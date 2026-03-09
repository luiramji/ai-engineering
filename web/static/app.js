/* AI Engineering Platform — Frontend */

'use strict';

const output     = document.getElementById('output');
const submitBtn  = document.getElementById('submit-btn');
const featureInp = document.getElementById('feature-input');
const statusBadge = document.getElementById('status-badge');
const charCount  = document.getElementById('char-count');

let ws = null;

// ── char counter ──────────────────────────────────────────────
featureInp.addEventListener('input', () => {
  charCount.textContent = `${featureInp.value.length} chars`;
});

// ── Phase sidebar map ─────────────────────────────────────────
const PHASE_MAP = {
  setup:     'ph-setup',
  analyze:   'ph-analyze',
  design:    'ph-design',
  implement: 'ph-implement',
  test:      'ph-test',
  fix:       'ph-test',
  commit:    'ph-commit',
  done:      'ph-done',
};

let currentPhaseEl = null;

function setPhase(phase) {
  if (currentPhaseEl) {
    currentPhaseEl.classList.remove('active');
    currentPhaseEl.classList.add('done');
  }
  const id = PHASE_MAP[phase];
  if (id) {
    currentPhaseEl = document.getElementById(id);
    if (currentPhaseEl) currentPhaseEl.classList.add('active');
  }
}

function resetPhases() {
  Object.values(PHASE_MAP).forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.classList.remove('active', 'done', 'error'); }
  });
  currentPhaseEl = null;
}

// ── Append message block ──────────────────────────────────────
function addBlock(cssClass, label, content, collapsible = false) {
  const block = document.createElement('div');
  block.className = `msg-block ${cssClass}`;

  const labelEl = document.createElement('div');
  labelEl.className = 'msg-label';
  labelEl.textContent = label;

  const contentEl = document.createElement('div');
  contentEl.className = 'msg-content';
  contentEl.textContent = content;

  block.appendChild(labelEl);
  block.appendChild(contentEl);

  if (collapsible && content.length > 400) {
    contentEl.classList.add('collapsed');
    const btn = document.createElement('span');
    btn.className = 'expand-btn';
    btn.textContent = '▼ Mostrar completo';
    btn.onclick = () => {
      const collapsed = contentEl.classList.toggle('collapsed');
      btn.textContent = collapsed ? '▼ Mostrar completo' : '▲ Colapsar';
    };
    block.appendChild(btn);
  }

  output.appendChild(block);
  output.scrollTop = output.scrollHeight;
  return block;
}

function addSpinner(label) {
  const block = document.createElement('div');
  block.className = 'msg-block phase';
  block.innerHTML = `<span class="spinner"></span><span>${label}</span>`;
  block.id = 'spinner-block';
  output.appendChild(block);
  output.scrollTop = output.scrollHeight;
}

function removeSpinner() {
  const s = document.getElementById('spinner-block');
  if (s) s.remove();
}

// ── WebSocket handler ─────────────────────────────────────────
function connectAndRun(featureRequest, project) {
  if (ws) { ws.close(); ws = null; }

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws/agent`);

  ws.onopen = () => {
    ws.send(JSON.stringify({ feature_request: featureRequest, project }));
  };

  ws.onmessage = (evt) => {
    const msg = JSON.parse(evt.data);
    removeSpinner();

    switch (msg.type) {

      case 'started':
        addBlock('phase', '🚀 INICIADO', `Proyecto: ${msg.project}\nFeature: ${msg.feature}`);
        break;

      case 'phase':
        setPhase(msg.phase);
        if (msg.phase !== 'done' && msg.phase !== 'error') {
          addSpinner(msg.label);
        }
        break;

      case 'analysis':
        addBlock('analysis', '🔍 ANÁLISIS DEL CODEBASE', msg.content, true);
        break;

      case 'design':
        addBlock('design', '📐 DISEÑO DE SOLUCIÓN', msg.content, true);
        break;

      case 'implementation':
        addBlock('implement', '⚡ IMPLEMENTACIÓN', msg.content, true);
        break;

      case 'tests':
        addBlock(
          msg.passed ? 'tests-ok' : 'tests-fail',
          msg.passed ? '🧪 TESTS — PASARON ✓' : '🧪 TESTS — FALLARON ✗',
          msg.content, true,
        );
        break;

      case 'fix':
        addBlock('implement', '🔧 CORRECCIÓN APLICADA', msg.content, true);
        break;

      case 'commit':
        addBlock('commit', '📦 COMMIT Y PUSH', `Commit: ${msg.hash}`);
        break;

      case 'done':
        setPhase('done');
        addBlock('done-ok', '✅ COMPLETADO', msg.summary);
        setStatus('done', 'Completado');
        setRunning(false);
        break;

      case 'error':
        addBlock('err', '❌ ERROR', msg.message);
        setStatus('error', 'Error');
        setRunning(false);
        // Marcar fase activa como error
        if (currentPhaseEl) {
          currentPhaseEl.classList.remove('active');
          currentPhaseEl.classList.add('error');
        }
        break;

      case 'finished':
        removeSpinner();
        setRunning(false);
        break;
    }
  };

  ws.onerror = () => {
    removeSpinner();
    addBlock('err', '❌ CONEXIÓN', 'Error de WebSocket. Recarga la página.');
    setStatus('error', 'Error');
    setRunning(false);
  };

  ws.onclose = () => {
    removeSpinner();
  };
}

function setStatus(cls, label) {
  statusBadge.className = `badge ${cls}`;
  statusBadge.textContent = label;
}

function setRunning(running) {
  submitBtn.disabled = running;
  featureInp.disabled = running;
  submitBtn.textContent = running ? 'Ejecutando...' : 'Ejecutar →';
}

// ── Submit ────────────────────────────────────────────────────
function submitFeature() {
  const text = featureInp.value.trim();
  if (!text) { featureInp.focus(); return; }

  const project = document.getElementById('project-select').value;
  if (!project) {
    addBlock('err', 'ERROR', 'No hay proyectos disponibles.');
    return;
  }

  // Reset UI
  output.innerHTML = '';
  resetPhases();
  setStatus('running', 'Ejecutando');
  setRunning(true);

  connectAndRun(text, project);
}

// ── Enter to submit (Ctrl+Enter) ──────────────────────────────
featureInp.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
    e.preventDefault();
    submitFeature();
  }
});
