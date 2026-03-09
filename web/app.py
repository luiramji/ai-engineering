"""
AI Engineering Platform — Web Interface

FastAPI app con:
- Login con sesión (cookie JWT simple)
- Chat en tiempo real via WebSocket
- Streaming del progreso del agente fase a fase
- Listado de proyectos disponibles
"""
import asyncio
import json
import logging
import os
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
    WEB_HOST, WEB_PORT, WEB_USER, WEB_PASSWORD, SECRET_KEY, PROJECTS_DIR,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="AI Engineering Platform", docs_url=None, redoc_url=None)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR    = Path(__file__).parent / "static"

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ─────────────────────────────────────────────────────────────
#  AUTH — JWT simple en cookie
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
#  RUTAS HTTP
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
    return HTMLResponse(
        content=f"""
        <html><body style="font-family:monospace;padding:40px;background:#0d1117;color:#ff6b6b">
        <h2>Login fallido</h2><p>Credenciales incorrectas.</p>
        <a href="/login" style="color:#58a6ff">Volver</a></body></html>
        """,
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

    # Listar proyectos disponibles
    projects = []
    if PROJECTS_DIR.exists():
        for p in sorted(PROJECTS_DIR.iterdir()):
            if p.is_dir() and (p / ".git").exists():
                projects.append(p.name)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "page": "chat",
        "user": user,
        "projects": projects,
    })


@app.get("/api/projects")
async def list_projects(user: str = Depends(get_current_user)):
    projects = []
    if PROJECTS_DIR.exists():
        for p in sorted(PROJECTS_DIR.iterdir()):
            if p.is_dir() and (p / ".git").exists():
                import subprocess
                try:
                    result = subprocess.run(
                        ["git", "log", "-1", "--pretty=format:%h │ %s"],
                        cwd=str(p), capture_output=True, text=True, timeout=5,
                    )
                    last_commit = result.stdout.strip()
                except Exception:
                    last_commit = "N/A"
                projects.append({"name": p.name, "path": str(p), "last_commit": last_commit})
    return JSONResponse({"projects": projects})


# ─────────────────────────────────────────────────────────────
#  WEBSOCKET — streaming del agente
# ─────────────────────────────────────────────────────────────

PHASE_LABELS = {
    "setup":      "⚙️  Iniciando...",
    "analyze":    "🔍 Analizando codebase...",
    "design":     "📐 Diseñando solución...",
    "implement":  "⚡ Implementando código...",
    "test":       "🧪 Ejecutando tests...",
    "fix":        "🔧 Corrigiendo errores...",
    "commit":     "📦 Haciendo commit...",
    "done":       "✅ Completado",
    "error":      "❌ Error",
}


async def _send(ws: WebSocket, msg_type: str, **data):
    try:
        await ws.send_json({"type": msg_type, **data})
    except Exception:
        pass


@app.websocket("/ws/agent")
async def agent_websocket(websocket: WebSocket):
    # Verificar sesión en el handshake
    session = websocket.cookies.get("session")
    user = _verify_token(session) if session else None
    if not user:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    logger.info(f"WebSocket conectado — usuario: {user}")

    try:
        # Esperar el mensaje de inicio con feature request y proyecto
        raw = await websocket.receive_text()
        payload = json.loads(raw)
        feature_request = payload.get("feature_request", "").strip()
        project_name    = payload.get("project", "tracker_master")

        if not feature_request:
            await _send(websocket, "error", message="El feature request no puede estar vacío.")
            return

        await _send(websocket, "started", project=project_name, feature=feature_request)

        # Importar aquí para no bloquear al iniciar la app
        from agent.engineering_agent import stream_feature_request

        async for event in stream_feature_request(feature_request, project_name):
            node  = event.get("node", "")
            phase = event.get("phase", "")
            label = PHASE_LABELS.get(phase, phase)

            # Notificar cambio de fase
            await _send(websocket, "phase", node=node, phase=phase, label=label)

            # Emitir contenido de cada fase
            if phase == "analyze" and event.get("analysis"):
                await _send(websocket, "analysis", content=event["analysis"])

            elif phase == "design" and event.get("design"):
                await _send(websocket, "design", content=event["design"])

            elif phase == "implement" and event.get("implementation_summary"):
                await _send(websocket, "implementation", content=event["implementation_summary"])

            elif phase == "test" and event.get("test_results"):
                passed = event.get("tests_passed", False)
                await _send(websocket, "tests",
                            content=event["test_results"],
                            passed=passed)

            elif phase == "fix" and event.get("implementation_summary"):
                await _send(websocket, "fix", content=event["implementation_summary"])

            elif phase == "commit" and event.get("commit_hash"):
                await _send(websocket, "commit", hash=event["commit_hash"])

            elif phase == "done" and event.get("result_summary"):
                await _send(websocket, "done", summary=event["result_summary"])

            elif phase == "error" and event.get("error"):
                await _send(websocket, "error", message=event["error"])
                return

        await _send(websocket, "finished")

    except WebSocketDisconnect:
        logger.info(f"WebSocket desconectado — usuario: {user}")
    except Exception as e:
        logger.exception(f"Error en WebSocket: {e}")
        await _send(websocket, "error", message=f"Error interno: {str(e)[:200]}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────

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
