// habicredit-co-pnl-dash — frontend.
// Vanilla JS, sin frameworks. Kamila mantiene sola.
//
// Estructura del JSON `data/kpi_pnl.json`:
//   {
//     meta: { generated_at, mtd_month, rango_meses, currency, fuente, ... },
//     ciudades: ['Total', 'Bogotá', 'Valle de Aburrá', ...],
//     kpis: [ {key, label, tipo, subtotal}, ... ]   // 8 líneas
//     meses: ['YYYY-MM', ...],
//     data: { <ciudad>: { <mes>: { <kpi_key>: valor|null, ... } } }
//   }
//
// tipo:
//   'count' → entero (# desembolsos)
//   'monto' → COP absoluto. El frontend divide por 1e6 (COP MM) salvo
//             ticket_promedio, que se muestra en COP absolutos con separador
//             de miles y sin decimales.

const PASSWORD = 'p+L_HbC*C0l*C12d4d';
const STORAGE_KEY = 'habicredit-co-pnl-auth';

const state = {
  data: null,          // kpi_pnl.json
  tab: 'pnl',          // 'pnl' | 'comparativa'
  rango: '12',         // '6' | '12' | 'all' | 'year' | 'range'
  year: null,          // int como string 'YYYY' (cuando rango === 'year')
  rangeFrom: null,     // 'YYYY-MM' (cuando rango === 'range')
  rangeTo: null,       // 'YYYY-MM' (cuando rango === 'range')
  ciudad: 'Total',
  // tab comparativa
  cmpPeriodo: '6m',    // '3m' | '6m' | '12m' | 'ytd'
  cmpRegiones: null,   // Set<string> — regiones seleccionadas
  cmpMetrica: 'abs',   // 'abs' | 'pct' | 'per_nid'
};

// ─── login ──────────────────────────────────────────────────────────
function unlockUI() {
  document.getElementById('loginGate').style.display = 'none';
  document.querySelector('.topbar').hidden = false;
  document.getElementById('tabsNav').hidden = false;
  document.getElementById('tab-pnl').hidden = false;
}

function setupLogin() {
  const form = document.getElementById('loginForm');
  const err = document.getElementById('loginError');
  if (sessionStorage.getItem(STORAGE_KEY) === 'ok') {
    unlockUI();
    return true;
  }
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const pwd = document.getElementById('loginPwd').value;
    if (pwd === PASSWORD) {
      sessionStorage.setItem(STORAGE_KEY, 'ok');
      unlockUI();
      init();
    } else {
      err.hidden = false;
    }
  });
  return false;
}

// ─── data load ──────────────────────────────────────────────────────
async function loadData() {
  const r = await fetch(`data/kpi_pnl.json?v=${Date.now()}`);
  state.data = await r.json();
}

// ─── header ─────────────────────────────────────────────────────────
function renderHeader() {
  const m = state.data.meta;
  document.getElementById('contextLabel').textContent =
    'HabiCredit CO · P&L por ciudad';
  document.getElementById('rangoFechas').textContent =
    `${m.rango_meses.min} → ${m.rango_meses.max}`;
  const dt = new Date(m.generated_at);
  document.getElementById('refreshAt').textContent =
    dt.toLocaleString('es-CO', { dateStyle: 'medium', timeStyle: 'short' });
}

function renderCiudadLabel() {
  document.getElementById('ciudadLabel').textContent = state.ciudad;
}

// ─── controls ───────────────────────────────────────────────────────
function setupControls() {
  // Dropdown ciudades
  const sel = document.getElementById('ciudadSelector');
  sel.innerHTML = '';
  for (const c of state.data.ciudades) {
    const opt = document.createElement('option');
    opt.value = c;
    opt.textContent = c;
    sel.appendChild(opt);
  }
  sel.value = state.ciudad;
  sel.addEventListener('change', () => {
    state.ciudad = sel.value;
    renderCiudadLabel();
    renderTable();
  });

  document.querySelectorAll('#rangoCtrl .seg-btn').forEach(b => {
    b.addEventListener('click', () => {
      state.rango = b.dataset.rango;
      document.querySelectorAll('#rangoCtrl .seg-btn').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      document.getElementById('yearSubCtrl').hidden = state.rango !== 'year';
      document.getElementById('rangeSubCtrl').hidden = state.rango !== 'range';
      renderTable();
    });
  });

  // sub-control: año — botones dinámicos según años presentes en el JSON
  const yearCtrl = document.getElementById('yearCtrl');
  const years = Array.from(new Set(state.data.meses.map(m => m.slice(0, 4)))).sort();
  state.year = state.year || years[years.length - 1];
  yearCtrl.innerHTML = '';
  for (const y of years) {
    const b = document.createElement('button');
    b.className = 'seg-btn' + (y === state.year ? ' active' : '');
    b.dataset.year = y;
    b.textContent = y;
    b.addEventListener('click', () => {
      state.year = y;
      yearCtrl.querySelectorAll('.seg-btn').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      renderTable();
    });
    yearCtrl.appendChild(b);
  }

  // sub-control: rango de fechas — selects de mes-año
  const fromSel = document.getElementById('rangeFrom');
  const toSel = document.getElementById('rangeTo');
  const opts = state.data.meses.map(m => `<option value="${m}">${m}</option>`).join('');
  fromSel.innerHTML = opts;
  toSel.innerHTML = opts;
  state.rangeFrom = state.rangeFrom || state.data.meses[0];
  state.rangeTo = state.rangeTo || state.data.meses[state.data.meses.length - 1];
  fromSel.value = state.rangeFrom;
  toSel.value = state.rangeTo;
  fromSel.addEventListener('change', () => {
    state.rangeFrom = fromSel.value;
    if (state.rangeFrom > state.rangeTo) {
      state.rangeTo = state.rangeFrom;
      toSel.value = state.rangeTo;
    }
    renderTable();
  });
  toSel.addEventListener('change', () => {
    state.rangeTo = toSel.value;
    if (state.rangeTo < state.rangeFrom) {
      state.rangeFrom = state.rangeTo;
      fromSel.value = state.rangeFrom;
    }
    renderTable();
  });
}

// ─── tabla ──────────────────────────────────────────────────────────
function mesesToShow() {
  const all = state.data.meses;
  if (state.rango === 'all') return all;
  if (state.rango === 'year') {
    return all.filter(m => m.startsWith(state.year + '-'));
  }
  if (state.rango === 'range') {
    return all.filter(m => m >= state.rangeFrom && m <= state.rangeTo);
  }
  const n = parseInt(state.rango, 10);
  return all.slice(-n);
}

// MTD = mes más reciente en el JSON (viene del backend en meta.mtd_month).
// Si por alguna razón no está, cae al último de la lista.
function currentMesMTD() {
  return state.data.meta.mtd_month || state.data.meses[state.data.meses.length - 1];
}

// Formato en millones de COP (2 decimales, separador de miles es-CO).
function fmtMonto(v) {
  if (v === null || v === undefined || !isFinite(v)) return '—';
  const inMM = v / 1_000_000;
  return inMM.toLocaleString('es-CO', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Cantidad Desembolsos: entero.
function fmtCount(v) {
  if (v === null || v === undefined || !isFinite(v)) return '—';
  return Math.round(v).toLocaleString('es-CO');
}

// % del ingreso — decimales para tabular en la celda debajo del monto.
function fmtPct(v) {
  if (v === null || v === undefined || !isFinite(v)) return '';
  return (v * 100).toLocaleString('es-CO', { minimumFractionDigits: 1, maximumFractionDigits: 1 }) + '%';
}

function fmtByKey(v, key, tipo) {
  if (tipo === 'count') return fmtCount(v);
  // Ticket Promedio también va en MM COP (misma escala que los demás montos).
  return fmtMonto(v);
}

// KPIs que llevan % vs Comisión Recibida (denominador). Los demás no.
const PCT_KEYS = new Set([
  'comision_externos',
  'comision_internos',
  'margen_neto',
]);

// KPIs que se RESTAN de la Recibida — se muestran con signo negativo y color rojo
// para que visualmente sea claro que son gastos que reducen el margen.
const NEG_KEYS = new Set([
  'comision_externos',
  'comision_internos',
]);

function renderTable() {
  const meses = mesesToShow();
  const mtd = currentMesMTD();
  const ciudad = state.ciudad;
  const dataCiudad = state.data.data[ciudad] || {};

  const head = document.getElementById('pnlHead');
  head.innerHTML = '';
  const firstTh = document.createElement('th');
  firstTh.textContent = `P&L HabiCredit CO · ${ciudad}`;
  head.appendChild(firstTh);
  for (const m of meses) {
    const th = document.createElement('th');
    th.textContent = m;
    if (m === mtd) th.classList.add('mtd');
    head.appendChild(th);
  }

  const body = document.getElementById('pnlBody');
  body.innerHTML = '';

  for (const line of state.data.kpis) {
    const tr = document.createElement('tr');
    if (line.subtotal) tr.classList.add('subtotal');
    if (line.key === 'margen_neto') tr.classList.add('margen-neto');

    const tdLabel = document.createElement('td');
    tdLabel.textContent = line.label;
    tr.appendChild(tdLabel);

    for (const m of meses) {
      const kv = dataCiudad[m] || {};
      const v = kv[line.key];
      const td = document.createElement('td');
      if (v === null || v === undefined) {
        td.textContent = '—';
        td.classList.add('placeholder');
      } else {
        const isNeg = NEG_KEYS.has(line.key);
        const displayVal = isNeg ? -Math.abs(v) : v;
        const main = fmtByKey(displayVal, line.key, line.tipo);
        if (isNeg) td.classList.add('neg');
        if (PCT_KEYS.has(line.key)) {
          const rec = kv['comision_recibida'];
          if (rec && rec !== 0) {
            const pctVal = isNeg ? -Math.abs(v / rec) : (v / rec);
            td.innerHTML = `${main}<br><span class="pct">${fmtPct(pctVal)}</span>`;
          } else {
            td.textContent = main;
          }
        } else {
          td.textContent = main;
        }
      }
      tr.appendChild(td);
    }
    body.appendChild(tr);
  }
}

// ─── tabs ───────────────────────────────────────────────────────────
function setupTabs() {
  document.querySelectorAll('#tabsNav .tab-btn').forEach(b => {
    b.addEventListener('click', () => {
      state.tab = b.dataset.tab;
      document.querySelectorAll('#tabsNav .tab-btn').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      document.getElementById('tab-pnl').hidden = state.tab !== 'pnl';
      document.getElementById('tab-comparativa').hidden = state.tab !== 'comparativa';
      if (state.tab === 'comparativa') renderCompareTable();
    });
  });
}

// ─── tab comparativa ────────────────────────────────────────────────
function ciudadesReales() {
  return (state.data.ciudades || []).filter(c => c !== 'Total');
}

function setupCompareControls() {
  // Regiones — botones tipo chip, click toggle
  const regs = ciudadesReales();
  state.cmpRegiones = state.cmpRegiones || new Set(regs);
  const regCtrl = document.getElementById('cmpRegionCtrl');
  regCtrl.innerHTML = '';
  for (const r of regs) {
    const b = document.createElement('button');
    b.className = 'seg-btn' + (state.cmpRegiones.has(r) ? ' active' : '');
    b.dataset.region = r;
    b.textContent = r;
    b.addEventListener('click', () => {
      if (state.cmpRegiones.has(r)) state.cmpRegiones.delete(r);
      else state.cmpRegiones.add(r);
      b.classList.toggle('active');
      renderCompareTable();
    });
    regCtrl.appendChild(b);
  }

  // Período
  document.querySelectorAll('#cmpPeriodoCtrl .seg-btn').forEach(b => {
    b.addEventListener('click', () => {
      state.cmpPeriodo = b.dataset.periodo;
      document.querySelectorAll('#cmpPeriodoCtrl .seg-btn').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      renderCompareTable();
    });
  });

  // Métrica
  document.querySelectorAll('#cmpMetricaCtrl .seg-btn').forEach(b => {
    b.addEventListener('click', () => {
      state.cmpMetrica = b.dataset.metrica;
      document.querySelectorAll('#cmpMetricaCtrl .seg-btn').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      renderCompareTable();
    });
  });
}

function mesesForCmp() {
  // Excluye siempre el MTD (mes en curso) porque tiene comisiones NULL.
  const mtd = state.data.meta.mtd_month;
  const cerrados = state.data.meses.filter(m => m !== mtd);
  if (state.cmpPeriodo === 'ytd') {
    const currentYear = (mtd || cerrados[cerrados.length - 1]).slice(0, 4);
    return cerrados.filter(m => m.startsWith(currentYear + '-'));
  }
  const n = parseInt(state.cmpPeriodo, 10); // '3m'→3, '6m'→6, '12m'→12
  return cerrados.slice(-n);
}

function aggregatePeriodo(ciudad, meses) {
  // Suma KPIs sobre los meses; recalcula ticket + margen + %.
  const kv = { cant_desembolsos: 0, valor_desembolsado: 0, comision_recibida: 0,
               comision_externos: 0, comision_internos: 0 };
  let counted = 0;
  for (const m of meses) {
    const kvMes = state.data.data[ciudad]?.[m];
    if (!kvMes) continue;
    let any = false;
    for (const k of Object.keys(kv)) {
      const v = kvMes[k];
      if (v !== null && v !== undefined) { kv[k] += v; any = true; }
    }
    if (any) counted += 1;
  }
  if (!counted) return null;
  kv.ticket_promedio = kv.cant_desembolsos > 0 ? kv.valor_desembolsado / kv.cant_desembolsos : null;
  kv.margen_neto = kv.comision_recibida - kv.comision_externos - kv.comision_internos;
  return kv;
}

function renderCompareTable() {
  const meses = mesesForCmp();
  const regiones = ciudadesReales().filter(r => state.cmpRegiones.has(r));
  const columns = ['Total', ...regiones];

  // Contexto
  const ctx = document.getElementById('cmpContext');
  if (meses.length === 0) {
    ctx.innerHTML = '<b>Período:</b> sin meses cerrados disponibles.';
  } else {
    const periodoLbl = state.cmpPeriodo === 'ytd'
      ? `YTD (${meses[0]} → ${meses[meses.length - 1]})`
      : `${meses.length} meses (${meses[0]} → ${meses[meses.length - 1]})`;
    ctx.innerHTML = `<b>Período:</b> ${periodoLbl} · <b>Regiones seleccionadas:</b> ${regiones.length || 0} · <b>Métrica:</b> ${
      { abs: 'Absoluto (COP MM)', pct: '% del Ingreso', per_nid: 'Por Desembolso (COP MM)' }[state.cmpMetrica]
    }`;
  }

  // Agregados por región
  const agg = {};
  for (const c of columns) agg[c] = aggregatePeriodo(c, meses);

  // Head
  const head = document.getElementById('cmpHead');
  head.innerHTML = '';
  const th0 = document.createElement('th');
  th0.textContent = 'KPI';
  head.appendChild(th0);
  for (const c of columns) {
    const th = document.createElement('th');
    th.textContent = c;
    head.appendChild(th);
  }

  // Body
  const body = document.getElementById('cmpBody');
  body.innerHTML = '';
  for (const line of state.data.kpis) {
    const tr = document.createElement('tr');
    if (line.subtotal) tr.classList.add('subtotal');
    if (line.key === 'margen_neto') tr.classList.add('margen-neto');

    const tdLabel = document.createElement('td');
    tdLabel.textContent = line.label;
    tr.appendChild(tdLabel);

    for (const c of columns) {
      const kv = agg[c];
      const td = document.createElement('td');
      const raw = kv ? kv[line.key] : null;
      if (raw === null || raw === undefined) {
        td.textContent = '—';
        td.classList.add('placeholder');
        tr.appendChild(td);
        continue;
      }
      // Transformar según métrica
      let v = raw;
      let render;
      const isNeg = NEG_KEYS.has(line.key);
      if (state.cmpMetrica === 'pct') {
        const denom = kv.comision_recibida;
        if (!denom) { td.textContent = '—'; td.classList.add('placeholder'); tr.appendChild(td); continue; }
        v = raw / denom;
        const disp = isNeg ? -Math.abs(v) : v;
        render = fmtPct(disp);
      } else if (state.cmpMetrica === 'per_nid') {
        const nid = kv.cant_desembolsos;
        if (!nid) { td.textContent = '—'; td.classList.add('placeholder'); tr.appendChild(td); continue; }
        // Solo aplica a montos, no a Cant/Ticket
        if (line.key === 'cant_desembolsos') {
          render = fmtCount(v);
        } else if (line.key === 'ticket_promedio') {
          render = fmtMonto(v);
        } else {
          const per = raw / nid;
          const disp = isNeg ? -Math.abs(per) : per;
          render = fmtMonto(disp);
        }
      } else {
        // Absoluto
        if (line.tipo === 'count') {
          render = fmtCount(v);
        } else {
          const disp = isNeg ? -Math.abs(v) : v;
          render = fmtMonto(disp);
        }
      }
      if (isNeg && line.tipo !== 'count') td.classList.add('neg');
      td.textContent = render;
      tr.appendChild(td);
    }
    body.appendChild(tr);
  }
}

// ─── init ───────────────────────────────────────────────────────────
async function init() {
  await loadData();
  // Ciudad default: la primera del array (Total)
  state.ciudad = state.data.ciudades[0] || 'Total';
  renderHeader();
  renderCiudadLabel();
  setupTabs();
  setupControls();
  setupCompareControls();
  renderTable();
}

if (setupLogin()) {
  init();
}
