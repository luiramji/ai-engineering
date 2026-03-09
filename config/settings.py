"""
AI Engineering Platform — Configuración Central
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Carga .env desde config/ si existe
_ENV_FILE = Path(__file__).parent / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE)
else:
    load_dotenv()  # fallback: buscar .env en cwd

ROOT_DIR        = Path("/opt/ai_engineering")
PROJECTS_DIR    = ROOT_DIR / "projects"
MCP_SERVERS_DIR = ROOT_DIR / "mcp_servers"
LOGS_DIR        = ROOT_DIR / "logs"
VENV_PYTHON     = str(ROOT_DIR / "venv" / "bin" / "python")

# ── LiteLLM Proxy ────────────────────────────────────────────
LITELLM_PROXY_URL  = os.getenv("LITELLM_PROXY_URL",  "http://localhost:4000")
LITELLM_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY", "sk-tracker-master-local")

# ── Modelos disponibles via proxy ────────────────────────────
AGENT_MODEL    = os.getenv("AGENT_MODEL",    "claude-sonnet-4-6")   # implementación
FAST_MODEL     = os.getenv("FAST_MODEL",     "claude-haiku-4-5")    # análisis rápido
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "gpt-4o-mini")         # fallback

# ── Web UI ───────────────────────────────────────────────────
WEB_HOST     = os.getenv("WEB_HOST",     "0.0.0.0")
WEB_PORT     = int(os.getenv("WEB_PORT", "8080"))
WEB_USER     = os.getenv("WEB_USER",     "admin")
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "ai-engineering-2026")
SECRET_KEY   = os.getenv("SECRET_KEY",   "change-me-in-production-secret-key-32chars")

# ── Git ──────────────────────────────────────────────────────
GIT_USER_NAME  = os.getenv("GIT_USER_NAME",  "AI Engineering Bot")
GIT_USER_EMAIL = os.getenv("GIT_USER_EMAIL", "ai-bot@ai-engineering.local")
GITHUB_TOKEN   = os.getenv("GITHUB_TOKEN",   "")

# ── Seguridad bash ───────────────────────────────────────────
BASH_TIMEOUT_SECONDS  = int(os.getenv("BASH_TIMEOUT", "60"))
BASH_MAX_OUTPUT_CHARS = 20_000
