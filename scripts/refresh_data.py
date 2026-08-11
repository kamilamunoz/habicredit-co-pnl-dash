"""Orquestador: lee data/raw_habicredit_ciudad.parquet, arma la tabla mensual
con las 8 líneas del P&L HabiCredit CO por ciudad (Total + ciudades reales) y
escribe site/data/kpi_pnl.json.

Estructura de 7 líneas:
    1. Cantidad Desembolsos               (count)
    2. Valor Desembolsado                 (monto COP)
    3. Ticket Promedio                    (monto COP, mostrado en MM como los demás)
    4. Comisión Recibida                  (monto COP)
    5. Comisión Pagada Externos           (monto COP)
    6. Comisión Pagada Internos           (monto COP)
    7. Margen de Contribución = 4 − 5 − 6 (subtotal morado)

La fila `Total` se calcula como suma de las ciudades reales (Bogotá + Valle de
Aburrá + Otros + cualquier otra que aparezca en el raw). Ticket Promedio del
Total se RECALCULA: valor_total / cantidad_total (nunca suma).

Uso:
    make refresh

Opcional:
    MES_CUTOFF=YYYY-MM   Excluye meses posteriores al cutoff (inclusive).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import db_dtypes  # noqa: F401  registra tipos dbdate/dbtime del parquet
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s · %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = REPO_ROOT / "data" / "raw_habicredit_ciudad.parquet"
OUT_PATH = REPO_ROOT / "site" / "data" / "kpi_pnl.json"

# Orden preferido de ciudades en el dropdown. Cualquier otra ciudad que salga
# del raw se anexa al final en orden alfabético.
CIUDAD_ORDER = ["Bogotá", "Valle de Aburrá", "Barranquilla", "Cali", "Otros"]

# Normalización de ciudades a la nomenclatura canónica del dashboard.
#   - 'Bogotá D.C.' llega del CTE ciudad_broker sin normalizar (el CASE solo
#     cubre 'Medellín' y 'Ibagué'); es la MISMA ciudad que 'Bogotá'.
CIUDAD_NORMALIZE = {
    "Bogotá D.C.": "Bogotá",
    "bogotá d.c.": "Bogotá",
    "BOGOTÁ D.C.": "Bogotá",
}

# Basura conocida en el campo `ciudad` de dim_brokers (valores literales '1','2','3'
# capturados en el formulario). Se descartan.
CIUDAD_DESCARTAR = {"1", "2", "3"}

# Rango temporal válido. Si aparece un mes fuera (p.ej. '2925-11-01' por typo en
# fecha_desembolso), se filtra.
MES_MIN = "2024-01"
MES_MAX_HARD = "2027-12"

# Mapeo KPI del raw → key del JSON
KPI_SOURCE_TO_KEY = {
    "Cantidad Desembolsos": "cant_desembolsos",
    "Valor Desembolsado": "valor_desembolsado",
    "Ticket Promedio": "ticket_promedio",
    "Comisión Recibida": "comision_recibida",
    "Comisión Pagada Externos": "comision_externos",
    "Comisión Pagada Internos": "comision_internos",
}

# Estructura de las 8 líneas para el frontend.
#   tipo: 'count' → entero (# desembolsos)
#         'monto' → COP (frontend divide por 1e6 salvo ticket_promedio)
#   subtotal: True → fondo morado
KPIS_STRUCTURE = [
    {"key": "cant_desembolsos",   "label": "Cantidad Desembolsos",     "tipo": "count", "subtotal": False},
    {"key": "valor_desembolsado", "label": "Valor Desembolsado",       "tipo": "monto", "subtotal": False},
    {"key": "ticket_promedio",    "label": "Ticket Promedio",          "tipo": "monto", "subtotal": False},
    {"key": "comision_recibida",  "label": "Comisión Recibida",        "tipo": "monto", "subtotal": False},
    {"key": "comision_externos",  "label": "Comisión Pagada Externos", "tipo": "monto", "subtotal": False},
    {"key": "comision_internos",  "label": "Comisión Pagada Internos", "tipo": "monto", "subtotal": False},
    {"key": "margen_neto",        "label": "Margen de Contribución",   "tipo": "monto", "subtotal": True},
]


def _ordered_ciudades(ciudades_raw: list[str]) -> list[str]:
    """Ordena las ciudades del raw usando CIUDAD_ORDER como prioridad."""
    ordered = [c for c in CIUDAD_ORDER if c in ciudades_raw]
    extras = sorted([c for c in ciudades_raw if c not in CIUDAD_ORDER])
    return ordered + extras


def _build_ciudad_month_values(
    raw: pd.DataFrame, ciudad: str, meses: list[str]
) -> dict[str, dict[str, float | None]]:
    """Devuelve {mes → {key → valor}} para una ciudad específica (los 6 KPIs base
    del raw, sin calcular subtotales aún)."""
    out: dict[str, dict[str, float | None]] = {m: {} for m in meses}
    sub = raw.loc[raw["ciudad"] == ciudad]
    for m in meses:
        row = sub.loc[sub["mes"] == m]
        for kpi_src, key in KPI_SOURCE_TO_KEY.items():
            match = row.loc[row["kpi"] == kpi_src, "valor"]
            v = float(match.iloc[0]) if len(match) else None
            if v is not None and pd.isna(v):
                v = None
            out[m][key] = v
    return out


def _finalize_values(
    values: dict[str, dict[str, float | None]],
) -> dict[str, dict[str, float | None]]:
    """Agrega margen_neto (= Margen de Contribución) a cada mes.

    Margen de Contribución = Comisión Recibida − Externos − Internos.
    """
    for m, kv in values.items():
        cr = kv.get("comision_recibida")
        ce = kv.get("comision_externos")
        ci = kv.get("comision_internos")
        parts = [x for x in (cr, ce, ci) if x is not None]
        if not parts:
            kv["margen_neto"] = None
        else:
            kv["margen_neto"] = (cr or 0.0) - (ce or 0.0) - (ci or 0.0)
    return values


def _sum_or_none(vals: list[float | None]) -> float | None:
    clean = [v for v in vals if v is not None]
    if not clean:
        return None
    return float(sum(clean))


def _build_total(
    per_city: dict[str, dict[str, dict[str, float | None]]], meses: list[str]
) -> dict[str, dict[str, float | None]]:
    """Consolida el Total sumando ciudades reales. Ticket Promedio se recalcula
    como valor_desembolsado_total / cant_desembolsos_total."""
    total: dict[str, dict[str, float | None]] = {}
    for m in meses:
        kv: dict[str, float | None] = {}
        # KPIs que se SUMAN
        for key in [
            "cant_desembolsos",
            "valor_desembolsado",
            "comision_recibida",
            "comision_externos",
            "comision_internos",
        ]:
            kv[key] = _sum_or_none([per_city[c][m].get(key) for c in per_city])
        # Ticket promedio: recalcular
        vd = kv.get("valor_desembolsado")
        nd = kv.get("cant_desembolsos")
        if vd is not None and nd not in (None, 0):
            kv["ticket_promedio"] = vd / nd
        else:
            kv["ticket_promedio"] = None
        total[m] = kv
    return _finalize_values(total)


def main() -> None:
    if not RAW_PATH.exists():
        raise SystemExit(f"No existe {RAW_PATH}. Corre `make raw` primero.")

    log.info("Leyendo %s ...", RAW_PATH)
    raw = pd.read_parquet(RAW_PATH)
    log.info("Raw: %d filas", len(raw))

    # normalizar mes a YYYY-MM string
    raw["mes"] = pd.to_datetime(raw["mes"]).dt.strftime("%Y-%m")
    # normalizar ciudad (NaN → 'Bogotá' como fallback, ya lo hace el SQL pero
    # cinturón y tirantes)
    raw["ciudad"] = raw["ciudad"].fillna("Bogotá")
    # aplicar mapeo de nomenclatura canónica (Bogotá D.C. → Bogotá)
    raw["ciudad"] = raw["ciudad"].replace(CIUDAD_NORMALIZE)

    # descartar basura del campo `ciudad` en dim_brokers ('1','2','3')
    antes = len(raw)
    raw = raw.loc[~raw["ciudad"].isin(CIUDAD_DESCARTAR)].copy()
    if antes != len(raw):
        log.info("Descartadas %d filas de ciudades basura {'1','2','3'}", antes - len(raw))

    # filtrar rango temporal válido (bloquea typos tipo '2925-11')
    antes = len(raw)
    raw = raw.loc[(raw["mes"] >= MES_MIN) & (raw["mes"] <= MES_MAX_HARD)].copy()
    if antes != len(raw):
        log.info("Descartadas %d filas fuera de rango [%s..%s]",
                 antes - len(raw), MES_MIN, MES_MAX_HARD)

    # Reagregar tras normalización de ciudades: si 'Bogotá' y 'Bogotá D.C.' quedaron
    # ambos como 'Bogotá', sumar por (mes, ciudad, kpi). Para 'Ticket Promedio'
    # la suma NO es correcta — se recalcula después como valor/cant al construir
    # per_city (se sobreescribe cualquier valor sumado con el correcto ahí).
    raw = raw.groupby(["mes", "ciudad", "kpi"], as_index=False)["valor"].sum()

    mes_cutoff = os.environ.get("MES_CUTOFF", "").strip()
    if mes_cutoff:
        antes = len(raw)
        raw = raw.loc[raw["mes"] <= mes_cutoff].copy()
        log.info(
            "Cutoff %s aplicado: %d filas (excluidas %d)",
            mes_cutoff, len(raw), antes - len(raw),
        )

    meses = sorted(raw["mes"].unique().tolist())
    if not meses:
        raise SystemExit("Raw quedó vacío tras el cutoff.")
    log.info("Meses en raw: %d (%s → %s)", len(meses), meses[0], meses[-1])

    ciudades_raw = sorted(raw["ciudad"].dropna().unique().tolist())
    ciudades_real = _ordered_ciudades(ciudades_raw)
    log.info("Ciudades reales detectadas: %s", ciudades_real)

    # Values por ciudad (6 KPIs base + subtotales)
    per_city: dict[str, dict[str, dict[str, float | None]]] = {}
    for c in ciudades_real:
        vals = _build_ciudad_month_values(raw, c, meses)
        # Recalcular Ticket Promedio = Valor Desembolsado / Cantidad Desembolsos
        # para blindar contra sumas incorrectas tras la reagrupación por
        # normalización de ciudades (Bogotá D.C. → Bogotá).
        for m in meses:
            vd = vals[m].get("valor_desembolsado")
            nd = vals[m].get("cant_desembolsos")
            if vd is not None and nd not in (None, 0):
                vals[m]["ticket_promedio"] = vd / nd
            else:
                vals[m]["ticket_promedio"] = None
        vals = _finalize_values(vals)
        per_city[c] = vals

    # Total consolidado
    total = _build_total(per_city, meses)

    # Mes en curso (MTD): NULLear comisiones y Neta.
    # Motivo: el BET (fuente de las comisiones) reconoce el ingreso/costo cuando
    # cae el bill contable, que se emite T+1 respecto al desembolso. En el mes
    # en curso el BET siempre está incompleto — mostrar las cifras parciales
    # crea la ilusión de una Neta negativa que se corregirá al cerrar el ciclo.
    # Los datos operativos (Cant, Valor, Ticket) sí se mantienen — son reales.
    mtd = meses[-1]
    _COMISION_KEYS_MTD = (
        "comision_recibida",
        "comision_externos",
        "comision_internos",
        "margen_neto",
    )
    for c in ciudades_real:
        for k in _COMISION_KEYS_MTD:
            per_city[c][mtd][k] = None
    for k in _COMISION_KEYS_MTD:
        total[mtd][k] = None
    log.info("MTD %s: comisiones/neta forzadas a NULL (BET incompleto por T+1)", mtd)

    # Ciudad list final: Total primero, luego ciudades reales
    ciudades_output = ["Total"] + ciudades_real

    data_out: dict[str, dict[str, dict[str, float | None]]] = {"Total": total}
    for c in ciudades_real:
        data_out[c] = per_city[c]

    payload = {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "cutoff": mes_cutoff or None,
            "mtd_month": meses[-1],
            "rango_meses": {"min": meses[0], "max": meses[-1]},
            "currency": "COP",
            "unidad": "unidades absolutas (frontend divide monto por 1e6 excepto ticket_promedio)",
            "fuente": "query oficial Pau — cross-project papyrus-master + papyrus-delivery-data",
            "ciudades_reales": ciudades_real,
        },
        "ciudades": ciudades_output,
        "kpis": KPIS_STRUCTURE,
        "meses": meses,
        "data": data_out,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    log.info("Escrito → %s (%.1f KB)", OUT_PATH, OUT_PATH.stat().st_size / 1024)

    # Sanity log del último mes por ciudad
    last = meses[-1]
    log.info("--- Sanity check %s ---", last)
    for c in ciudades_output:
        kv = data_out[c][last]
        log.info(
            "  %-16s cant=%s valor=%s margen=%s",
            c,
            kv.get("cant_desembolsos"),
            kv.get("valor_desembolsado"),
            kv.get("margen_neto"),
        )


if __name__ == "__main__":
    main()
