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

  // Restaurar proyecto activo desde localStorage
  const savedProject = localStorage.getItem('ai_active_project');
  const select = document.getElementById('project-select');
  if (savedProject && select) {
    const exists = Array.from(select.options).some(o => o.value === savedProject);
    if (exists) {
      select.value = savedProject;
      activeProject = savedProject;
    }
  }

  const label = document.getElementById('active-project-label');
  if (label && activeProject) label.textContent = activeProject;

  loadProjectData(activeProject);
  loadCosts();
  loadScrumBoard(activeProject);

  // Refresh costs every 30s
  setInterval(loadCosts, 30000);
});

// ─── Project selection ───────────────────────────────────────
function onProjectChange(projectId) {
  activeProject = projectId;
  localStorage.setItem('ai_active_project', projectId);
  const label = document.getElementById('active-project-label');
  if (label) label.textContent = projectId;
  loadProjectData(projectId);
  loadScrumBoard(projectId);
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
  else if (type === 'clarify') {
    renderClarifyPanel(msg);
  }
  else if (type === 'started') {
    const modelBadge = msg.model ? ` · ${esc(msg.model)}` : '';
    addMessage('system', `Proyecto: ${esc(msg.project)}${modelBadge}`, 'Iniciado');
  }
  else if (type === 'cancelled') {
    addMessage('system', 'Instrucción cancelada.', 'Cancelado');
    setRunning(false);
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

// ─── Clarification panel ─────────────────────────────────────
const AVAILABLE_MODELS = [
  { value: 'gpt-4o-mini',      label: 'GPT-4o mini (recomendado tareas simples)' },
  { value: 'gpt-4o',           label: 'GPT-4o (tareas complejas)' },
  { value: 'claude-haiku-4-5', label: 'Claude Haiku 4.5' },
  { value: 'claude-sonnet-4-6',label: 'Claude Sonnet 4.6 (más capaz)' },
];

function renderClarifyPanel(msg) {
  const complexity  = msg.complexity  || 'medium';
  const recModel    = msg.recommended_model || 'gpt-4o-mini';
  const questions   = msg.questions   || [];
  const understood  = msg.understood  || '';

  const complexityColor = { simple: 'var(--green)', medium: 'var(--yellow)', complex: 'var(--red)' }[complexity] || 'var(--text-muted)';

  let questionsHtml = '';
  questions.forEach((q, i) => {
    questionsHtml += `
      <div class="clarify-q">
        <label class="clarify-q-label">${esc(q)}</label>
        <input type="text" class="clarify-answer" id="cq-${i}" placeholder="Tu respuesta...">
      </div>`;
  });

  const modelOptions = AVAILABLE_MODELS.map(m =>
    `<option value="${m.value}" ${m.value === recModel ? 'selected' : ''}>${m.label}</option>`
  ).join('');

  addMessageHTML('clarify-panel', `
    <div class="clarify-box">
      <div class="clarify-header">
        <span class="clarify-title">Revisión antes de iniciar</span>
        <span class="clarify-badge" style="background:${complexityColor}20;color:${complexityColor};border-color:${complexityColor}40">${complexity}</span>
      </div>
      <div class="clarify-understood">
        <span class="clarify-label">Entendí:</span> ${esc(understood)}
      </div>
      ${questionsHtml}
      <div class="clarify-model">
        <label class="clarify-label">Modelo recomendado:</label>
        <select id="clarify-model-select" class="clarify-select">${modelOptions}</select>
      </div>
      <div class="clarify-context">
        <label class="clarify-label">Contexto adicional (opcional):</label>
        <textarea id="clarify-context-input" class="clarify-textarea" placeholder="Aclara dudas, añade restricciones..." rows="2"></textarea>
      </div>
      <div class="clarify-actions">
        <button class="btn-secondary" onclick="sendClarifyCancel()">Cancelar</button>
        <button class="btn-primary" onclick="sendClarifyConfirm()">Iniciar</button>
      </div>
    </div>
  `);
}

function sendClarifyConfirm() {
  if (!ws) return;
  const modelEl   = document.getElementById('clarify-model-select');
  const contextEl = document.getElementById('clarify-context-input');

  // Recoger respuestas a preguntas
  const answers = [];
  let i = 0;
  while (document.getElementById(`cq-${i}`)) {
    const val = document.getElementById(`cq-${i}`).value.trim();
    if (val) answers.push(val);
    i++;
  }

  let additional = (contextEl?.value || '').trim();
  if (answers.length) additional = answers.join('\n') + (additional ? '\n' + additional : '');

  ws.send(JSON.stringify({
    action:             'confirm',
    selected_model:     modelEl?.value || 'gpt-4o-mini',
    additional_context: additional,
    chosen_proposal:    'a',
  }));

  // Deshabilitar panel
  document.querySelectorAll('.clarify-actions button').forEach(b => b.disabled = true);
}

function sendClarifyCancel() {
  if (!ws) return;
  ws.send(JSON.stringify({ action: 'cancel' }));
  document.querySelectorAll('.clarify-actions button').forEach(b => b.disabled = true);
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
  const sb = document.getElementById('session-badge');
  if (sb) sb.textContent = '';
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

async function deleteActiveProject() {
  if (!activeProject) return;
  const sel = document.getElementById('project-select');
  const name = sel?.options[sel.selectedIndex]?.text || activeProject;
  if (!confirm(`¿Eliminar el proyecto "${name}"?\nSolo se elimina del registro, el repositorio local no se borra.`)) return;
  try {
    const resp = await fetch(`/api/projects/${activeProject}`, { method: 'DELETE' });
    if (!resp.ok) { alert('Error al eliminar el proyecto.'); return; }
    // Quitar del select
    const opt = sel?.querySelector(`option[value="${activeProject}"]`);
    if (opt) opt.remove();
    // Seleccionar el primero que quede
    const first = sel?.options[0];
    if (first && first.value) {
      sel.value = first.value;
      onProjectChange(first.value);
    } else {
      activeProject = '';
    }
  } catch (e) {
    alert('Error de conexión.');
  }
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

// ═══════════════════════════════════════════════════════════════
//  SCRUM BOARD
// ═══════════════════════════════════════════════════════════════

let scrumState = {
  backlog: [],
  sprint: [],
  done: [],
  currentSprint: null,
  generatedStories: [],   // stories generadas pendientes de guardar
  sprintWs: null,
  sprintRunning: false,
};

// ── Tab switching ────────────────────────────────────────────
function showTab(tab) {
  ['backlog', 'sprint', 'done'].forEach(t => {
    const content = document.getElementById(`tab-${t}`);
    const btn = document.querySelector(`.tab-btn[onclick="showTab('${t}')"]`);
    if (content) content.style.display = t === tab ? 'flex' : 'none';
    if (btn) btn.classList.toggle('active', t === tab);
  });
}

// ── Load full scrum board ────────────────────────────────────
async function loadScrumBoard(projectId) {
  if (!projectId) return;
  try {
    const [storiesResp, sprintResp] = await Promise.all([
      fetch(`/api/projects/${projectId}/stories`),
      fetch(`/api/projects/${projectId}/sprints/current`),
    ]);

    if (storiesResp.ok) {
      const data = await storiesResp.json();
      scrumState.backlog = data.backlog || [];
      scrumState.sprint  = data.sprint  || [];
      scrumState.done    = data.done    || [];
    }

    if (sprintResp.ok) {
      scrumState.currentSprint = await sprintResp.json();
    } else {
      scrumState.currentSprint = null;
    }

    renderBacklog();
    renderSprintTab();
    renderDoneTab();
  } catch (e) {
    console.error('[loadScrumBoard]', e);
  }
}

// ── Backlog rendering ────────────────────────────────────────
function renderBacklog() {
  const list = document.getElementById('backlog-list');
  if (!list) return;

  const stories = scrumState.backlog;
  const btn = document.getElementById('btn-create-sprint');

  if (!stories.length && !scrumState.generatedStories.length) {
    list.innerHTML = '<div class="story-placeholder">Sin stories en el backlog.<br>Escribe un épico y genera user stories.</div>';
    if (btn) btn.disabled = true;
    return;
  }

  let html = '';

  // Primero mostrar stories generadas pendientes (si existen)
  if (scrumState.generatedStories.length) {
    html += `<div style="font-size:10px;color:var(--accent);font-weight:600;text-transform:uppercase;letter-spacing:0.6px;margin:8px 0 6px;">Stories generadas — revisar antes de guardar</div>`;
    scrumState.generatedStories.forEach((s, i) => {
      html += renderStoryCard(s, i, true);
    });
    html += `<div style="display:flex;gap:8px;margin:8px 0 12px;">
      <button class="btn-secondary" style="flex:1;font-size:11px;" onclick="discardGenerated()">Descartar</button>
      <button class="btn-primary" style="flex:1;font-size:11px;" onclick="saveStoriesToBacklog()">Guardar en Backlog</button>
    </div>`;
  }

  if (stories.length) {
    html += `<div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:0.6px;margin:8px 0 6px;">Backlog (${stories.length})</div>`;
    stories.forEach(s => {
      html += renderStoryCard(s, null, false);
    });
  }

  list.innerHTML = html;
  if (btn) btn.disabled = stories.length === 0;
}

function renderStoryCard(story, genIdx, isGenerated) {
  const id          = story.id || `gen-${genIdx}`;
  const points      = story.story_points || 3;
  const priority    = story.priority || 'medium';
  const title       = story.title || '(sin título)';
  const question    = story.clarification_question || '';
  const statusIcon  = story.status === 'in_progress' ? '🔄 ' : '';

  const editBtn = isGenerated
    ? `<button title="Editar" onclick="editGeneratedStory(${genIdx})">&#9998;</button>`
    : `<button title="Editar" onclick="editStory('${id}')">&#9998;</button>`;
  const delBtn = isGenerated
    ? `<button class="del" title="Eliminar" onclick="removeGenerated(${genIdx})">&#215;</button>`
    : `<button class="del" title="Eliminar" onclick="deleteStory('${id}')">&#215;</button>`;

  return `<div class="story-card${isGenerated ? ' generating' : ''}" data-id="${esc(id)}">
    <div class="story-header">
      <span class="story-points">${points}pt</span>
      <span class="story-priority priority-${esc(priority)}">${esc(priority)}</span>
      <div class="story-actions">${editBtn}${delBtn}</div>
    </div>
    <div class="story-title">${statusIcon}${esc(title)}</div>
    ${question ? `<div class="story-question">? ${esc(question)}</div>` : ''}
  </div>`;
}

// ── Story generation ─────────────────────────────────────────
async function generateStories() {
  const epicInput = document.getElementById('epic-input');
  const epic = epicInput ? epicInput.value.trim() : '';
  if (!epic) { addMessage('error', 'Escribe un épico primero.', 'Error'); return; }
  if (!activeProject) { addMessage('error', 'Selecciona un proyecto.', 'Error'); return; }

  const list = document.getElementById('backlog-list');
  if (list) list.innerHTML = '<div class="story-placeholder" style="color:var(--accent);">Generando user stories...</div>';

  try {
    const resp = await fetch(`/api/projects/${activeProject}/stories/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ epic }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      addMessage('error', err.detail || 'Error generando stories', 'Error');
      renderBacklog();
      return;
    }
    const stories = await resp.json();
    scrumState.generatedStories = stories;
    renderBacklog();
    addMessage('system', `${stories.length} user stories generadas. Revísalas en el backlog.`, 'Scrum');
  } catch (e) {
    addMessage('error', 'Error de conexión al generar stories.', 'Error');
    renderBacklog();
  }
}

function discardGenerated() {
  scrumState.generatedStories = [];
  renderBacklog();
}

function removeGenerated(idx) {
  scrumState.generatedStories.splice(idx, 1);
  renderBacklog();
}

function editGeneratedStory(idx) {
  const s = scrumState.generatedStories[idx];
  if (!s) return;
  const newTitle = prompt('Título de la story:', s.title || '');
  if (newTitle !== null) {
    s.title = newTitle.trim() || s.title;
    renderBacklog();
  }
}

async function saveStoriesToBacklog() {
  if (!activeProject || !scrumState.generatedStories.length) return;
  try {
    const resp = await fetch(`/api/projects/${activeProject}/stories`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(scrumState.generatedStories),
    });
    if (!resp.ok) {
      const err = await resp.json();
      addMessage('error', err.detail || 'Error guardando stories', 'Error');
      return;
    }
    scrumState.generatedStories = [];
    const epicInput = document.getElementById('epic-input');
    if (epicInput) epicInput.value = '';
    await loadScrumBoard(activeProject);
    addMessage('system', 'Stories guardadas en el backlog.', 'Scrum');
  } catch (e) {
    addMessage('error', 'Error de conexión al guardar stories.', 'Error');
  }
}

// ── Story CRUD ───────────────────────────────────────────────
async function deleteStory(storyId) {
  if (!activeProject) return;
  if (!confirm('¿Eliminar esta story?')) return;
  try {
    const resp = await fetch(`/api/projects/${activeProject}/stories/${storyId}`, { method: 'DELETE' });
    if (!resp.ok) { addMessage('error', 'Error al eliminar story', 'Error'); return; }
    await loadScrumBoard(activeProject);
  } catch (e) {
    addMessage('error', 'Error de conexión.', 'Error');
  }
}

async function editStory(storyId) {
  const story = scrumState.backlog.find(s => s.id === storyId);
  if (!story) return;
  const newTitle = prompt('Título de la story:', story.title || '');
  if (newTitle === null) return;
  try {
    const resp = await fetch(`/api/projects/${activeProject}/stories/${storyId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: newTitle.trim() || story.title }),
    });
    if (!resp.ok) { addMessage('error', 'Error al actualizar story', 'Error'); return; }
    await loadScrumBoard(activeProject);
  } catch (e) {
    addMessage('error', 'Error de conexión.', 'Error');
  }
}

// ── Sprint Planning Modal ────────────────────────────────────
function openSprintModal() {
  const overlay = document.getElementById('sprint-modal-overlay');
  if (!overlay) return;

  // Default dates
  const today = new Date().toISOString().split('T')[0];
  const inTwoWeeks = new Date(Date.now() + 14*24*60*60*1000).toISOString().split('T')[0];
  const startEl = document.getElementById('sp-start');
  const endEl   = document.getElementById('sp-end');
  if (startEl && !startEl.value) startEl.value = today;
  if (endEl   && !endEl.value)   endEl.value   = inTwoWeeks;

  // Populate story checkboxes
  const listEl = document.getElementById('sp-story-list');
  if (listEl) {
    if (!scrumState.backlog.length) {
      listEl.innerHTML = '<div style="color:var(--text-muted);font-size:11px;font-style:italic;">Sin stories en el backlog.</div>';
    } else {
      listEl.innerHTML = scrumState.backlog.map(s => `
        <div class="story-check-item">
          <input type="checkbox" id="sp-chk-${esc(s.id)}" value="${esc(s.id)}" data-pts="${s.story_points || 0}" onchange="updateSprintPoints()">
          <label class="story-check-label" for="sp-chk-${esc(s.id)}">${esc(s.title || '(sin título)')}</label>
          <span class="story-check-pts">${s.story_points || 0}pt</span>
        </div>
      `).join('');
    }
  }
  updateSprintPoints();
  overlay.style.display = 'flex';
}

function closeSprintModal() {
  const overlay = document.getElementById('sprint-modal-overlay');
  if (overlay) overlay.style.display = 'none';
  const errEl = document.getElementById('sp-error');
  if (errEl) errEl.style.display = 'none';
}

function updateSprintPoints() {
  let total = 0;
  document.querySelectorAll('#sp-story-list input[type="checkbox"]:checked').forEach(chk => {
    total += parseInt(chk.dataset.pts || '0', 10);
  });
  const el = document.getElementById('sp-total-points');
  if (el) el.textContent = `${total} pts`;
}

async function createSprint() {
  const goal     = (document.getElementById('sp-goal')?.value || '').trim();
  const startDate = document.getElementById('sp-start')?.value || '';
  const endDate   = document.getElementById('sp-end')?.value   || '';
  const errEl     = document.getElementById('sp-error');

  const checkedStories = [];
  document.querySelectorAll('#sp-story-list input[type="checkbox"]:checked').forEach(chk => {
    checkedStories.push(chk.value);
  });

  if (!goal) { if (errEl) { errEl.textContent = 'El objetivo es requerido'; errEl.style.display = 'block'; } return; }
  if (!checkedStories.length) { if (errEl) { errEl.textContent = 'Selecciona al menos una story'; errEl.style.display = 'block'; } return; }

  const btn = document.getElementById('sp-submit');
  if (btn) btn.disabled = true;

  try {
    const resp = await fetch(`/api/projects/${activeProject}/sprints`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ goal, story_ids: checkedStories, start_date: startDate, end_date: endDate }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      if (errEl) { errEl.textContent = err.detail || 'Error al crear sprint'; errEl.style.display = 'block'; }
      return;
    }
    const sprint = await resp.json();
    closeSprintModal();
    await loadScrumBoard(activeProject);
    showTab('sprint');
    addMessage('system', `Sprint ${sprint.id} creado con ${checkedStories.length} stories.`, 'Scrum');
  } catch (e) {
    if (errEl) { errEl.textContent = 'Error de conexión'; errEl.style.display = 'block'; }
  } finally {
    if (btn) btn.disabled = false;
  }
}

// ── Sprint Tab rendering ─────────────────────────────────────
function renderSprintTab() {
  const infoEl   = document.getElementById('sprint-info');
  const listEl   = document.getElementById('sprint-story-list');
  const runBtn   = document.getElementById('btn-run-sprint');
  const sprint   = scrumState.currentSprint;

  if (!sprint) {
    if (infoEl) infoEl.style.display = 'none';
    if (listEl) listEl.innerHTML = '<div class="story-placeholder">No hay sprint activo.<br>Crea un sprint desde el Backlog.</div>';
    if (runBtn) runBtn.disabled = true;
    return;
  }

  if (infoEl) {
    infoEl.style.display = 'block';
    const goalEl  = document.getElementById('sprint-goal-text');
    const datesEl = document.getElementById('sprint-dates-text');
    const barEl   = document.getElementById('sprint-progress-bar');
    const labelEl = document.getElementById('sprint-progress-label');

    if (goalEl)  goalEl.textContent  = sprint.goal || '';
    if (datesEl) datesEl.textContent = `${sprint.start_date || ''} → ${sprint.end_date || ''}`;

    const pct = sprint.total_points > 0
      ? Math.round((sprint.completed_points / sprint.total_points) * 100)
      : 0;
    if (barEl)   barEl.style.width  = `${pct}%`;
    if (labelEl) labelEl.textContent = `${sprint.completed_points || 0} / ${sprint.total_points || 0} pts (${pct}%)`;
  }

  const stories = sprint.stories || scrumState.sprint;
  if (listEl) {
    if (!stories.length) {
      listEl.innerHTML = '<div class="story-placeholder">Sin stories en este sprint.</div>';
    } else {
      listEl.innerHTML = stories.map(s => {
        const statusMap = {
          sprint:      { icon: '⏳', label: 'Pendiente' },
          in_progress: { icon: '🔄', label: 'En progreso' },
          done:        { icon: '✅', label: 'Hecho' },
          failed:      { icon: '❌', label: 'Fallida' },
        };
        const st = statusMap[s.status] || { icon: '⏳', label: s.status };
        return `<div class="story-card" data-id="${esc(s.id)}">
          <div class="story-header">
            <span class="story-status-icon">${st.icon}</span>
            <span class="story-points">${s.story_points || 0}pt</span>
            <span class="story-priority priority-${esc(s.priority || 'medium')}">${esc(s.priority || 'medium')}</span>
          </div>
          <div class="story-title">${esc(s.title || '')}</div>
          <div class="story-status">${st.label}</div>
        </div>`;
      }).join('');
    }
  }

  if (runBtn) {
    runBtn.disabled = scrumState.sprintRunning || sprint.status !== 'active';
    runBtn.textContent = scrumState.sprintRunning ? 'Ejecutando...' : 'Ejecutar Sprint';
  }
}

// ── Done Tab rendering ───────────────────────────────────────
function renderDoneTab() {
  const list = document.getElementById('done-list');
  if (!list) return;
  const stories = scrumState.done;
  if (!stories.length) {
    list.innerHTML = '<div class="story-placeholder">Sin stories completadas.</div>';
    return;
  }
  list.innerHTML = stories.map(s => `
    <div class="story-card" data-id="${esc(s.id)}">
      <div class="story-header">
        <span class="story-points">${s.story_points || 0}pt</span>
        <span class="story-priority priority-${esc(s.priority || 'medium')}">${esc(s.priority || 'medium')}</span>
      </div>
      <div class="story-title">✅ ${esc(s.title || '')}</div>
      <div class="story-links">
        ${s.pr_url ? `<a class="story-link" href="${esc(s.pr_url)}" target="_blank">PR #${esc(s.pr_url.split('/').pop())}</a>` : ''}
        ${s.commit_hash ? `<span class="story-link">${esc(s.commit_hash.substring(0,7))}</span>` : ''}
        ${s.completed_at ? `<span style="font-size:10px;color:var(--text-muted);">${esc(s.completed_at.substring(0,10))}</span>` : ''}
      </div>
    </div>
  `).join('');
}

// ── Run Sprint via WebSocket ─────────────────────────────────
function runSprint() {
  const sprint = scrumState.currentSprint;
  if (!sprint || scrumState.sprintRunning) return;

  if (!confirm(`¿Ejecutar el sprint "${sprint.goal}"?\nEl agente implementará todas las stories de forma autónoma.`)) return;

  scrumState.sprintRunning = true;
  const runBtn = document.getElementById('btn-run-sprint');
  const stopBtn = document.getElementById('btn-stop-sprint');
  if (runBtn) { runBtn.disabled = true; runBtn.textContent = 'Ejecutando...'; }
  if (stopBtn) { stopBtn.style.display = ''; }

  if (scrumState.sprintWs) { scrumState.sprintWs.close(); scrumState.sprintWs = null; }

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/ws/sprint`);
  scrumState.sprintWs = ws;

  ws.onopen = () => {
    ws.send(JSON.stringify({
      project: activeProject,
      sprint_id: sprint.id,
      model: 'gpt-4o-mini',
    }));
    addMessage('system', `Iniciando sprint ${sprint.id}: "${sprint.goal}"`, 'Sprint');
  };

  ws.onmessage = (event) => {
    try {
      handleSprintWsMessage(JSON.parse(event.data));
    } catch (e) {
      console.error('[sprint ws] parse error:', e);
    }
  };

  ws.onclose = () => {
    scrumState.sprintRunning = false;
    scrumState.sprintWs = null;
    const b = document.getElementById('btn-run-sprint');
    if (b) { b.disabled = false; b.textContent = 'Ejecutar Sprint'; }
    const s = document.getElementById('btn-stop-sprint');
    if (s) { s.style.display = 'none'; }
    loadScrumBoard(activeProject);
  };

  ws.onerror = () => {
    addMessage('error', 'Error de conexión con el sprint.', 'Sprint Error');
    scrumState.sprintRunning = false;
  };
}

function stopSprint() {
  if (scrumState.sprintWs) {
    scrumState.sprintWs.close();
    scrumState.sprintWs = null;
    addMessage('system', 'Sprint detenido por el Director.', 'Sprint');
  }
}

// Estado interno del sprint en ejecución
const _sprintRunState = { goal: '', done: 0, total: 0, pts: 0, totalPts: 0 };

function _showSprintRunSection(visible) {
  const s = document.getElementById('sprint-run-section');
  if (s) s.style.display = visible ? '' : 'none';
}

function _updateSprintRunInfo() {
  const goal  = document.getElementById('sprint-run-goal');
  const prog  = document.getElementById('sprint-run-progress');
  const done  = document.getElementById('sprint-run-done');
  const total = document.getElementById('sprint-run-total');
  const pts   = document.getElementById('sprint-run-pts');
  if (goal)  goal.textContent  = _sprintRunState.goal;
  if (done)  done.textContent  = _sprintRunState.done;
  if (total) total.textContent = _sprintRunState.total;
  if (pts)   pts.textContent   = `${_sprintRunState.pts}/${_sprintRunState.totalPts}`;
}

function _setSprintRunStory(title) {
  const el = document.getElementById('sprint-run-story');
  if (el) el.textContent = title ? `Implementando: ${title}` : '';
}

function handleSprintWsMessage(msg) {
  const type = msg.type;

  if (type === 'log') {
    appendLog(msg.level, msg.msg);
    return;
  }
  if (type === 'sprint_start') {
    _sprintRunState.goal = msg.goal || '';
    _sprintRunState.done = 0;
    _sprintRunState.total = msg.total_stories || 0;
    _sprintRunState.pts = 0;
    _sprintRunState.totalPts = scrumState.currentSprint?.total_points || 0;
    _showSprintRunSection(true);
    _updateSprintRunInfo();
    addMessage('system', `Sprint iniciado: "${esc(msg.goal)}" (${msg.total_stories} stories)`, 'Sprint');
  }
  else if (type === 'story_start') {
    resetPhases();
    markPhase('setup', 'Iniciando story...');
    _setSprintRunStory(msg.title);
    const sb = document.getElementById('session-badge');
    if (sb) sb.textContent = `${msg.story_points || 0}pt`;
    addMessage('system', `[${esc(msg.story_id)}] Iniciando: "${esc(msg.title)}" (${msg.story_points}pt)`, 'Story');
  }
  else if (type === 'phase') {
    const PHASE_LABELS_LOCAL = {
      setup: 'Iniciando...', analyze: 'Analizando...', propose: 'Propuestas...',
      design: 'Diseñando...', implement: 'Implementando...', pipeline: 'Pipeline QA...',
      fix: 'Corrigiendo...', commit: 'Commit...', pr: 'Pull Request...', deploy: 'Deploy...', done: 'Listo',
    };
    if (msg.phase) markPhase(msg.phase, PHASE_LABELS_LOCAL[msg.phase] || msg.phase);
    appendLog('INFO', `[${msg.story_id || ''}] ${msg.node || ''}: ${msg.phase || ''}`);
  }
  else if (type === 'implementation') {
    addMessage('system', `[${esc(msg.story_id)}] Implementación completada.`, 'Story');
  }
  else if (type === 'pr') {
    const link = msg.content ? `<a class="msg-link" href="${esc(msg.content)}" target="_blank">${esc(msg.content)}</a>` : '—';
    addMessageHTML('result', `<div class="msg-label">[${esc(msg.story_id)}] Pull Request</div>${link}`);
  }
  else if (type === 'story_done') {
    markPhase('done', 'Listo');
    _sprintRunState.done += 1;
    _sprintRunState.pts += (msg.story_points || 0);
    _updateSprintRunInfo();
    _setSprintRunStory('');
    addMessage('result', `Story completada: "${esc(msg.title)}" (+${msg.story_points}pt)${msg.pr_url ? '\nPR: ' + msg.pr_url : ''}`, 'Story Done');
    loadScrumBoard(activeProject);
  }
  else if (type === 'story_failed') {
    markPhaseError();
    _setSprintRunStory('');
    addMessage('error', `Story fallida: "${esc(msg.title)}"\n${esc(msg.error || '')}`, 'Story Error');
    loadScrumBoard(activeProject);
  }
  else if (type === 'sprint_done') {
    _showSprintRunSection(false);
    resetPhases();
    addMessage('result', msg.review_summary || 'Sprint completado.', 'Sprint completado');
    if (msg.handoff) {
      addMessageHTML('result',
        `<div class="msg-label" style="color:var(--green);font-size:13px;">¿Cómo ver el resultado?</div>` +
        `<div class="msg-content" style="white-space:pre-wrap;">${esc(msg.handoff)}</div>`
      );
    }
    if (msg.sprint_pr_url) {
      addMessageHTML('result',
        `<div class="msg-label">Pull Request</div>` +
        `<a class="msg-link" href="${esc(msg.sprint_pr_url)}" target="_blank">${esc(msg.sprint_pr_url)}</a>`
      );
    }
    loadScrumBoard(activeProject);
    loadProjectData(activeProject);
  }
  else if (type === 'error') {
    addMessage('error', msg.message, 'Error Sprint');
  }
  else if (type === 'finished') {
    _showSprintRunSection(false);
    addMessage('system', 'Sprint finalizado.', 'Sprint');
  }
}
