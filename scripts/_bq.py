"""Cliente de BigQuery.

Usa Application Default Credentials (ADC). Antes del primer uso:
    gcloud auth application-default login

Si Python falla con error de permiso 'serviceusage.serviceUsageConsumer',
borra el quota_project_id del archivo ADC:
    python -c "import json,os; p=os.path.expanduser('~/.config/gcloud/application_default_credentials.json'); d=json.load(open(p)); d.pop('quota_project_id',None); json.dump(d,open(p,'w'),indent=2)"
"""

from __future__ import annotations

import logging

import pandas as pd
from google.cloud import bigquery

# Billing project. Kamila tiene bigquery.jobs.create en papyrus-delivery-data.
# El query oficial que Pau usa toca varias tablas cross-project (papyrus-master,
# papyrus-delivery-data). Se factura en papyrus-delivery-data.
BILLING_PROJECT = "papyrus-delivery-data"

log = logging.getLogger(__name__)


def get_client() -> bigquery.Client:
    return bigquery.Client(project=BILLING_PROJECT)


def run_query(sql: str, *, label: str | None = None) -> pd.DataFrame:
    """Ejecuta una query y devuelve un DataFrame. Loguea bytes facturados."""
    client = get_client()
    job = client.query(sql)
    df = job.to_dataframe(create_bqstorage_client=False)
    bytes_billed = job.total_bytes_billed or 0
    gb_billed = bytes_billed / 1024**3
    tag = f"[{label}] " if label else ""
    log.info("%squery OK · %d filas · %.2f GB facturados", tag, len(df), gb_billed)
    return df
