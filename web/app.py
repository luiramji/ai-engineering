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

app = FastAPI(title="AI Engineering Platform", docs_url=None, redoc_url=None)

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
        {"request": Request, "page": "login", "error": "Credenciales incorrectas"},
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
        raw = await websocket.receive_text()
        payload = json.loads(raw)
        feature_request  = payload.get("feature_request", "").strip()
        project_name     = payload.get("project", "tracker_master")
        chosen_proposal  = payload.get("chosen_proposal", "a")

        if not feature_request:
            await _send(websocket, "error", message="El feature request no puede estar vacio.")
            return

        await _send(websocket, "started", project=project_name, feature=feature_request)

        from agent.engineering_agent import stream_feature_request

        async for event in stream_feature_request(feature_request, project_name, chosen_proposal=chosen_proposal):
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
