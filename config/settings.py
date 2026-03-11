"""
AI Engineering Platform — Configuración Central
"""
import os
from pathlib import Path
from dotenv import load_dotenv

_ENV_FILE = Path(__file__).parent / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE)
else:
    load_dotenv()

ROOT_DIR        = Path("/opt/ai_engineering")
PROJECTS_DIR    = ROOT_DIR / "projects"
MCP_SERVERS_DIR = ROOT_DIR / "mcp_servers"
LOGS_DIR        = ROOT_DIR / "logs"
DATA_DIR        = ROOT_DIR / "data"
VENV_PYTHON     = str(ROOT_DIR / "venv" / "bin" / "python")

# ── LiteLLM Proxy ────────────────────────────────────────────
LITELLM_PROXY_URL  = os.getenv("LITELLM_PROXY_URL",  "http://localhost:4000")
LITELLM_MASTER_KEY = os.getenv("LITELLM_MASTER_KEY", "sk-tracker-master-local")

# ── Modelos disponibles via proxy ────────────────────────────
AGENT_MODEL    = os.getenv("AGENT_MODEL",    "claude-sonnet-4-6")   # implementación/diseño
FAST_MODEL     = os.getenv("FAST_MODEL",     "claude-haiku-4-5")    # análisis rápido
FALLBACK_MODEL = os.getenv("FALLBACK_MODEL", "gpt-4o-mini")         # fallback / tareas simples
REVIEW_MODEL   = os.getenv("REVIEW_MODEL",   "gpt-4o")              # revisión de código
LONG_CTX_MODEL = os.getenv("LONG_CTX_MODEL", "gemini-2.5-pro")      # contexto largo

# ── Web UI ───────────────────────────────────────────────────
WEB_HOST     = os.getenv("WEB_HOST",     "0.0.0.0")
WEB_PORT     = int(os.getenv("WEB_PORT", "8080"))
WEB_USER     = os.getenv("WEB_USER",     "admin")
WEB_PASSWORD = os.getenv("WEB_PASSWORD", "ai-engineering-2026")
SECRET_KEY   = os.getenv("SECRET_KEY",   "change-me-in-production-secret-key-32chars")

# ── Telegram ─────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN    = os.getenv("TELEGRAM_BOT_TOKEN_AGENT", "8621904822:AAHPUyl6z91BfICzeN5Pw-OhZFo55072i-A")
TELEGRAM_ALLOWED_USER = int(os.getenv("TELEGRAM_ALLOWED_USER", "5238148831"))

# ── Git ──────────────────────────────────────────────────────
GIT_USER_NAME  = os.getenv("GIT_USER_NAME",  "AI Engineering Bot")
GIT_USER_EMAIL = os.getenv("GIT_USER_EMAIL", "ai-bot@ai-engineering.local")
GITHUB_TOKEN   = os.getenv("GITHUB_TOKEN",   "")

# ── Infraestructura ──────────────────────────────────────────
VULTR_API_KEY    = os.getenv("VULTR_API_KEY", "VYFCBC26ATANVYJIS5BECXO2D4FB73VMAZ5Q")
SERVER1_HOST     = os.getenv("SERVER1_HOST",  "149.28.209.93")
SERVER1_USER     = os.getenv("SERVER1_USER",  "tracker")
SERVER1_SSH_KEY  = os.getenv("SERVER1_SSH_KEY", "/home/aidev/.ssh/id_ed25519")

# ── Secrets vault ────────────────────────────────────────────
SECRETS_FILE = DATA_DIR / "secrets.enc"

# ── Pipeline ─────────────────────────────────────────────────
PIPELINE_MAX_RETRIES = int(os.getenv("PIPELINE_MAX_RETRIES", "3"))

# ── Seguridad bash ───────────────────────────────────────────
BASH_TIMEOUT_SECONDS  = int(os.getenv("BASH_TIMEOUT", "60"))
BASH_MAX_OUTPUT_CHARS = 20_000
