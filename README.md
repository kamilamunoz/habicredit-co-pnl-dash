# habicredit-co-pnl-dash

Dashboard live del P&L consolidado de **HabiCredit CO** (los 4 productos: MM Mortgages / Non-MM / Bancario / HC100).

Réplica en la línea de `co-city-pnl-dash`. Sitio estático (HTML + CSS + vanilla JS) publicado en GitHub Pages, con refresh manual de datos contra BigQuery.

## URLs
- **Live**: https://kamilamunoz.github.io/habicredit-co-pnl-dash/
- **Local**: http://localhost:8004/site/

## Password
Password del gate del login: `p&L_HbC*C0l*C12d4d` (definida en `site/js/app.js`, constante `PASSWORD`).

## Fuente de datos
`papyrus-delivery-data.corp_gov_global.pl_habicredit_colombia`

Columnas: `mes` (DATE, 1er del mes), `kpi` (STRING), `descripcion` (STRING), `detalle` (STRING), `valor` (FLOAT64).

Los totales por mes viven en las filas con `descripcion IS NULL AND detalle IS NULL`. Los desgloses (por banco, por área) viven en filas hijas.

Billing project: `papyrus-delivery-data` (Kamila no tiene `bigquery.jobs.create` en `clients-domain-data-master`).

## Estructura de las 15 líneas

1. Número Radicaciones
2. Número Desembolsos
3. Ticket Promedio
4. Valor Desembolsos
5. Comisión Recibida Total
6. Comisión Recibida
7. Comision Pagada Externos
8. **Comisión Neta** (subtotal)
9. **Subtotal Margen Después de Costos Directos** (subtotal)
10. **Subtotal (margen − gastos comerciales)** (subtotal)
11. Salarios equipo comercial y operativo
12. **Sub Total (margen − salarios operativos)** (subtotal)
13. Salarios equipo administrativo
14. **Subtotal (margen − salarios infra)** (subtotal)
15. **Margen Neto** (subtotal final)

Los subtotales se pintan con fondo morado en la UI.

## Prerrequisitos
- `uv` instalado
- `gcloud auth application-default login` ya hecho
- Python 3.12

## Comandos
```bash
make install   # dependencias
make raw       # descarga raw parquet
make refresh   # arma site/data/kpi_pnl.json
make serve     # local en 8004
```

## Salarios manuales (opcional)
Por default, las líneas de salarios (11, 13) se leen directo de `pl_habicredit_colombia`. Si Kamila quiere override manual, puede crear `data/salarios_manual.csv` con columnas:

```csv
mes,salarios_comercial,salarios_admin
2026-03,5712605373,769825452
2026-04,4662249398,664849254
```

Si el archivo existe, sobreescribe los valores de la tabla en el refresh.

## Deploy
Push a `main` dispara `.github/workflows/pages.yml` que publica el contenido de `site/` en GitHub Pages.
