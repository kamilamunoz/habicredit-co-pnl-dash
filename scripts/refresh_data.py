"""Orquestador: lee data/raw_pl_habicredit_co.parquet, arma la tabla mensual
con las 15 líneas del P&L HabiCredit CO consolidado, aplica override manual
opcional de salarios y escribe site/data/kpi_pnl.json.

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
RAW_PATH = REPO_ROOT / "data" / "raw_pl_habicredit_co.parquet"
SALARIOS_MANUAL_PATH = REPO_ROOT / "data" / "salarios_manual.csv"
OUT_PATH = REPO_ROOT / "site" / "data" / "kpi_pnl.json"

# Estructura de la tabla en el orden que Pau usa:
#   type: 'row' (línea normal) | 'subtotal' (fondo morado)
#   sign: 'count' | 'money' | 'ratio' — controla formato en el frontend
#   key: identificador para el JSON (snake_case en español)
#   kpi_source: nombre EXACTO en la tabla pl_habicredit_colombia
#   pintar: True → subtotal morado
#
# Ojo con los espacios en los nombres source (la tabla los tiene tal cual).
PNL_STRUCTURE = [
    {"n": 1,  "key": "num_radicaciones",     "label": "Número Radicaciones",                     "type": "row",      "sign": "count",  "kpi_source": "Número Radicaciones"},
    {"n": 2,  "key": "num_desembolsos",      "label": "Número Desembolsos",                      "type": "row",      "sign": "count",  "kpi_source": "Número Desembolsos"},
    {"n": 3,  "key": "ticket_promedio",      "label": "Ticket Promedio",                         "type": "row",      "sign": "ratio",  "kpi_source": "Ticket Promedio"},
    {"n": 4,  "key": "valor_desembolsos",    "label": "Valor Desembolsos",                       "type": "row",      "sign": "money",  "kpi_source": "Valor Desembolsos"},
    {"n": 5,  "key": "comision_recibida_total", "label": "Comisión Recibida Total",              "type": "row",      "sign": "money",  "kpi_source": "Comisión Recibida Total"},
    {"n": 6,  "key": "comision_recibida",    "label": "Comisión Recibida",                       "type": "row",      "sign": "money",  "kpi_source": "Comisión Recibida"},
    {"n": 7,  "key": "comision_pagada_ext",  "label": "Comisión Pagada Externos",                "type": "row",      "sign": "money",  "kpi_source": "Comision Pagada Externos"},
    {"n": 8,  "key": "comision_neta",        "label": "Comisión Neta",                           "type": "subtotal", "sign": "money",  "kpi_source": "Comisión Neta"},
    {"n": 9,  "key": "subtotal_post_directos", "label": "Subtotal Margen Después de Costos Directos", "type": "subtotal", "sign": "money", "kpi_source": "Subtotal Margen Despues de Costos Directos"},
    {"n": 10, "key": "subtotal_post_com",    "label": "Subtotal (margen − gastos comerciales)",  "type": "subtotal", "sign": "money",  "kpi_source": "Subtotal (margen - gastos comerciales)"},
    {"n": 11, "key": "salarios_comercial",   "label": "Salarios equipo comercial y operativo",   "type": "row",      "sign": "money",  "kpi_source": "Salarios equipo comercial y operativo "},
    {"n": 12, "key": "subtotal_post_sal_op", "label": "Sub Total (margen − salarios operativos)", "type": "subtotal", "sign": "money", "kpi_source": "Sub Total (margen - salarios operativos)"},
    {"n": 13, "key": "salarios_admin",       "label": "Salarios equipo administrativo",          "type": "row",      "sign": "money",  "kpi_source": "Salarios equipo administrativo"},
    {"n": 14, "key": "subtotal_post_sal_infra", "label": "Subtotal (margen − salarios infra)",   "type": "subtotal", "sign": "money",  "kpi_source": "Subtotal (margen - salarios infra)"},
    {"n": 15, "key": "margen_neto",          "label": "Margen Neto",                             "type": "subtotal", "sign": "money",  "kpi_source": "Margen Neto"},
]

# KPIs cuyo valor "total mes" es la SUMA de todas las filas del mes con ese kpi
# (típicamente los desembolsos por banco). Los subtotales precalculados vienen
# como fila única, no requieren agregación.
SUMMABLE_KPIS = {
    "Número Radicaciones",
    "Número Desembolsos",
    "Ticket Promedio",
    "Valor Desembolsos",
    "Comisión Recibida Total",
    "Comisión Recibida",
    "Comision Pagada Externos",
    "Salarios equipo comercial y operativo ",
    "Salarios equipo administrativo",
}

# Para líneas de tipo ratio (Ticket Promedio) NO queremos sumar — usamos la
# fila total (con descripcion IS NULL AND detalle IS NULL). Si no existe, la
# recalculamos como Valor Desembolsos / Número Desembolsos.
RATIO_KPIS = {"Ticket Promedio"}


def _total_per_month(df: pd.DataFrame, kpi: str) -> pd.Series:
    """Devuelve una Series indexada por mes (YYYY-MM) con el valor total para el kpi."""
    sub = df.loc[df["kpi"] == kpi].copy()
    if sub.empty:
        return pd.Series(dtype=float)

    if kpi in RATIO_KPIS:
        # Preferimos la fila con descripcion IS NULL AND detalle IS NULL.
        totals = sub.loc[sub["descripcion"].isna() & sub["detalle"].isna()].copy()
        if not totals.empty:
            return totals.groupby("mes")["valor"].first()

    if kpi in SUMMABLE_KPIS:
        # Fallback: sumar todas las filas del mes (para el total real).
        # Pero preferimos la fila total si existe (más consistente con Pau).
        totals = sub.loc[sub["descripcion"].isna() & sub["detalle"].isna()].copy()
        if not totals.empty:
            return totals.groupby("mes")["valor"].first()
        return sub.groupby("mes")["valor"].sum()

    # Subtotales precalculados: fila única por mes.
    return sub.groupby("mes")["valor"].first()


def _load_salarios_override() -> dict | None:
    """Lee data/salarios_manual.csv si existe. Devuelve {mes: {comercial, admin}}."""
    if not SALARIOS_MANUAL_PATH.exists():
        return None
    log.info("Encontrado override manual de salarios: %s", SALARIOS_MANUAL_PATH)
    csv = pd.read_csv(SALARIOS_MANUAL_PATH)
    csv["mes"] = csv["mes"].astype(str)  # esperamos "YYYY-MM"
    out = {}
    for _, row in csv.iterrows():
        out[row["mes"]] = {
            "comercial": float(row.get("salarios_comercial", 0) or 0),
            "admin": float(row.get("salarios_admin", 0) or 0),
        }
    log.info("Override de salarios cargado para %d meses", len(out))
    return out


def main() -> None:
    if not RAW_PATH.exists():
        raise SystemExit(f"No existe {RAW_PATH}. Corre `make raw` primero.")

    log.info("Leyendo %s ...", RAW_PATH)
    raw = pd.read_parquet(RAW_PATH)
    log.info("Raw: %d filas", len(raw))

    # normalizar mes a YYYY-MM string
    raw["mes"] = pd.to_datetime(raw["mes"]).dt.strftime("%Y-%m")

    mes_cutoff = os.environ.get("MES_CUTOFF", "").strip()
    if mes_cutoff:
        antes = len(raw)
        raw = raw.loc[raw["mes"] <= mes_cutoff].copy()
        log.info("Cutoff %s aplicado: %d filas (excluidas %d)", mes_cutoff, len(raw), antes - len(raw))

    # meses disponibles ordenados
    meses = sorted(raw["mes"].unique().tolist())
    log.info("Meses en raw: %d (%s → %s)", len(meses), meses[0], meses[-1])

    # override manual de salarios (opcional)
    salarios_override = _load_salarios_override()

    # Construir la tabla: {mes → {key → valor}}
    values_per_month: dict[str, dict[str, float]] = {m: {} for m in meses}

    for line in PNL_STRUCTURE:
        series = _total_per_month(raw, line["kpi_source"])
        for m in meses:
            v = series.get(m, None)
            if v is None or pd.isna(v):
                # Fallback Ticket Promedio si no hay fila total
                if line["key"] == "ticket_promedio":
                    vd = _total_per_month(raw, "Valor Desembolsos").get(m)
                    nd = _total_per_month(raw, "Número Desembolsos").get(m)
                    if vd and nd:
                        v = float(vd) / float(nd)
                    else:
                        v = None
            values_per_month[m][line["key"]] = None if v is None else float(v)

    # aplicar override de salarios y recalcular subtotales dependientes
    if salarios_override:
        for m, ov in salarios_override.items():
            if m not in values_per_month:
                continue
            values_per_month[m]["salarios_comercial"] = ov["comercial"]
            values_per_month[m]["salarios_admin"] = ov["admin"]
            # recalcular subtotales downstream:
            #   subtotal_post_sal_op = subtotal_post_com − salarios_comercial
            #   subtotal_post_sal_infra = subtotal_post_sal_op − salarios_admin
            #   margen_neto = subtotal_post_sal_infra
            base = values_per_month[m].get("subtotal_post_com")
            if base is not None:
                s_op = base - ov["comercial"]
                values_per_month[m]["subtotal_post_sal_op"] = s_op
                s_infra = s_op - ov["admin"]
                values_per_month[m]["subtotal_post_sal_infra"] = s_infra
                values_per_month[m]["margen_neto"] = s_infra
            log.info("Override aplicado para %s: comercial=%s, admin=%s", m, ov["comercial"], ov["admin"])

    # Estructura para el frontend (solo campos que usa el JS)
    estructura = [
        {"n": r["n"], "key": r["key"], "label": r["label"], "type": r["type"], "sign": r["sign"]}
        for r in PNL_STRUCTURE
    ]

    payload = {
        "meta": {
            "generado_en": datetime.now().isoformat(timespec="seconds"),
            "tabla_fuente": "papyrus-delivery-data.corp_gov_global.pl_habicredit_colombia",
            "cohorte": "mes (primer día del mes calendario)",
            "currency": "COP",
            "unidad": "unidades absolutas (el frontend divide por 1_000_000 para mostrar en millones)",
            "consolidado": "MM Mortgages + Non-MM + Bancario + HC100 (los 4 productos ya vienen consolidados en la tabla)",
            "salarios_override_activo": bool(salarios_override),
            "filas_raw": int(len(raw)),
            "rango_meses": {"min": meses[0], "max": meses[-1]},
        },
        "estructura": estructura,
        "meses": meses,
        "valores": values_per_month,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))

    log.info("Escrito → %s (%.1f KB)", OUT_PATH, OUT_PATH.stat().st_size / 1024)


if __name__ == "__main__":
    main()
