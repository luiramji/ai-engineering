"""
AI Engineering Platform — Entry Point (v2)

Modos de ejecución:
  python main.py              → Inicia Web UI + Telegram Bot
  python main.py --web        → Solo Web UI en puerto 8080
  python main.py --bot        → Solo Telegram Bot
  python main.py --check      → Verifica configuración del entorno
  python main.py --monitor    → Monitoreo de servidores (daemon)
"""
import asyncio
import argparse
import logging
import sys

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
    WEB_HOST, WEB_PORT, LITELLM_PROXY_URL,
    VENV_PYTHON, PROJECTS_DIR, DATA_DIR,
)


def run_check():
    """Verifica que el entorno esté correctamente configurado."""
    import httpx
    from pathlib import Path

    print("\n── Verificando AI Engineering Platform v2 ──\n")

    checks = [
        ("Python venv",          Path(VENV_PYTHON).exists(),                          VENV_PYTHON),
        ("Directorio projects",  PROJECTS_DIR.exists(),                               str(PROJECTS_DIR)),
        ("Directorio data",      DATA_DIR.exists(),                                   str(DATA_DIR)),
        ("projects.json",        (DATA_DIR / "projects.json").exists(),               "OK"),
        ("MCP: filesystem",      Path("/opt/ai_engineering/mcp_servers/filesystem_mcp.py").exists(), "OK"),
        ("MCP: bash",            Path("/opt/ai_engineering/mcp_servers/bash_mcp.py").exists(),       "OK"),
        ("MCP: git",             Path("/opt/ai_engineering/mcp_servers/git_mcp.py").exists(),        "OK"),
        ("MCP: vultr",           Path("/opt/ai_engineering/mcp_servers/vultr_mcp.py").exists(),      "OK"),
        ("Telegram bot",         Path("/opt/ai_engineering/tg_bot/bot.py").exists(),               "OK"),
        ("Web templates",        Path("/opt/ai_engineering/web/templates/index.html").exists(),       "OK"),
        ("Secrets vault",        Path("/opt/ai_engineering/agent/vault.py").exists(),                "OK"),
        ("Pipeline quality",     Path("/opt/ai_engineering/pipeline/quality.py").exists(),           "OK"),
    ]

    all_ok = True
    for name, ok, detail in checks:
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] {name}: {detail}")
        if not ok:
            all_ok = False

    print(f"\n  Verificando LiteLLM Proxy en {LITELLM_PROXY_URL}...")
    try:
        resp = httpx.get(f"{LITELLM_PROXY_URL}/health/liveliness", timeout=5)
        proxy_ok = resp.status_code == 200
        print(f"  [{'OK' if proxy_ok else 'FAIL'}] LiteLLM Proxy: {'activo' if proxy_ok else 'no responde'}")
        if not proxy_ok:
            all_ok = False
    except Exception as e:
        print(f"  [FAIL] LiteLLM Proxy: {e}")
        all_ok = False

    print(f"\n  Proyectos en {PROJECTS_DIR}:")
    if PROJECTS_DIR.exists():
        for p in PROJECTS_DIR.iterdir():
            if p.is_dir() and (p / ".git").exists():
                print(f"    - {p.name}")
    else:
        print("    (ninguno)")

    print()
    if all_ok:
        print("OK — Plataforma lista.\n")
        print(f"   Inicia con: python main.py")
        print(f"   Web UI:     http://{WEB_HOST}:{WEB_PORT}\n")
    else:
        print("FAIL — Hay problemas de configuración.\n")
        sys.exit(1)


async def run_monitor_daemon(interval_seconds: int = 300):
    """Monitorea servidores de producción y notifica al Director si hay caidas."""
    import json
    from pathlib import Path
    from agent.deploy import check_service_health
    from tg_bot.notifier import send_message

    logger.info(f"[monitor] Daemon iniciado — intervalo: {interval_seconds}s")

    while True:
        servers_file = DATA_DIR / "servers.json"
        if not servers_file.exists():
            await asyncio.sleep(interval_seconds)
            continue

        try:
            servers = json.loads(servers_file.read_text())
        except Exception as e:
            logger.error(f"[monitor] Error leyendo servers.json: {e}")
            await asyncio.sleep(interval_seconds)
            continue

        for srv in servers:
            ip       = srv.get("ip", "?")
            user     = srv.get("user", "root")
            key      = srv.get("ssh_key", "/home/aidev/.ssh/id_ed25519")
            services = srv.get("services", [])

            for svc in services:
                try:
                    result = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: check_service_health(ip, user, key, svc)
                    )
                    if not result["active"]:
                        logger.warning(f"[monitor] SERVICIO CAIDO: {svc} en {ip}")
                        await send_message(
                            f"*ALERTA — Servicio caido*\n\n"
                            f"Servidor: `{ip}`\n"
                            f"Servicio: `{svc}`\n"
                            f"Estado: {result['status_output']}\n\n"
                            f"_Usa /monitor para verificar y /reparar para intervenir._"
                        )
                    else:
                        logger.debug(f"[monitor] OK: {svc} en {ip}")
                except Exception as e:
                    logger.error(f"[monitor] Error verificando {svc}@{ip}: {e}")

        await asyncio.sleep(interval_seconds)


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


def run_bot():
    """Inicia el bot de Telegram."""
    from tg_bot.bot import run_bot as _run_bot
    logger.info("Iniciando Telegram Bot (AI Engineering)...")
    _run_bot()


async def run_all():
    """Inicia Web UI + Telegram Bot + Monitor en paralelo."""
    import uvicorn
    import threading

    logger.info("Iniciando AI Engineering Platform v2")

    # Web UI en thread separado
    def _web():
        uvicorn.run(
            "web.app:app",
            host=WEB_HOST,
            port=WEB_PORT,
            reload=False,
            log_level="warning",
        )

    web_thread = threading.Thread(target=_web, daemon=True)
    web_thread.start()
    logger.info(f"Web UI iniciada en http://{WEB_HOST}:{WEB_PORT}")

    # Monitor daemon
    monitor_task = asyncio.create_task(run_monitor_daemon(300))

    # Telegram Bot (blocking - debe ir en el main thread del event loop)
    try:
        from tg_bot.bot import create_application
        app = create_application()

        # No usar run_polling (bloquea) — usar async
        await app.initialize()
        await app.start()
        await app.updater.start_polling(allowed_updates=["message", "callback_query"])
        logger.info("Telegram Bot iniciado (polling)")

        # Mantener vivo
        import signal
        stop_event = asyncio.Event()

        def _handle_signal(*_):
            stop_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_event_loop().add_signal_handler(sig, _handle_signal)

        await stop_event.wait()

    except Exception as e:
        logger.error(f"Error en Telegram Bot: {e}")
    finally:
        monitor_task.cancel()
        try:
            await app.updater.stop()
            await app.stop()
            await app.shutdown()
        except Exception:
            pass
        logger.info("Plataforma detenida.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Engineering Platform v2")
    parser.add_argument("--check",   action="store_true", help="Verificar configuración")
    parser.add_argument("--web",     action="store_true", help="Solo Web UI")
    parser.add_argument("--bot",     action="store_true", help="Solo Telegram Bot")
    parser.add_argument("--monitor", action="store_true", help="Monitor de servidores")
    args = parser.parse_args()

    if args.check:
        run_check()
    elif args.web:
        run_web()
    elif args.bot:
        run_bot()
    elif args.monitor:
        asyncio.run(run_monitor_daemon(300))
    else:
        asyncio.run(run_all())
