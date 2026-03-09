"""
AI Engineering Platform — Entry Point

Modos de ejecución:
  python main.py              → Inicia la web UI en puerto 8080
  python main.py --agent "…" → Ejecuta un feature request via CLI
  python main.py --check      → Verifica la configuración del entorno
"""
import asyncio
import argparse
import logging
import sys

# Configurar logging primero
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/opt/ai_engineering/logs/ai_engineering.log"),
    ],
)
logger = logging.getLogger("ai_engineering")

sys.path.insert(0, "/opt/ai_engineering")
from config.settings import (
    WEB_HOST, WEB_PORT, LITELLM_PROXY_URL, LITELLM_MASTER_KEY,
    AGENT_MODEL, PROJECTS_DIR, VENV_PYTHON,
)


def run_check():
    """Verifica que el entorno esté correctamente configurado."""
    import httpx
    from pathlib import Path

    print("\n── Verificando AI Engineering Platform ──\n")

    checks = [
        ("Python venv",         Path(VENV_PYTHON).exists(),          VENV_PYTHON),
        ("Directorio projects", PROJECTS_DIR.exists(),               str(PROJECTS_DIR)),
        ("MCP: filesystem",     Path("/opt/ai_engineering/mcp_servers/filesystem_mcp.py").exists(), "OK"),
        ("MCP: bash",           Path("/opt/ai_engineering/mcp_servers/bash_mcp.py").exists(),       "OK"),
        ("MCP: git",            Path("/opt/ai_engineering/mcp_servers/git_mcp.py").exists(),        "OK"),
        ("MCP: pytest",         Path("/opt/ai_engineering/mcp_servers/pytest_mcp.py").exists(),     "OK"),
        ("Web templates",       Path("/opt/ai_engineering/web/templates/index.html").exists(),      "OK"),
    ]

    all_ok = True
    for name, ok, detail in checks:
        status = "✅" if ok else "❌"
        print(f"  {status} {name}: {detail}")
        if not ok:
            all_ok = False

    # Verificar LiteLLM Proxy
    print(f"\n  Verificando LiteLLM Proxy en {LITELLM_PROXY_URL}...")
    try:
        resp = httpx.get(f"{LITELLM_PROXY_URL}/health/liveliness", timeout=5)
        proxy_ok = resp.status_code == 200
        print(f"  {'✅' if proxy_ok else '❌'} LiteLLM Proxy: {'activo' if proxy_ok else 'no responde'}")
    except Exception as e:
        print(f"  ❌ LiteLLM Proxy: {e}")
        proxy_ok = False
        all_ok = False

    # Listar proyectos disponibles
    print(f"\n  Proyectos en {PROJECTS_DIR}:")
    if PROJECTS_DIR.exists():
        for p in PROJECTS_DIR.iterdir():
            if p.is_dir() and (p / ".git").exists():
                print(f"    • {p.name}")
    else:
        print("    (ninguno)")

    print()
    if all_ok:
        print("✅ Plataforma lista.\n")
        print(f"   Inicia con: python main.py")
        print(f"   Web UI:     http://{WEB_HOST}:{WEB_PORT}\n")
    else:
        print("❌ Hay problemas de configuración.\n")
        sys.exit(1)


async def run_agent_cli(feature_request: str, project: str):
    """Ejecuta un feature request desde la línea de comandos."""
    from agent.engineering_agent import stream_feature_request

    print(f"\n{'='*60}")
    print(f"  AI Engineering Agent")
    print(f"  Proyecto: {project}")
    print(f"  Feature:  {feature_request[:60]}...")
    print(f"{'='*60}\n")

    async for event in stream_feature_request(feature_request, project):
        node  = event.get("node", "?")
        phase = event.get("phase", "?")

        ICONS = {
            "setup": "⚙️ ", "analyze": "🔍", "design": "📐",
            "implement": "⚡", "test": "🧪", "fix": "🔧",
            "commit": "📦", "done": "✅", "error": "❌",
        }
        icon = ICONS.get(phase, "•")
        print(f"\n{icon}  [{node.upper()}] → {phase}")

        for key in ("analysis", "design", "implementation_summary", "test_results"):
            val = event.get(key, "")
            if val:
                preview = val[:200].replace("\n", " ")
                print(f"   {key}: {preview}{'…' if len(val) > 200 else ''}")

        if event.get("result_summary"):
            print(f"\n{event['result_summary']}")

        if phase == "error":
            print(f"\n❌ Error: {event.get('error', 'desconocido')}")
            sys.exit(1)


def run_web():
    """Inicia la interfaz web."""
    import uvicorn
    logger.info(f"Iniciando Web UI en http://{WEB_HOST}:{WEB_PORT}")
    uvicorn.run(
        "web.app:app",
        host=WEB_HOST,
        port=WEB_PORT,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Engineering Platform")
    parser.add_argument("--check",   action="store_true",  help="Verificar configuración")
    parser.add_argument("--agent",   type=str, default="", help="Ejecutar feature request via CLI")
    parser.add_argument("--project", type=str, default="tracker_master", help="Proyecto activo")
    args = parser.parse_args()

    if args.check:
        run_check()
    elif args.agent:
        asyncio.run(run_agent_cli(args.agent, args.project))
    else:
        run_web()
