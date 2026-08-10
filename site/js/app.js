// habicredit-co-pnl-dash — frontend.
// Vanilla JS, sin frameworks. Kamila mantiene sola.
//
// SALARIOS OVERRIDE:
//   Si Kamila necesita reemplazar los salarios de la tabla, crea el archivo
//   data/salarios_manual.csv en el repo (NO en site/data — el CSV lo lee el
//   refresh_data.py en Python) con columnas:
//       mes,salarios_comercial,salarios_admin
//       2026-03,5712605373,769825452
//   Y corre `make refresh` de nuevo. El JS no toca ese archivo; solo lee el
//   JSON ya recalculado.

const PASSWORD = 'p&L_HbC*C0l*C12d4d';
const STORAGE_KEY = 'habicredit-co-pnl-auth';

const state = {
  data: null,          // kpi_pnl.json
  rango: 'all',        // '6' | 'all'
};

// keys de subtotales (fila morada) — deben coincidir con estructura del JSON
const SUBTOTAL_KEYS = new Set([
  'comision_neta',
  'subtotal_post_directos',
  'subtotal_post_com',
  'subtotal_post_sal_op',
  'subtotal_post_sal_infra',
  'margen_neto',
]);

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
    `${m.consolidado || 'HabiCredit CO'}`;
  document.getElementById('rangoFechas').textContent =
    `${m.rango_meses.min} → ${m.rango_meses.max}`;
  const dt = new Date(m.generado_en);
  document.getElementById('refreshAt').textContent =
    dt.toLocaleString('es-CO', { dateStyle: 'medium', timeStyle: 'short' });

  // Flag si hay override manual de salarios
  document.getElementById('salariosFlag').hidden = !m.salarios_override_activo;
}

// ─── controls ───────────────────────────────────────────────────────
function setupControls() {
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

// Determina cuál mes es "MTD" (el mes calendario en curso HOY).
function currentMesMTD() {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  return `${y}-${m}`;
}

function fmtMoney(v) {
  if (v === null || v === undefined || !isFinite(v)) return '—';
  const inMM = v / 1_000_000;
  return inMM.toLocaleString('es-CO', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

function fmtCount(v) {
  if (v === null || v === undefined || !isFinite(v)) return '—';
  return Math.round(v).toLocaleString('es-CO');
}

function fmtRatio(v) {
  // Ticket promedio en COP MM (no en cientos de millones)
  return fmtMoney(v);
}

function fmtCell(v, sign) {
  if (sign === 'count') return fmtCount(v);
  if (sign === 'ratio') return fmtRatio(v);
  return fmtMoney(v);
}

function renderTable() {
  const meses = mesesToShow();
  const mtd = currentMesMTD();

  const head = document.getElementById('pnlHead');
  head.innerHTML = '';
  const firstTh = document.createElement('th');
  firstTh.textContent = 'P&L HabiCredit CO (COP MM)';
  head.appendChild(firstTh);
  for (const m of meses) {
    const th = document.createElement('th');
    th.textContent = m;
    if (m === mtd) th.classList.add('mtd');
    head.appendChild(th);
  }

  const body = document.getElementById('pnlBody');
  body.innerHTML = '';

  for (const line of state.data.estructura) {
    const tr = document.createElement('tr');
    if (line.type === 'subtotal') tr.classList.add('subtotal');
    if (line.key === 'margen_neto') tr.classList.add('margen-neto');

    const tdLabel = document.createElement('td');
    tdLabel.textContent = `${line.n}. ${line.label}`;
    tr.appendChild(tdLabel);

    for (const m of meses) {
      const monthVals = state.data.valores[m] || {};
      const v = monthVals[line.key];
      const td = document.createElement('td');
      if (v === null || v === undefined) {
        td.textContent = '—';
        td.classList.add('placeholder');
      } else {
        td.textContent = fmtCell(v, line.sign);
      }
      tr.appendChild(td);
    }
    body.appendChild(tr);
  }
}

// ─── init ───────────────────────────────────────────────────────────
async function init() {
  await loadData();
  renderHeader();
  setupControls();
  renderTable();
}

if (setupLogin()) {
  init();
}
