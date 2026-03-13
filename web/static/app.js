/* AI Engineering Platform — Frontend v2 */
'use strict';

// ─── State ───────────────────────────────────────────────────
let ws = null;
let running = false;
let startTime = null;
let elapsedInterval = null;
let activeProject = document.getElementById('project-select')?.value || '';

// Phase map: server key → DOM id suffix
const PHASE_MAP = {
  setup: 'setup', analyze: 'analyze', propose: 'propose',
  await_decision: 'propose', design: 'design', implement: 'implement',
  pipeline: 'pipeline', fix: 'pipeline', commit: 'commit',
  pr: 'pr', deploy: 'deploy', done: 'done', error: 'done',
};

// ─── Init ────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('feature-input');
  if (input) {
    input.addEventListener('input', () => {
      const cc = document.getElementById('char-count');
      if (cc) cc.textContent = input.value.length;
    });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submitFeature();
    });
  }

  loadProjectData(activeProject);
  loadCosts();

  // Refresh costs every 30s
  setInterval(loadCosts, 30000);
});

// ─── Project selection ───────────────────────────────────────
function onProjectChange(projectId) {
  activeProject = projectId;
  const label = document.getElementById('active-project-label');
  if (label) label.textContent = projectId;
  loadProjectData(projectId);
}

async function loadProjectData(projectId) {
  if (!projectId) return;
  try {
    const resp = await fetch(`/api/project/${projectId}`);
    if (!resp.ok) return;
    const data = await resp.json();
    renderMemory(data.memory || {});
    renderChecklist(data.checklist || []);
    renderLastSession(data.memory?.last_session);
  } catch (e) {
    console.error('loadProjectData:', e);
  }
}

function renderMemory(memory) {
  const box = document.getElementById('project-memory');
  if (!box) return;

  const arch = memory.architecture || '';
  const decisions = memory.tech_decisions || [];
  const debt = memory.tech_debt || [];

  let html = '';
  if (arch) {
    html += `<div class="memory-item"><strong>Arquitectura:</strong><br>${esc(arch.substring(0, 120))}${arch.length > 120 ? '...' : ''}</div>`;
  }
  if (decisions.length) {
    html += `<div class="memory-item"><strong>Decisiones:</strong><br>`;
    decisions.slice(0, 3).forEach(d => {
      html += `<span class="memory-tag">${esc(d.substring(0, 60))}</span>`;
    });
    html += '</div>';
  }
  if (debt.length) {
    html += `<div class="memory-item"><strong>Deuda técnica:</strong><br>`;
    debt.slice(0, 2).forEach(d => {
      html += `<span class="memory-tag" style="border-color:var(--yellow)">${esc(d.substring(0, 60))}</span>`;
    });
    html += '</div>';
  }
  box.innerHTML = html || '<div class="memory-placeholder">Sin memoria registrada.</div>';
}

function renderChecklist(checklist) {
  const box = document.getElementById('checklist');
  if (!box) return;
  if (!checklist.length) {
    box.innerHTML = '<div class="checklist-placeholder">Sin tareas.</div>';
    return;
  }
  box.innerHTML = checklist.map(item => {
    const done = item.status === 'done' || item.status === 'completed';
    return `<div class="checklist-item">
      <span class="check-icon ${done ? 'done' : 'pending'}">${done ? '✓' : '○'}</span>
      <span class="check-text ${done ? 'done' : ''}">${esc(item.task)}</span>
    </div>`;
  }).join('');
}

function renderLastSession(ls) {
  const box = document.getElementById('last-session');
  if (!box) return;
  if (!ls) {
    box.innerHTML = '<div class="last-session-placeholder">Sin sesiones previas.</div>';
    return;
  }
  box.innerHTML = `
    <div class="ls-row"><span>Fecha</span><span class="ls-val">${esc((ls.date||'').substring(0,10))}</span></div>
    <div class="ls-row"><span>Feature</span><span class="ls-val" title="${esc(ls.feature||'')}">${esc((ls.feature||'').substring(0,30))}</span></div>
    <div class="ls-row"><span>Commit</span><span class="ls-val">${esc(ls.commit||'N/A')}</span></div>
    ${ls.pr ? `<div class="ls-row"><span>PR</span><span class="ls-val"><a class="msg-link" href="${esc(ls.pr)}" target="_blank">#${esc(ls.pr.split('/').pop())}</a></span></div>` : ''}
  `;
}

async function loadCosts() {
  try {
    const resp = await fetch('/api/costs');
    if (!resp.ok) return;
    const data = await resp.json();
    renderCosts(data);
  } catch (e) {}
}

function renderCosts(data) {
  const box = document.getElementById('cost-summary');
  if (!box) return;
  const total = data.total_usd || 0;
  const byModel = data.by_model || {};
  let html = `<div class="cost-total">$${total.toFixed(4)}</div>`;
  Object.entries(byModel).sort((a,b) => b[1]-a[1]).slice(0, 5).forEach(([model, cost]) => {
    html += `<div class="cost-row"><span class="cost-model">${esc(model)}</span><span class="cost-val">$${cost.toFixed(4)}</span></div>`;
  });
  box.innerHTML = html;
}

// ─── Submit feature request ──────────────────────────────────
function submitFeature() {
  const input = document.getElementById('feature-input');
  if (!input) return;
  const text = input.value.trim();
  if (!text || running) return;

  const projectId = document.getElementById('project-select')?.value || activeProject;
  if (!projectId) {
    addMessage('error', 'Selecciona un proyecto primero.');
    return;
  }

  openWS(text, projectId);
  input.value = '';
  const cc = document.getElementById('char-count');
  if (cc) cc.textContent = '0';
}

function openWS(featureRequest, projectId) {
  if (ws) { ws.close(); ws = null; }

  setRunning(true);
  resetPhases();
  addMessage('feature', `Instrucción: ${featureRequest}`);

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/ws/agent`);

  ws.onopen = () => {
    const payload = {
      feature_request: featureRequest,
      project: projectId,
      chosen_proposal: 'a',
    };
    ws.send(JSON.stringify(payload));
  };

  ws.onmessage = (event) => {
    try {
      handleWsMessage(JSON.parse(event.data));
    } catch (e) {
      console.error('WS message parse error:', e);
    }
  };

  ws.onclose = () => {
    setRunning(false);
  };

  ws.onerror = (e) => {
    addMessage('error', 'Error de conexión con el agente.');
    setRunning(false);
  };
}

// ─── WS message handler ──────────────────────────────────────
function handleWsMessage(msg) {
  const type = msg.type;

  if (type === 'phase') {
    markPhase(msg.phase, msg.label);
  }
  else if (type === 'log') {
    appendLog(msg.level, msg.msg);
  }
  else if (type === 'analysis') {
    addMessage('analysis', msg.content, 'Análisis del codebase');
  }
  else if (type === 'proposal') {
    renderProposal(msg.content, msg.proposal_b);
  }
  else if (type === 'design') {
    addMessage('system', msg.content, 'Plan técnico');
  }
  else if (type === 'implementation') {
    addMessage('system', msg.content, 'Implementación');
  }
  else if (type === 'tests') {
    const cls = msg.passed ? 'result' : 'error';
    addMessage(cls, msg.content, `Pipeline: ${msg.passed ? 'PASS' : 'FAIL'}`);
  }
  else if (type === 'pr') {
    const link = msg.content ? `<a class="msg-link" href="${esc(msg.content)}" target="_blank">${esc(msg.content)}</a>` : '—';
    addMessageHTML('result', `<div class="msg-label">Pull Request creado</div>${link}`);
  }
  else if (type === 'done') {
    addMessage('result', msg.summary || msg.content, 'Completado');
    markPhase('done', 'Completado');
    setBadge('done', 'Listo');
    setRunning(false);
    loadProjectData(activeProject);
    loadCosts();
  }
  else if (type === 'error') {
    addMessage('error', msg.message, 'Error');
    markPhaseError();
    setBadge('error', 'Error');
    setRunning(false);
  }
  else if (type === 'finished') {
    setRunning(false);
  }
}

// ─── Phase tracking ──────────────────────────────────────────
let currentPhase = null;

function resetPhases() {
  currentPhase = null;
  document.querySelectorAll('.phase-item').forEach(el => {
    el.classList.remove('active', 'done', 'error');
    const time = el.querySelector('.ph-time');
    if (time) time.textContent = '';
  });
  document.getElementById('session-badge').textContent = '';
}

function markPhase(phase, label) {
  const key = PHASE_MAP[phase] || phase;
  const el = document.getElementById(`ph-${key}`);
  if (!el) return;

  // Mark previous phase as done
  if (currentPhase && currentPhase !== key) {
    const prev = document.getElementById(`ph-${currentPhase}`);
    if (prev) {
      prev.classList.remove('active');
      prev.classList.add('done');
      const pt = prev.querySelector('.ph-time');
      if (pt) pt.textContent = formatElapsed();
    }
  }

  currentPhase = key;
  el.classList.remove('done', 'error');
  el.classList.add('active');

  // Update session badge
  const sb = document.getElementById('session-badge');
  if (sb && label) sb.textContent = label;
}

function markPhaseError() {
  if (currentPhase) {
    const el = document.getElementById(`ph-${currentPhase}`);
    if (el) {
      el.classList.remove('active', 'done');
      el.classList.add('error');
    }
  }
}

// ─── Chat messages ───────────────────────────────────────────
function addMessage(cls, content, label) {
  const box = document.getElementById('chat-messages');
  if (!box) return;
  const div = document.createElement('div');
  div.className = `chat-msg ${cls}`;
  let html = '';
  if (label) html += `<div class="msg-label">${esc(label)}</div>`;
  html += `<div class="msg-content">${esc(content)}</div>`;
  div.innerHTML = html;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function addMessageHTML(cls, html) {
  const box = document.getElementById('chat-messages');
  if (!box) return;
  const div = document.createElement('div');
  div.className = `chat-msg ${cls}`;
  div.innerHTML = html;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function renderProposal(optionA, optionB) {
  const box = document.getElementById('chat-messages');
  if (!box) return;
  const div = document.createElement('div');
  div.className = 'chat-msg proposal';
  div.innerHTML = `
    <div class="msg-label">Propuestas técnicas — elige una</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:10px;">
      <div style="background:var(--bg-3);border-radius:4px;padding:8px;font-size:11px;line-height:1.5;">${esc(optionA.substring(0,400))}</div>
      <div style="background:var(--bg-3);border-radius:4px;padding:8px;font-size:11px;line-height:1.5;">${esc(optionB.substring(0,400))}</div>
    </div>
    <div class="proposal-options">
      <button class="btn-option" onclick="chooseProposal('a', this)">Opción A</button>
      <button class="btn-option" onclick="chooseProposal('b', this)">Opción B</button>
    </div>
  `;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function chooseProposal(choice, btn) {
  btn.parentElement.querySelectorAll('.btn-option').forEach(b => b.classList.remove('chosen'));
  btn.classList.add('chosen');
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'proposal_choice', choice }));
  }
}

// ─── Log panel ───────────────────────────────────────────────
function appendLog(level, msg) {
  const body = document.getElementById('log-body');
  if (!body) return;

  // Remove placeholder
  const placeholder = body.querySelector('.log-placeholder');
  if (placeholder) placeholder.remove();

  const line = document.createElement('div');
  const cls = ['INFO','WARNING','ERROR'].includes(level) ? level : 'default';
  line.className = `log-line ${cls}`;
  line.textContent = msg;
  body.appendChild(line);

  // Keep max 300 lines
  while (body.children.length > 300) body.removeChild(body.firstChild);
  body.scrollTop = body.scrollHeight;
}

function clearLog() {
  const body = document.getElementById('log-body');
  if (body) body.innerHTML = '<div class="log-placeholder">Log limpiado.</div>';
}

function toggleLog() {
  const panel = document.getElementById('log-panel');
  const btn   = document.getElementById('log-toggle');
  if (!panel) return;
  const collapsed = panel.classList.toggle('collapsed');
  if (btn) btn.textContent = collapsed ? 'Expandir' : 'Colapsar';
}

// ─── UI helpers ──────────────────────────────────────────────
function setRunning(val) {
  running = val;
  const btn = document.getElementById('submit-btn');
  if (btn) btn.disabled = val;

  if (val) {
    startTime = Date.now();
    setBadge('running', 'Ejecutando...');
    elapsedInterval = setInterval(updateElapsed, 1000);
  } else {
    if (elapsedInterval) { clearInterval(elapsedInterval); elapsedInterval = null; }
    const eb = document.getElementById('elapsed-badge');
    if (eb) eb.style.display = 'none';
  }
}

function setBadge(cls, text) {
  const badge = document.getElementById('status-badge');
  if (!badge) return;
  badge.className = `badge ${cls}`;
  badge.textContent = text;
}

function updateElapsed() {
  if (!startTime) return;
  const secs = Math.floor((Date.now() - startTime) / 1000);
  const m = Math.floor(secs / 60).toString().padStart(2, '0');
  const s = (secs % 60).toString().padStart(2, '0');
  const eb = document.getElementById('elapsed-badge');
  if (eb) { eb.style.display = 'inline'; eb.textContent = `${m}:${s}`; }
}

function formatElapsed() {
  if (!startTime) return '';
  const secs = Math.floor((Date.now() - startTime) / 1000);
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return m > 0 ? `${m}m${s}s` : `${s}s`;
}

// ─── New Project Modal ───────────────────────────────────────
function openNewProjectModal() {
  document.getElementById('modal-overlay').style.display = 'flex';
  document.getElementById('np-name').focus();
}

function closeNewProjectModal() {
  document.getElementById('modal-overlay').style.display = 'none';
  document.getElementById('new-project-form').reset();
  document.getElementById('np-error').style.display = 'none';
}

async function submitNewProject(e) {
  e.preventDefault();
  const btn = document.getElementById('np-submit');
  const errEl = document.getElementById('np-error');
  const exclusive = document.getElementById('np-exclusive').checked;
  btn.disabled = true;
  btn.textContent = exclusive ? 'Creando servidor...' : 'Creando...';
  errEl.style.display = 'none';

  try {
    const resp = await fetch('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name:             document.getElementById('np-name').value.trim(),
        description:      document.getElementById('np-desc').value.trim(),
        repository:       document.getElementById('np-repo').value.trim(),
        exclusive_server: document.getElementById('np-exclusive').checked,
      }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      errEl.textContent = data.detail || 'Error al crear el proyecto';
      errEl.style.display = 'block';
      return;
    }
    // Agregar al select y seleccionarlo
    const sel = document.getElementById('project-select');
    // Quitar opción vacía si existe
    const empty = sel.querySelector('option[value=""]');
    if (empty) empty.remove();
    // Agregar nueva opción
    const opt = document.createElement('option');
    opt.value = data.id;
    opt.textContent = data.name;
    sel.appendChild(opt);
    sel.value = data.id;
    onProjectChange(data.id);
    closeNewProjectModal();
  } catch (err) {
    errEl.textContent = 'Error de conexión';
    errEl.style.display = 'block';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Crear proyecto';
  }
}

function esc(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ─── Greeting Section ────────────────────────────────────────────────────────

async function submitGreeting() {
  const input     = document.getElementById('greeting-name');
  const resultDiv = document.getElementById('greeting-result');

  // Guardia: elementos deben existir en el DOM
  if (!input || !resultDiv) return;

  const name = input.value.trim();

  // Validaciones cliente (espejo de las del backend)
  if (!name) {
    _renderGreetingError(resultDiv, 'El nombre no puede estar vacío.');
    return;
  }
  if (name.length > 100) {
    _renderGreetingError(resultDiv, 'Nombre demasiado largo (máx. 100 caracteres).');
    return;
  }

  // Estado de carga
  input.disabled = true;
  resultDiv.innerHTML = '<div class="result-label">Cargando…</div>';

  try {
    const resp = await fetch(`/api/greeting/${encodeURIComponent(name)}`);

    if (!resp.ok) {
      // Intentar leer el mensaje de error del backend (formato FastAPI estándar)
      let detail = `Error ${resp.status}`;
      try {
        const errBody = await resp.json();
        if (errBody?.detail) detail = errBody.detail;
      } catch (_) { /* ignorar si el body no es JSON */ }
      _renderGreetingError(resultDiv, detail);
      return;
    }

    const data      = await resp.json();
    const timestamp = data.timestamp
      ? new Date(data.timestamp).toLocaleTimeString('es-ES')
      : '';

    resultDiv.innerHTML = `
      <div class="greeting-result">
        <div class="result-label">✓ Saludo generado</div>
        <div class="result-text">${esc(data.greeting)}</div>
        ${timestamp ? `<div style="font-size:10px;color:var(--text-muted);margin-top:6px;">${timestamp}</div>` : ''}
      </div>
    `;

  } catch (e) {
    _renderGreetingError(resultDiv, 'Error de conexión. Intenta de nuevo.');
    console.error('[submitGreeting]', e);
  } finally {
    input.disabled = false;
    input.focus();
  }
}

function _renderGreetingError(resultDiv, message) {
  // Prefijo _ = función de módulo privado (convención proyecto)
  resultDiv.innerHTML = `
    <div class="greeting-result greeting-result--error">
      <div class="result-label">✗ Error</div>
      <div class="result-text">${esc(message)}</div>
    </div>
  `;
}
