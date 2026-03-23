"""
AI Engineering Platform — Web Interface (v2)

Layout tres columnas:
  Izquierda: panel de proyectos + memoria del proyecto activo
  Centro:    chat con el agente
  Derecha:   checklist de tareas + progreso del feature activo

FastAPI + WebSockets + JWT auth
"""
import asyncio
import json
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import jwt
import uvicorn
from fastapi import (
    Cookie, Depends, FastAPI, Form, HTTPException,
    Request, WebSocket, WebSocketDisconnect, status,
)
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

sys.path.insert(0, "/opt/ai_engineering")
from config.settings import (
    WEB_HOST, WEB_PORT, WEB_USER, WEB_PASSWORD, SECRET_KEY, PROJECTS_DIR, DATA_DIR,
)
from agent.project_manager import get_all as get_all_projects, get_project
from agent.cost_tracker import get_summary as get_cost_summary

logger = logging.getLogger(__name__)

from contextlib import asynccontextmanager

@asynccontextmanager
async def _lifespan(app):
    """Al arrancar: resetea stories bloqueadas en 'in_progress' por reinicios anteriores."""
    try:
        from agent.project_manager import get_all as _get_all_projects
        from agent.story_manager import get_stories, save_stories, get_sprints, _save_sprints
        for project in _get_all_projects():
            pid = project.get("id", "")
            if not pid:
                continue
            stories = get_stories(pid)
            changed = False
            for s in stories:
                if s.get("status") == "in_progress":
                    s["status"] = "sprint"   # vuelve al sprint para poder reejecutarse
                    changed = True
            if changed:
                save_stories(pid, stories)
                logger.info(f"[startup] Reseteadas stories bloqueadas en '{pid}'")
    except Exception as e:
        logger.warning(f"[startup] Error reseteando stories: {e}")
    yield   # app corre aquí

app = FastAPI(title="AI Engineering Platform", docs_url=None, redoc_url=None, lifespan=_lifespan)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR    = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ─────────────────────────────────────────────────────────────
#  AUTH
# ─────────────────────────────────────────────────────────────

def _create_token(username: str) -> str:
    payload = {"sub": username, "iat": int(time.time()), "exp": int(time.time()) + 86400}
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")


def _verify_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload.get("sub")
    except Exception:
        return None


def get_current_user(session: Optional[str] = Cookie(default=None)) -> str:
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    user = _verify_token(session)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return user


# ─────────────────────────────────────────────────────────────
#  LOG HANDLER — redirige logs al WebSocket
# ─────────────────────────────────────────────────────────────

class WSLogHandler(logging.Handler):
    def __init__(self, queue: asyncio.Queue):
        super().__init__()
        self.queue = queue
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord):
        try:
            self.queue.put_nowait({
                "type": "log",
                "level": record.levelname,
                "msg": self.format(record),
                "ts": int(record.created * 1000),
            })
        except asyncio.QueueFull:
            pass


# ─────────────────────────────────────────────────────────────
#  ROUTES
# ─────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "page": "login", "error": None})


@app.post("/login")
async def login(username: str = Form(...), password: str = Form(...)):
    if username == WEB_USER and password == WEB_PASSWORD:
        token = _create_token(username)
        resp = RedirectResponse(url="/", status_code=303)
        resp.set_cookie("session", token, httponly=True, max_age=86400)
        return resp
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "page": "login", "error": "Credenciales incorrectas"},
        status_code=401,
    )


@app.get("/logout")
async def logout():
    resp = RedirectResponse(url="/login")
    resp.delete_cookie("session")
    return resp


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, session: Optional[str] = Cookie(default=None)):
    user = _verify_token(session) if session else None
    if not user:
        return RedirectResponse(url="/login")

    projects = get_all_projects()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "page": "main",
        "user": user,
        "projects": projects,
    })


# ─────────────────────────────────────────────────────────────
#  API ENDPOINTS
# ─────────────────────────────────────────────────────────────

@app.post("/api/projects")
async def api_create_project(request: Request, user: str = Depends(get_current_user)):
    """Crea un proyecto: crea repo GitHub, clona, asigna servidor."""
    from agent.project_manager import upsert_project
    from config.settings import GITHUB_TOKEN, APP_SERVER_HOST, APP_SERVER_USER, APP_SERVER_KEY
    import re, httpx, subprocess

    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")

    project_id       = re.sub(r"[^a-z0-9_]", "_", name.lower())
    description      = body.get("description", "")
    repository       = body.get("repository", "").strip()
    exclusive_server = body.get("exclusive_server", False)
    local_path       = str(PROJECTS_DIR / project_id)

    # ── Crear repo en GitHub si no se proporcionó uno existente ──
    if not repository and GITHUB_TOKEN:
        gh_name = re.sub(r"[^a-zA-Z0-9_.-]", "-", name)
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                "https://api.github.com/user/repos",
                headers={
                    "Authorization": f"Bearer {GITHUB_TOKEN}",
                    "Accept": "application/vnd.github+json",
                },
                json={
                    "name":        gh_name,
                    "description": description,
                    "private":     True,
                    "auto_init":   True,
                },
            )
        if resp.status_code in (201, 422):  # 422 = ya existe
            gh_data    = resp.json()
            ssh_url    = gh_data.get("ssh_url") or f"git@github.com:luiramji/{gh_name}.git"
            repository = ssh_url
        else:
            raise HTTPException(status_code=502, detail=f"GitHub API error: {resp.text[:200]}")

    # ── Clonar repo localmente si no existe ya ────────────────
    if repository and not Path(local_path).exists():
        result = subprocess.run(
            ["git", "clone", repository, local_path],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            logger.warning(f"git clone falló: {result.stderr[:200]}")

    # ── Servidor de despliegue ────────────────────────────────
    # Por defecto: servidor de aplicaciones compartido.
    # Si exclusive_server=True: crear nuevo servidor en Vultr (async, notifica por Telegram).
    if exclusive_server:
        server_entry = {
            "ip": "pending",
            "user": "root",
            "ssh_key": APP_SERVER_KEY,
            "purpose": "production",
            "status": "provisioning",
            "note": "Servidor Vultr en creación — se actualizará al completar",
        }
        asyncio.create_task(_provision_vultr_server(project_id, name))
    else:
        server_entry = {
            "ip": APP_SERVER_HOST,
            "user": APP_SERVER_USER,
            "ssh_key": APP_SERVER_KEY,
            "purpose": "production",
        }

    project = {
        "id":          project_id,
        "name":        name,
        "description": description,
        "repository":  repository,
        "local_path":  local_path,
        "servers":     [server_entry],
        "memory":    {"architecture": "", "tech_decisions": [], "tech_debt": [], "roadmap": []},
        "checklist": [],
    }
    saved = upsert_project(project)
    return JSONResponse(saved, status_code=201)


async def _provision_vultr_server(project_id: str, project_name: str):
    """
    Crea un servidor Vultr en background, espera a que esté listo,
    instala la SSH key e instala el proyecto.

    El usuario autorizó la creación al marcar 'Requiere servidor exclusivo' en la UI.
    """
    import httpx as _httpx
    from agent.project_manager import get_project, upsert_project
    from config.settings import VULTR_API_KEY, APP_SERVER_KEY

    VULTR_BASE = "https://api.vultr.com/v2"
    headers = {"Authorization": f"Bearer {VULTR_API_KEY}", "Content-Type": "application/json"}

    logger.info(f"[vultr] Iniciando provisión para proyecto '{project_id}'")

    try:
        # ── 1. Obtener o registrar SSH key en Vultr ───────────
        ssh_pub_key_path = str(Path(APP_SERVER_KEY).with_suffix(".pub"))
        vultr_sshkey_id = None
        try:
            pub_key_content = Path(ssh_pub_key_path).read_text().strip()
        except Exception:
            # Intentar generarla desde la clave privada
            import subprocess as _sp
            r = _sp.run(["ssh-keygen", "-y", "-f", APP_SERVER_KEY], capture_output=True, text=True)
            pub_key_content = r.stdout.strip() if r.returncode == 0 else ""

        if pub_key_content:
            async with _httpx.AsyncClient(timeout=15) as http:
                # Verificar si ya existe
                resp = await http.get(f"{VULTR_BASE}/ssh-keys", headers=headers)
                existing_keys = resp.json().get("ssh_keys", []) if resp.is_success else []
                for k in existing_keys:
                    if k.get("ssh_key", "").strip() == pub_key_content:
                        vultr_sshkey_id = k["id"]
                        logger.info(f"[vultr] SSH key ya registrada: {vultr_sshkey_id}")
                        break

                if not vultr_sshkey_id:
                    resp = await http.post(
                        f"{VULTR_BASE}/ssh-keys", headers=headers,
                        json={"name": "ai-engineering", "ssh_key": pub_key_content},
                    )
                    if resp.is_success:
                        vultr_sshkey_id = resp.json().get("ssh_key", {}).get("id")
                        logger.info(f"[vultr] SSH key registrada: {vultr_sshkey_id}")

        # ── 2. Crear instancia ────────────────────────────────
        payload = {
            "label":    f"app-{project_id}",
            "region":   "ewr",          # New Jersey
            "plan":     "vc2-1c-1gb",   # 1 vCPU, 1 GB RAM — $6/mes
            "os_id":    1743,           # Ubuntu 24.04 LTS
            "backups":  "disabled",
            "hostname": f"app-{project_id}",
        }
        if vultr_sshkey_id:
            payload["sshkey_id"] = [vultr_sshkey_id]

        async with _httpx.AsyncClient(timeout=30) as http:
            resp = await http.post(f"{VULTR_BASE}/instances", headers=headers, json=payload)

        if not resp.is_success:
            logger.error(f"[vultr] Error al crear instancia: {resp.status_code} {resp.text[:300]}")
            return

        instance = resp.json().get("instance", {})
        instance_id = instance.get("id")
        logger.info(f"[vultr] Instancia creada id={instance_id}, esperando IP...")

        # ── 3. Polling hasta que tenga IP y esté activa ───────
        new_ip = None
        for attempt in range(30):   # máx ~10 minutos
            await asyncio.sleep(20)
            async with _httpx.AsyncClient(timeout=15) as http:
                r = await http.get(f"{VULTR_BASE}/instances/{instance_id}", headers=headers)
            if not r.is_success:
                continue
            inst_data = r.json().get("instance", {})
            ip = inst_data.get("main_ip", "")
            status = inst_data.get("status", "")
            server_state = inst_data.get("server_state", "")
            logger.info(f"[vultr] Polling {attempt+1}/30 — status={status} server_state={server_state} ip={ip}")

            if ip and ip != "0.0.0.0" and status == "active":  # nosec B104 — comparación, no binding
                new_ip = ip
                break

        if not new_ip:
            logger.error(f"[vultr] Timeout esperando IP para instancia {instance_id}")
            return

        logger.info(f"[vultr] Servidor listo: {new_ip}")

        # ── 4. Actualizar proyecto con la IP real ─────────────
        project = get_project(project_id)
        if project:
            for srv in project.get("servers", []):
                if srv.get("status") == "provisioning":
                    srv["ip"]      = new_ip
                    srv["user"]    = "root"
                    srv["ssh_key"] = APP_SERVER_KEY
                    srv["status"]  = "active"
                    srv["vultr_id"] = instance_id
                    srv.pop("note", None)
            upsert_project(project)

        # ── 5. Notificar al Director via Telegram ─────────────
        try:
            from tg_bot.notifier import send_message
            await send_message(
                f"✅ Servidor exclusivo listo para *{project_name}*\n"
                f"IP: `{new_ip}`\nPlan: vc2-1c-1gb (New Jersey)"
            )
        except Exception as e:
            logger.warning(f"[vultr] No se pudo notificar al Director: {e}")

    except Exception as e:
        logger.error(f"[vultr] Error provisionando servidor para {project_id}: {e}", exc_info=True)


@app.delete("/api/projects/{project_id}")
async def api_delete_project(project_id: str, user: str = Depends(get_current_user)):
    """Elimina un proyecto del registro y sus stories/sprints asociados."""
    from agent.project_manager import delete_project
    from agent.story_manager import STORIES_DIR, SPRINTS_DIR
    ok = delete_project(project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    # Borrar archivos de stories y sprints
    for f in [STORIES_DIR / f"{project_id}.json", SPRINTS_DIR / f"{project_id}.json"]:
        try:
            f.unlink(missing_ok=True)
        except Exception:
            pass
    return JSONResponse({"ok": True})


@app.get("/api/projects")
async def api_projects(user: str = Depends(get_current_user)):
    """Lista proyectos con último commit."""
    projects = get_all_projects()
    result = []
    for p in projects:
        local_path = p.get("local_path", "")
        last_commit = "N/A"
        if local_path and Path(local_path).exists():
            try:
                r = subprocess.run(
                    ["git", "log", "-1", "--pretty=format:%h | %s | %ar"],
                    cwd=local_path, capture_output=True, text=True, timeout=5,
                )
                last_commit = r.stdout.strip()
            except Exception:
                pass
        result.append({**p, "last_commit": last_commit})
    return JSONResponse({"projects": result})


@app.get("/api/project/{project_id}")
async def api_project_detail(project_id: str, user: str = Depends(get_current_user)):
    """Detalles de un proyecto con memoria y checklist."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado")
    return JSONResponse(project)


@app.get("/api/costs")
async def api_costs(user: str = Depends(get_current_user)):
    """Resumen de costos LLM."""
    return JSONResponse(get_cost_summary())


@app.get("/api/greeting/{name}")
async def api_greeting(name: str, user: str = Depends(get_current_user)):
    """Retorna un saludo personalizado para el nombre proporcionado."""
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="El nombre no puede estar vacío")
    if len(name) > 100:
        raise HTTPException(status_code=400, detail="Nombre demasiado largo (máx. 100 caracteres)")
    return JSONResponse({
        "name": name,
        "greeting": f"¡Hola, {name}! Bienvenido a AI Engineering Platform.",
        "timestamp": datetime.now().isoformat(),
    })


@app.get("/api/health")
async def api_health():
    """Health check."""
    import httpx
    from config.settings import LITELLM_PROXY_URL
    try:
        resp = httpx.get(f"{LITELLM_PROXY_URL}/health/liveliness", timeout=3)
        litellm_ok = resp.status_code == 200
    except Exception:
        litellm_ok = False
    return JSONResponse({"status": "ok", "litellm": litellm_ok})


# ─────────────────────────────────────────────────────────────
#  WEBSOCKET — streaming del agente
# ─────────────────────────────────────────────────────────────

PHASE_LABELS = {
    "setup":          "Iniciando...",
    "analyze":        "Analizando codebase...",
    "propose":        "Generando propuestas...",
    "await_decision": "Esperando decision del Director...",
    "design":         "Disenando solucion...",
    "implement":      "Implementando codigo...",
    "pipeline":       "Ejecutando pipeline de calidad...",
    "fix":            "Corrigiendo errores...",
    "commit":         "Haciendo commit...",
    "pr":             "Creando Pull Request...",
    "deploy":         "Desplegando...",
    "done":           "Completado",
    "error":          "Error",
}

_AGENT_LOGGERS = [
    "agent.nodes", "agent.engineering_agent",
    "agent.deploy", "pipeline.quality",
]


async def _send(ws: WebSocket, msg_type: str, **data):
    try:
        await ws.send_json({"type": msg_type, **data})
    except Exception:
        pass


@app.websocket("/ws/agent")
async def agent_websocket(websocket: WebSocket):
    session = websocket.cookies.get("session")
    user = _verify_token(session) if session else None
    if not user:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    logger.info(f"WebSocket conectado — usuario: {user}")

    log_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    ws_handler = WSLogHandler(log_queue)
    ws_handler.setLevel(logging.INFO)

    agent_loggers = [logging.getLogger(name) for name in _AGENT_LOGGERS]
    for al in agent_loggers:
        al.addHandler(ws_handler)

    stop_logs = asyncio.Event()

    async def forward_logs():
        while not stop_logs.is_set():
            try:
                item = await asyncio.wait_for(log_queue.get(), timeout=0.3)
                await _send(websocket, **item)
            except asyncio.TimeoutError:
                continue
        while not log_queue.empty():
            item = log_queue.get_nowait()
            await _send(websocket, **item)

    log_task = asyncio.create_task(forward_logs())

    try:
        # ── Paso 1: recibir instrucción del Director ──────────
        raw = await websocket.receive_text()
        payload = json.loads(raw)
        feature_request = payload.get("feature_request", "").strip()
        project_name    = payload.get("project", "tracker_master")

        if not feature_request:
            await _send(websocket, "error", message="El feature request no puede estar vacio.")
            return

        # ── Paso 2: pre-análisis (modelo barato) → clarificación ──
        await _send(websocket, "phase", node="clarify", phase="clarify", label="Analizando instrucción...")
        from agent.engineering_agent import clarify_feature_request
        clarification = await clarify_feature_request(feature_request, project_name)
        await _send(websocket, "clarify", **clarification)

        # ── Paso 3: esperar confirmación del Director ─────────
        raw2 = await websocket.receive_text()
        payload2 = json.loads(raw2)

        if payload2.get("action") == "cancel":
            await _send(websocket, "cancelled", message="Cancelado por el Director.")
            return

        additional_context = payload2.get("additional_context", "").strip()
        selected_model     = payload2.get("selected_model", clarification.get("recommended_model", "gpt-4o-mini"))
        chosen_proposal    = payload2.get("chosen_proposal", "a")

        # Añadir contexto adicional a la instrucción si el Director respondió preguntas
        full_request = feature_request
        if additional_context:
            full_request += f"\n\nACLARACIONES DEL DIRECTOR:\n{additional_context}"

        await _send(websocket, "started", project=project_name, feature=full_request, model=selected_model)

        from agent.engineering_agent import stream_feature_request

        async for event in stream_feature_request(
            full_request, project_name,
            chosen_proposal=chosen_proposal,
            selected_model=selected_model,
            clarifications=additional_context,
        ):
            node  = event.get("node", "")
            phase = event.get("phase", "")
            label = PHASE_LABELS.get(phase, phase)

            await _send(websocket, "phase", node=node, phase=phase, label=label)

            # Enviar datos específicos de cada fase
            for key, evt_type in [
                ("analysis",              "analysis"),
                ("proposal_a",            "proposal"),
                ("design",                "design"),
                ("implementation_summary","implementation"),
                ("test_results",          "tests"),
                ("pr_url",                "pr"),
                ("result_summary",        "done"),
                ("error",                 "error"),
            ]:
                if event.get(key):
                    extra = {}
                    if key == "test_results":
                        extra["passed"] = event.get("tests_passed", False)
                    if key == "proposal_a":
                        extra["proposal_b"] = event.get("proposal_b", "")
                    if key == "error":
                        await _send(websocket, "error", message=event[key])
                        return
                    await _send(websocket, evt_type, content=event[key], **extra)

        await _send(websocket, "finished")

    except WebSocketDisconnect:
        logger.info(f"WebSocket desconectado — usuario: {user}")
    except Exception as e:
        logger.exception(f"Error en WebSocket: {e}")
        await _send(websocket, "error", message=f"Error interno: {str(e)[:200]}")
    finally:
        stop_logs.set()
        await asyncio.sleep(0.4)
        log_task.cancel()
        for al in agent_loggers:
            al.removeHandler(ws_handler)
        try:
            await websocket.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
#  SCRUM API ENDPOINTS
# ─────────────────────────────────────────────────────────────

@app.post("/api/projects/{project_id}/stories/generate")
async def api_generate_stories(project_id: str, request: Request, user: str = Depends(get_current_user)):
    """Descompone un épico en user stories (sin guardar, para revisión)."""
    from agent.engineering_agent import generate_stories_from_epic
    body = await request.json()
    epic = body.get("epic", "").strip()
    if not epic:
        raise HTTPException(status_code=400, detail="El épico no puede estar vacío")
    stories = await generate_stories_from_epic(epic, project_id)
    return JSONResponse(stories)


@app.get("/api/projects/{project_id}/stories")
async def api_get_stories(project_id: str, user: str = Depends(get_current_user)):
    """Retorna stories agrupadas por estado."""
    from agent.story_manager import get_stories
    stories = get_stories(project_id)
    backlog    = [s for s in stories if s.get("status") == "backlog"]
    in_sprint  = [s for s in stories if s.get("status") in ("sprint", "in_progress")]
    done       = [s for s in stories if s.get("status") == "done"]
    return JSONResponse({"backlog": backlog, "sprint": in_sprint, "done": done})


@app.post("/api/projects/{project_id}/stories")
async def api_save_stories(project_id: str, request: Request, user: str = Depends(get_current_user)):
    """Guarda una lista de stories aprobadas al backlog."""
    from agent.story_manager import upsert_story
    body = await request.json()
    if not isinstance(body, list):
        raise HTTPException(status_code=400, detail="Se esperaba una lista de stories")
    saved = []
    for story in body:
        story["status"] = "backlog"
        saved.append(upsert_story(project_id, story))
    return JSONResponse(saved, status_code=201)


@app.patch("/api/projects/{project_id}/stories/{story_id}")
async def api_update_story(
    project_id: str, story_id: str, request: Request, user: str = Depends(get_current_user)
):
    """Actualiza campos de una story (título, descripción, criterios, puntos, prioridad)."""
    from agent.story_manager import get_story, upsert_story
    story = get_story(project_id, story_id)
    if not story:
        raise HTTPException(status_code=404, detail="Story no encontrada")
    body = await request.json()
    allowed = ("title", "description", "acceptance_criteria", "story_points", "priority", "clarification_question")
    for k in allowed:
        if k in body:
            story[k] = body[k]
    updated = upsert_story(project_id, story)
    return JSONResponse(updated)


@app.delete("/api/projects/{project_id}/stories/{story_id}")
async def api_delete_story(project_id: str, story_id: str, user: str = Depends(get_current_user)):
    """Elimina una story del backlog."""
    from agent.story_manager import delete_story
    ok = delete_story(project_id, story_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Story no encontrada")
    return JSONResponse({"ok": True})


@app.post("/api/projects/{project_id}/sprints")
async def api_create_sprint(project_id: str, request: Request, user: str = Depends(get_current_user)):
    """Crea un nuevo sprint con las stories seleccionadas."""
    from agent.story_manager import create_sprint
    body = await request.json()
    goal       = body.get("goal", "").strip()
    story_ids  = body.get("story_ids", [])
    start_date = body.get("start_date", "")
    end_date   = body.get("end_date", "")
    if not goal or not story_ids:
        raise HTTPException(status_code=400, detail="goal y story_ids son requeridos")
    sprint = create_sprint(project_id, goal, story_ids, start_date, end_date)
    return JSONResponse(sprint, status_code=201)


@app.get("/api/projects/{project_id}/sprints")
async def api_get_sprints(project_id: str, user: str = Depends(get_current_user)):
    """Lista todos los sprints del proyecto."""
    from agent.story_manager import get_sprints
    return JSONResponse(get_sprints(project_id))


@app.get("/api/projects/{project_id}/sprints/current")
async def api_get_current_sprint(project_id: str, user: str = Depends(get_current_user)):
    """Retorna el sprint activo o 404."""
    from agent.story_manager import get_current_sprint, get_stories
    sprint = get_current_sprint(project_id)
    if not sprint:
        raise HTTPException(status_code=404, detail="No hay sprint activo")
    # Enriquecer con stories
    all_stories = get_stories(project_id)
    story_map = {s["id"]: s for s in all_stories}
    sprint["stories"] = [story_map[sid] for sid in sprint.get("story_ids", []) if sid in story_map]
    return JSONResponse(sprint)


# ─────────────────────────────────────────────────────────────
#  WEBSOCKET — Sprint execution streaming
# ─────────────────────────────────────────────────────────────

@app.websocket("/ws/sprint")
async def sprint_websocket(websocket: WebSocket):
    session = websocket.cookies.get("session")
    user = _verify_token(session) if session else None
    if not user:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    logger.info(f"[ws/sprint] conectado — usuario: {user}")

    log_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    ws_handler = WSLogHandler(log_queue)
    ws_handler.setLevel(logging.INFO)

    agent_loggers = [logging.getLogger(name) for name in _AGENT_LOGGERS]
    for al in agent_loggers:
        al.addHandler(ws_handler)

    stop_logs = asyncio.Event()

    async def forward_logs():
        while not stop_logs.is_set():
            try:
                item = await asyncio.wait_for(log_queue.get(), timeout=0.3)
                await _send(websocket, **item)
            except asyncio.TimeoutError:
                continue
        while not log_queue.empty():
            item = log_queue.get_nowait()
            await _send(websocket, **item)

    log_task = asyncio.create_task(forward_logs())

    try:
        raw = await websocket.receive_text()
        payload = json.loads(raw)
        project_name = payload.get("project", "").strip()
        sprint_id    = payload.get("sprint_id", "").strip()
        model        = payload.get("model", "gpt-4o-mini")

        if not project_name or not sprint_id:
            await _send(websocket, "error", message="project y sprint_id son requeridos")
            return

        await _send(websocket, "started", project=project_name, sprint_id=sprint_id, model=model)

        from agent.engineering_agent import run_sprint

        async for event in run_sprint(project_name, sprint_id, model=model):
            msg_type = event.pop("type", "log")
            await _send(websocket, msg_type, **event)

        await _send(websocket, "finished")

    except WebSocketDisconnect:
        logger.info(f"[ws/sprint] desconectado — usuario: {user}")
    except Exception as e:
        logger.exception(f"[ws/sprint] Error: {e}")
        await _send(websocket, "error", message=f"Error interno: {str(e)[:200]}")
    finally:
        stop_logs.set()
        await asyncio.sleep(0.4)
        log_task.cancel()
        for al in agent_loggers:
            al.removeHandler(ws_handler)
        try:
            await websocket.close()
        except Exception:
            pass


def run():
    uvicorn.run(
        "web.app:app",
        host=WEB_HOST,
        port=WEB_PORT,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
