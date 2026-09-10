# habicredit-co-pnl-dash

Dashboard live del **P&L HabiCredit CO por ciudad**.

Réplica en la línea de `co-city-pnl-dash`. Sitio estático (HTML + CSS + vanilla JS) publicado en GitHub Pages, con refresh manual de datos contra BigQuery.

## URLs
- **Live**: https://kamilamunoz.github.io/habicredit-co-pnl-dash/
- **Local**: http://localhost:8004/site/

## Password
Password del gate del login: `reporte_fincorp_1` (definida en `site/js/app.js`, constante `PASSWORD`).

## Fuente de datos

Query oficial de Pau que arma el P&L HabiCredit CO por ciudad. Es un query **cross-project** que combina tablas de `papyrus-master` (Liquidez) y `papyrus-delivery-data` (HabiCredit + Corp Gov):

- `papyrus-master.liquidez_platinum_co.dim_brokers` — dimensiones + ciudad de cada broker (para atribución de comisiones a ciudad)
- `papyrus-master.liquidez_gold_co.mart_habicredit` — desembolsos reales (fecha, banco, monto)
- `papyrus-delivery-data.habicredit.main_board` — reporte HabiCredit (para conteo por broker)
- `papyrus-delivery-data.habicredit.pipe_pago_comisiones_hc` — pagos de comisiones a brokers externos
- `papyrus-delivery-data.habicredit.cs_comisiones_internas_hc_finanzas` — **tabla espejo** de la sheet de pagos internos
- `papyrus-delivery-data.corp_gov_global.cs_tarifa_comisiones_habicredit` — **tabla espejo** de la sheet de tarifas por banco

Las 2 tablas con prefijo `cs_` son **materializaciones nativas** de las sheets `tarifa_comisiones_habicredit` y `comisiones_internas_hc_finanzas`. Se usan porque el ADC de Python no tiene scope de Drive; Kamila mantiene las espejo sincronizadas.

Billing project: `papyrus-delivery-data`.

Fecha canónica: `fecha_desembolso` (nivel mes con `DATE_TRUNC(..., MONTH)`).

## Estructura de la salida

Cobertura: **8 filas × N meses × N ciudades** (Total + reales).

Filas:
1. Cantidad Desembolsos (entero)
2. Valor Desembolsado (COP MM)
3. Ticket Promedio (COP absolutos)
4. Comisión Recibida (COP MM)
5. Comisión Pagada Externos (COP MM)
6. Comisión Pagada Internos (COP MM)
7. **Comisión Neta = (4) − (5) − (6)** (subtotal morado)
8. **Margen Neto = Comisión Neta** (subtotal morado)

Ciudades reales detectadas al 2026-08-11: `Bogotá`, `Valle de Aburrá`, `Barranquilla`, `Cali`, `Otros`. `Bogotá D.C.` del CTE `ciudad_broker` se normaliza a `Bogotá` en el refresh. Valores basura `'1'/'2'/'3'` del campo `ciudad` de `dim_brokers` se descartan.

La fila **Total** se calcula sumando las ciudades reales. **Ticket Promedio del Total se RECALCULA** como `valor_desembolsado_total / cant_desembolsos_total` (no es el promedio de los tickets por ciudad).

El mes en curso trae el sufijo **· MTD** en el header de columna.

## Prerrequisitos
- `uv` instalado
- `gcloud auth application-default login` ya hecho
- Python 3.12

## Comandos
```bash
make install   # dependencias
make raw       # descarga raw parquet (query BQ, ~0.06 GB facturados)
make refresh   # arma site/data/kpi_pnl.json
make serve     # local en http://localhost:8004/site/
```

Opcional: exportar `MES_CUTOFF=YYYY-MM` antes de `make refresh` para excluir meses posteriores al cutoff.

## Deploy
Push a `main` dispara `.github/workflows/pages.yml` que publica el contenido de `site/` en GitHub Pages.
