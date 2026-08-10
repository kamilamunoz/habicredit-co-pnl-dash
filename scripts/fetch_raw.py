"""Trae el raw de pl_habicredit_colombia y lo guarda como parquet.

Nota sobre la tabla `papyrus-delivery-data.corp_gov_global.pl_habicredit_colombia`:
- Es la tabla canónica que Pau usa hoy: 32 KPIs y 4 subtotales precalculados.
- Los TOTALES por mes viven en filas con `descripcion IS NULL AND detalle IS NULL`.
- Los DESGLOSES (por banco / por área) viven en filas hijas con `descripcion`/`detalle` poblados.
- Los 4 productos (MM Mortgages, Non-MM, Bancario, HC100) YA están consolidados en las filas totales.

Uso:
    make raw
"""

from __future__ import annotations

import logging
from pathlib import Path

from scripts._bq import BILLING_PROJECT, TABLE_PL_HBC_CO, run_query

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s · %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "data" / "raw_pl_habicredit_co.parquet"

# Los 15 KPIs canónicos que Pau necesita (exactamente como aparecen en la tabla).
# Ojo: "Salarios equipo comercial y operativo " tiene un espacio al final en la tabla,
# lo respetamos.
KPIS_15 = [
    "Número Radicaciones",
    "Número Desembolsos",
    "Ticket Promedio",
    "Valor Desembolsos",
    "Comisión Recibida Total",
    "Comisión Recibida",
    "Comision Pagada Externos",
    "Comisión Neta",
    "Subtotal Margen Despues de Costos Directos",
    "Subtotal (margen - gastos comerciales)",
    "Salarios equipo comercial y operativo ",
    "Sub Total (margen - salarios operativos)",
    "Salarios equipo administrativo",
    "Subtotal (margen - salarios infra)",
    "Margen Neto",
]

# Ventana temporal: desde mar-2026 (arranque del análisis Pau) hasta 6 meses
# adelante para incluir MTD. El script filtra automáticamente por rango en
# refresh_data.py; acá jalamos un rango amplio por si en el futuro Kamila
# quiere ver histórico completo.
QUERY = f"""
select
    mes,
    kpi,
    descripcion,
    detalle,
    valor
from `{TABLE_PL_HBC_CO}`
where mes between date('2024-01-01') and date_add(current_date(), interval 3 month)
  and kpi in (
    'Número Radicaciones',
    'Número Desembolsos',
    'Ticket Promedio',
    'Valor Desembolsos',
    'Comisión Recibida Total',
    'Comisión Recibida',
    'Comision Pagada Externos',
    'Comisión Neta',
    'Subtotal Margen Despues de Costos Directos',
    'Subtotal (margen - gastos comerciales)',
    'Salarios equipo comercial y operativo ',
    'Sub Total (margen - salarios operativos)',
    'Salarios equipo administrativo',
    'Subtotal (margen - salarios infra)',
    'Margen Neto'
  )
"""


def main() -> None:
    log.info("Trayendo raw de %s (billing=%s) ...", TABLE_PL_HBC_CO, BILLING_PROJECT)
    df = run_query(QUERY, label="pl_habicredit_co_raw")
    log.info("Total filas: %d", len(df))
    if len(df) == 0:
        raise SystemExit("Query devolvió 0 filas. Revisa la tabla o el filtro de KPIs.")

    log.info("Rango mes: %s → %s", df["mes"].min(), df["mes"].max())
    log.info("KPIs únicos: %d", df["kpi"].nunique())
    for k in KPIS_15:
        n = int((df["kpi"] == k).sum())
        log.info("  · %s: %d filas", k, n)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT_PATH, index=False)
    log.info("Escrito → %s (%.1f KB)", OUT_PATH, OUT_PATH.stat().st_size / 1024)


if __name__ == "__main__":
    main()
