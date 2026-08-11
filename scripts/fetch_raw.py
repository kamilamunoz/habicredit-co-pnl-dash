"""Trae el raw de HabiCredit CO por ciudad y lo guarda como parquet.

Fuente: query oficial que Pau usa para P&L HabiCredit CO por ciudad.
Toca varias tablas cross-project (papyrus-master, papyrus-delivery-data):
  - papyrus-master.liquidez_platinum_co.dim_brokers
  - papyrus-master.liquidez_gold_co.mart_habicredit
  - papyrus-delivery-data.habicredit.main_board
  - papyrus-delivery-data.habicredit.pipe_pago_comisiones_hc
  - papyrus-delivery-data.habicredit.cs_comisiones_internas_hc_finanzas  (mirror de sheet)
  - papyrus-delivery-data.corp_gov_global.cs_tarifa_comisiones_habicredit  (mirror de sheet)

Nota: las 2 tablas `cs_*` son materializadas espejo de las tablas sheet-backed
originales (`tarifa_comisiones_habicredit`, `comisiones_internas_hc_finanzas`).
Kamila las mantiene sincronizadas; se usan porque el ADC de Python no tiene
scope de Drive, mientras que las espejo son tablas nativas de BigQuery.

Salida: 6 KPIs por (mes, ciudad):
  - Cantidad Desembolsos
  - Valor Desembolsado
  - Ticket Promedio
  - Comisión Recibida
  - Comisión Pagada Externos
  - Comisión Pagada Internos

Ciudades esperadas: Bogotá, Valle de Aburrá, Otros (más NULL→Bogotá por default).

Uso:
    make raw
"""

from __future__ import annotations

import logging
from pathlib import Path

from scripts._bq import BILLING_PROJECT, run_query

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s · %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "data" / "raw_habicredit_ciudad.parquet"

QUERY = """
WITH ciudad_broker AS (
  SELECT DISTINCT
    LOWER(TRIM(COALESCE(v.correo_habi, v.correo_personal))) AS correo_del_broker,
    CASE
      WHEN v.ciudad IS NULL THEN 'Bogotá'
      WHEN CAST(v.ciudad AS STRING) = '1' THEN 'Bogotá'
      WHEN v.ciudad = 'Medellín' THEN 'Valle de Aburrá'
      WHEN v.ciudad = 'Ibagué' THEN 'Otros'
      ELSE v.ciudad
    END AS ciudad
  FROM `papyrus-master.liquidez_platinum_co.dim_brokers` AS v
  LEFT JOIN (
    SELECT broker_id, COUNT(fecha_radicacion) AS radicaciones
    FROM `papyrus-delivery-data.habicredit.main_board`
    GROUP BY 1
  ) AS r ON r.broker_id = v.h_broker_pk
)
, pipe_para_ciudad AS (
  SELECT DISTINCT
    report_id,
    correo_broker_financiero,
    correo_broker
  FROM `papyrus-delivery-data.habicredit.pipe_pago_comisiones_hc`
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY report_id
    ORDER BY numero_orden_de_compra
  ) = 1
)
, base_desembolsos AS (
  SELECT
    DATE_TRUNC(DATE(m.fecha_desembolso), MONTH) AS mes_radicado,
    m.report_id,
    CASE
      WHEN UPPER(m.banco)='BANCODEBOGOTA' THEN 'BANCO DE BOGOTÁ'
      WHEN UPPER(m.banco)='ITAU' THEN 'ITAÚ'
      WHEN UPPER(m.banco)='AV VILLAS' THEN 'AV. VILLAS'
      WHEN UPPER(m.banco)='COLPATRIA' THEN 'SCOTIABANK COLPATRIA'
      ELSE UPPER(m.banco) END AS banco,
    m.monto_desembolso AS valor_desembolso
  FROM `papyrus-master.liquidez_gold_co.mart_habicredit` AS m
  WHERE DATE_TRUNC(DATE(m.fecha_desembolso), MONTH) >= '2024-01-01'
)
, desembolsos_ciudad AS (
  SELECT
    bd.mes_radicado,
    COALESCE(cb1.ciudad, cb2.ciudad) AS ciudad,
    bd.report_id,
    bd.banco,
    bd.valor_desembolso
  FROM base_desembolsos AS bd
  LEFT JOIN pipe_para_ciudad AS p
    ON CAST(bd.report_id AS STRING) = p.report_id
  LEFT JOIN ciudad_broker AS cb1
    ON LOWER(TRIM(p.correo_broker_financiero)) = cb1.correo_del_broker
  LEFT JOIN ciudad_broker AS cb2
    ON LOWER(TRIM(p.correo_broker)) = cb2.correo_del_broker
)
, metricas_desembolso AS (
  SELECT mes_radicado,
  COALESCE(ciudad,'Bogotá') AS ciudad,
    COUNT(*) AS cant_desembolsos,
    SUM(valor_desembolso) AS valor_desembolso
  FROM desembolsos_ciudad
  GROUP BY 1, 2
)
, comision_por_desembolso AS (
  SELECT
    dc.mes_radicado,
    dc.ciudad,
    dc.report_id,
    dc.valor_desembolso * s.porcentaje_comision AS comision
  FROM desembolsos_ciudad AS dc
  LEFT JOIN `papyrus-delivery-data.corp_gov_global.cs_tarifa_comisiones_habicredit` AS s
    ON dc.banco = s.banco
    AND dc.valor_desembolso >= s.limite_inferior
    AND dc.valor_desembolso <= s.limite_superior
    AND s.fecha <= DATE_TRUNC(dc.mes_radicado, YEAR)
  QUALIFY ROW_NUMBER() OVER (
    PARTITION BY dc.mes_radicado, dc.ciudad, dc.report_id
    ORDER BY s.fecha DESC
  ) = 1
)
, comision_recibida_ciudad AS (
  SELECT
    mes_radicado,
    COALESCE(ciudad,'Bogotá') AS ciudad,
    SUM(comision) AS valor
  FROM comision_por_desembolso
  GROUP BY 1, 2
)
, comision_externa_ciudad AS (
  SELECT
    DATE_TRUNC(p.fecha_desembolso, MONTH) AS mes_radicado,
    COALESCE(cb1.ciudad, cb2.ciudad,'Bogotá') AS ciudad,
    SUM(SAFE_CAST(REPLACE(p.valor_comision_bruto, ",", "") AS FLOAT64)) AS valor
  FROM `papyrus-delivery-data.habicredit.pipe_pago_comisiones_hc` AS p
  LEFT JOIN ciudad_broker AS cb1
    ON LOWER(TRIM(p.correo_broker_financiero)) = cb1.correo_del_broker
  LEFT JOIN ciudad_broker AS cb2
    ON LOWER(TRIM(p.correo_broker)) = cb2.correo_del_broker
  WHERE DATE_TRUNC(p.fecha_desembolso, MONTH) >= '2024-08-01'
  GROUP BY 1, 2
)
, comision_interna_ciudad AS (
  SELECT
    ci.mes_comision AS mes_radicado,
    COALESCE(cb.ciudad,'Bogotá') AS ciudad,
    SUM(ci.pago) AS valor
  FROM (
    SELECT mes_comision, beneficiado AS correo_broker, SUM(pago) AS pago
    FROM `papyrus-delivery-data.habicredit.cs_comisiones_internas_hc_finanzas`
    GROUP BY 1, 2
  ) AS ci
  LEFT JOIN ciudad_broker AS cb
    ON LOWER(TRIM(ci.correo_broker)) = cb.correo_del_broker
  GROUP BY 1, 2
)
SELECT mes_radicado AS mes, COALESCE(ciudad,'Bogotá') AS ciudad, 'Cantidad Desembolsos' AS kpi, CAST(cant_desembolsos AS FLOAT64) AS valor
FROM metricas_desembolso
UNION ALL
SELECT mes_radicado, COALESCE(ciudad,'Bogotá'), 'Valor Desembolsado', valor_desembolso FROM metricas_desembolso
UNION ALL
SELECT mes_radicado, COALESCE(ciudad,'Bogotá'), 'Ticket Promedio', SAFE_DIVIDE(valor_desembolso, cant_desembolsos) FROM metricas_desembolso
UNION ALL
SELECT mes_radicado, COALESCE(ciudad,'Bogotá'), 'Comisión Recibida', valor FROM comision_recibida_ciudad
UNION ALL
SELECT mes_radicado, COALESCE(ciudad,'Bogotá'), 'Comisión Pagada Externos', valor FROM comision_externa_ciudad
UNION ALL
SELECT mes_radicado, COALESCE(ciudad,'Bogotá'), 'Comisión Pagada Internos', valor FROM comision_interna_ciudad
ORDER BY mes DESC, ciudad
"""


def main() -> None:
    log.info("Trayendo raw HabiCredit CO por ciudad (billing=%s) ...", BILLING_PROJECT)
    df = run_query(QUERY, label="habicredit_co_ciudad_raw")
    log.info("Total filas: %d", len(df))
    if len(df) == 0:
        raise SystemExit("Query devolvió 0 filas. Revisa tablas/permisos.")

    log.info("Rango mes: %s → %s", df["mes"].min(), df["mes"].max())
    log.info("Ciudades únicas: %s", sorted(df["ciudad"].dropna().unique().tolist()))
    log.info("KPIs únicos: %s", sorted(df["kpi"].unique().tolist()))
    for k in sorted(df["kpi"].unique().tolist()):
        n = int((df["kpi"] == k).sum())
        log.info("  · %s: %d filas", k, n)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    log.info("Escrito → %s (%.1f KB)", OUT_PATH, OUT_PATH.stat().st_size / 1024)


if __name__ == "__main__":
    main()
