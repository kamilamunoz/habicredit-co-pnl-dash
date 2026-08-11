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

const PASSWORD = 'p&L_HbC*C0l*C12d4d';
const STORAGE_KEY = 'habicredit-co-pnl-auth';

const state = {
  data: null,          // kpi_pnl.json
  rango: 'all',        // '6' | 'all'
  ciudad: 'Total',
};

// ─── login ──────────────────────────────────────────────────────────
function unlockUI() {
  document.getElementById('loginGate').style.display = 'none';
  document.querySelector('.topbar').hidden = false;
  document.getElementById('mainWrap').hidden = false;
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
      renderTable();
    });
  });
}

// ─── tabla ──────────────────────────────────────────────────────────
function mesesToShow() {
  const all = state.data.meses;
  if (state.rango === 'all') return all;
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

// Ticket Promedio: COP absoluto con separador de miles, sin decimales.
function fmtTicket(v) {
  if (v === null || v === undefined || !isFinite(v)) return '—';
  return Math.round(v).toLocaleString('es-CO');
}

// Cantidad Desembolsos: entero.
function fmtCount(v) {
  if (v === null || v === undefined || !isFinite(v)) return '—';
  return Math.round(v).toLocaleString('es-CO');
}

function fmtByKey(v, key, tipo) {
  if (tipo === 'count') return fmtCount(v);
  if (key === 'ticket_promedio') return fmtTicket(v);
  return fmtMonto(v);
}

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
        td.textContent = fmtByKey(v, line.key, line.tipo);
      }
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
  setupControls();
  renderTable();
}

if (setupLogin()) {
  init();
}
