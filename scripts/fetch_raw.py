"""Trae el raw de HabiCredit CO por ciudad y lo guarda como parquet.

Motor híbrido (revisión 2026-08-11):
  - Cantidad Desembolsos y Valor Desembolsado vienen de `mart_habicredit` con
    ciudad real derivada por `dim_brokers` (asignación exacta por NID).
  - Comisión Recibida, Pagada Externos y Pagada Internos vienen de `bet_data_p2`
    (fuente contable oficial, ancla en fecha del bill / T+1 vs desembolso).
    Los totales nacionales del BET se distribuyen por ciudad usando el share
    de valor desembolsado del mismo mes calendario (supuesto explícito).

Tablas usadas:
  - papyrus-master.liquidez_platinum_co.dim_brokers
  - papyrus-master.liquidez_gold_co.mart_habicredit
  - papyrus-delivery-data.habicredit.main_board
  - papyrus-delivery-data.habicredit.pipe_pago_comisiones_hc
  - papyrus-delivery-data.corp_gov_global.bet_data_p2

Mapping BET → dashboard:
  - Comisión Recibida   → m_tipo='1. Financials'  · m_categoria='01. Total Revenue' · m_metrica='03. HabiCredit'
  - Comisión Pagada Ext → m_tipo='1. Financials'  · m_categoria='02. Total Costs'   · m_metrica='03. HabiCredit Costs'
  - Comisión Pagada Int → m_tipo='1. Financials'  · m_categoria='03. Unit Costs'    · m_metrica='03. Commercial Costs' · m_submetrica='01. Internal' · m_negocio='03. Habicredit'

Convenciones:
  - Filtro `COALESCE(dummie_eliminaciones, 0) NOT IN (1, -1)` para excluir intercompañía.
  - Se usa `actuals_accounting` (revenue/costs habicredit en managerial vienen en 0).
  - Costs vienen negativos en BET; se toma `ABS()` para consistencia con el flujo dashboard
    (Neta = Recibida − Externos − Internos, los tres positivos).

Nota metodológica sobre el share por ciudad:
  El BET solo tiene granularidad país. Para mantener la vista por ciudad se aplica
  un share por (mes, ciudad) calculado como valor_desembolsado_ciudad / valor_total_mes.
  Es un supuesto: asume que el mix de comisiones bank-side/broker-side sigue la misma
  proporción que los desembolsos por ciudad. Se documenta en el dashboard.

Salida: 6 KPIs por (mes, ciudad):
  - Cantidad Desembolsos
  - Valor Desembolsado
  - Ticket Promedio
  - Comisión Recibida
  - Comisión Pagada Externos
  - Comisión Pagada Internos

Ciudades esperadas: Bogotá, Valle de Aburrá, Barranquilla, Cali, Otros
(más NULL→Bogotá por default).

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
      -- Códigos numéricos sin traducir en dim_brokers (confirmados con BI HabiCredit 2026-09-01):
      WHEN CAST(v.ciudad AS STRING) = '1' THEN 'Bogotá'
      WHEN CAST(v.ciudad AS STRING) = '2' THEN 'Valle de Aburrá'
      WHEN CAST(v.ciudad AS STRING) = '3' THEN 'Cali'
      WHEN CAST(v.ciudad AS STRING) = '4' THEN 'Otros'
      WHEN v.ciudad = 'Medellín' THEN 'Valle de Aburrá'
      WHEN v.ciudad = 'Ibagué' THEN 'Otros'
      WHEN v.ciudad = 'Bogotá D.C.' THEN 'Bogotá'
      ELSE (TRIM(v.ciudad))
    END AS ciudad
  FROM `papyrus-master.liquidez_platinum_co.dim_brokers` AS v
  LEFT JOIN (
    SELECT broker_id, COUNT(fecha_radicacion) AS radicaciones
    FROM `papyrus-delivery-data.habicredit.main_board`
    GROUP BY 1
  ) AS r ON r.broker_id = v.h_broker_pk
)

, pipe_para_ciudad AS (
  -- una sola fila por report_id, solo para identificar el broker gestor
  -- (no se usa para sumar montos de comisión, solo para asignar ciudad)
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
    COALESCE(cb1.ciudad, cb2.ciudad, 'Bogotá') AS ciudad,
    bd.report_id,
    bd.banco,
    bd.valor_desembolso
  FROM base_desembolsos AS bd
  LEFT JOIN pipe_para_ciudad AS p
    ON TRIM(CAST(bd.report_id AS STRING)) = TRIM(CAST(p.report_id AS STRING))
  LEFT JOIN ciudad_broker AS cb1
    ON LOWER(TRIM(p.correo_broker_financiero)) = cb1.correo_del_broker
  LEFT JOIN ciudad_broker AS cb2
    ON LOWER(TRIM(p.correo_broker)) = cb2.correo_del_broker
)

, metricas_desembolso AS (
  SELECT
    mes_radicado,
    ciudad,
    COUNT(*) AS cant_desembolsos,
    SUM(valor_desembolso) AS valor_desembolso
  FROM desembolsos_ciudad
  GROUP BY 1, 2
)

-- ============================================================
-- Nuevo motor híbrido: montos del BET, ciudad por share de desembolso
-- ============================================================

, share_valor_ciudad AS (
  -- share_ciudad = valor_desembolsado_ciudad / valor_desembolsado_total_mes
  -- se aplica a los totales del BET para distribuir por ciudad
  SELECT
    md.mes_radicado,
    md.ciudad,
    SAFE_DIVIDE(md.valor_desembolso, SUM(md.valor_desembolso) OVER (PARTITION BY md.mes_radicado)) AS share
  FROM metricas_desembolso AS md
)

, bet_habicredit_co_mes AS (
  -- Totales nacionales BET Habicredit CO por mes (actuals_accounting)
  -- Signos preservados como vienen del BET: Revenue positivo, Costs negativos
  SELECT
    mes AS mes_radicado,
    SUM(CASE
      WHEN m_categoria = '01. Total Revenue' AND m_metrica = '03. HabiCredit' THEN actuals_accounting
      ELSE 0 END) AS revenue_bet,
    SUM(CASE
      WHEN m_categoria = '02. Total Costs' AND m_metrica = '03. HabiCredit Costs' THEN actuals_accounting
      ELSE 0 END) AS externos_bet,
    SUM(CASE
      WHEN m_categoria = '03. Unit Costs' AND m_metrica = '03. Commercial Costs'
       AND m_submetrica = '01. Internal' AND m_negocio = '03. Habicredit' THEN actuals_accounting
      ELSE 0 END) AS internos_bet
  FROM `papyrus-delivery-data.corp_gov_global.bet_data_p2`
  WHERE m_pais = '1. Colombia'
    AND m_tipo = '1. Financials'
    AND mes >= '2024-08-01'
    AND COALESCE(dummie_eliminaciones, 0) NOT IN (1, -1)
    AND (
      (m_categoria = '01. Total Revenue' AND m_metrica = '03. HabiCredit')
      OR (m_categoria = '02. Total Costs' AND m_metrica = '03. HabiCredit Costs')
      OR (m_categoria = '03. Unit Costs' AND m_metrica = '03. Commercial Costs'
          AND m_submetrica = '01. Internal' AND m_negocio = '03. Habicredit')
    )
  GROUP BY mes
)

, comision_recibida_ciudad AS (
  SELECT
    b.mes_radicado,
    s.ciudad,
    b.revenue_bet * s.share AS valor
  FROM bet_habicredit_co_mes AS b
  JOIN share_valor_ciudad AS s USING (mes_radicado)
)

, comision_externa_ciudad AS (
  -- ABS() para consistencia con flujo dashboard (Neta = Recibida - Ext - Int, todos positivos)
  SELECT
    b.mes_radicado,
    s.ciudad,
    ABS(b.externos_bet) * s.share AS valor
  FROM bet_habicredit_co_mes AS b
  JOIN share_valor_ciudad AS s USING (mes_radicado)
)

, comision_interna_ciudad AS (
  SELECT
    b.mes_radicado,
    s.ciudad,
    ABS(b.internos_bet) * s.share AS valor
  FROM bet_habicredit_co_mes AS b
  JOIN share_valor_ciudad AS s USING (mes_radicado)
)

SELECT mes_radicado AS mes, ciudad, 'Cantidad Desembolsos' AS kpi, CAST(cant_desembolsos AS FLOAT64) AS valor
FROM metricas_desembolso

UNION ALL
SELECT mes_radicado, ciudad, 'Valor Desembolsado', valor_desembolso
FROM metricas_desembolso

UNION ALL
SELECT mes_radicado, ciudad, 'Ticket Promedio', SAFE_DIVIDE(valor_desembolso, cant_desembolsos)
FROM metricas_desembolso

UNION ALL
SELECT mes_radicado, ciudad, 'Comisión Recibida', valor
FROM comision_recibida_ciudad

UNION ALL
SELECT mes_radicado, ciudad, 'Comisión Pagada Externos', valor
FROM comision_externa_ciudad

UNION ALL
SELECT mes_radicado, ciudad, 'Comisión Pagada Internos', valor
FROM comision_interna_ciudad

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
