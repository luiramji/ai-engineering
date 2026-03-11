"""
AI Engineering — Bot de Telegram (canal principal del Director)

Handlers:
  /start          — bienvenida
  /proyectos      — lista proyectos
  /estado         — estado de la plataforma
  /costos         — resumen de costos LLM
  /secret PROJ NAME VALUE — almacenar secret encriptado
  /monitor        — verificar salud de servidores
  Mensajes libres — ejecutar feature request en proyecto activo
  Callbacks de botones — elección de propuesta / autorización Vultr
"""
import asyncio
import logging
import sys

sys.path.insert(0, "/opt/ai_engineering")

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters,
)

from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USER
from agent.vault import store_secret, list_secrets
from agent.cost_tracker import get_summary as get_cost_summary
from agent.project_manager import get_all as get_all_projects, get_project
from tg_bot.notifier import resolve_decision

logger = logging.getLogger(__name__)

# Proyecto activo por defecto
_active_project: str = "tracker_master"
# Sesiones activas {session_id: task}
_active_sessions: dict[str, asyncio.Task] = {}


# ─────────────────────────────────────────────────────────────
#  GUARD: solo responde al Director
# ─────────────────────────────────────────────────────────────

def _is_director(update: Update) -> bool:
    return update.effective_user and update.effective_user.id == TELEGRAM_ALLOWED_USER


async def _guard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if not _is_director(update):
        logger.warning(f"Mensaje rechazado de user_id={update.effective_user.id if update.effective_user else '?'}")
        return False
    return True


# ─────────────────────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────────────────────

async def _reply(update: Update, text: str, parse_mode: str = "Markdown") -> None:
    try:
        await update.effective_message.reply_text(text, parse_mode=parse_mode)
    except Exception as e:
        logger.error(f"Error enviando respuesta: {e}")


# ─────────────────────────────────────────────────────────────
#  COMMANDS
# ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    await _reply(update, (
        "*AI Engineering Platform*\n\n"
        "Canal principal del Director.\n\n"
        "*Comandos:*\n"
        "/proyectos — lista proyectos\n"
        "/proyecto NOMBRE — cambiar proyecto activo\n"
        "/estado — estado de la plataforma\n"
        "/costos — resumen de costos LLM\n"
        "/monitor — salud de servidores\n"
        "/secret PROJ NOMBRE VALOR — guardar secret\n"
        "/cancelar — cancelar sesión activa\n\n"
        "_Envía cualquier texto para ejecutar como feature request._"
    ))


async def cmd_proyectos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    projects = get_all_projects()
    if not projects:
        await _reply(update, "No hay proyectos registrados.")
        return

    lines = ["*Proyectos registrados:*\n"]
    for p in projects:
        status = "Activo" if p.get("id") == _active_project else ""
        lines.append(f"• `{p['id']}` — {p['name']} {status}")
        if p.get("memory", {}).get("last_session"):
            ls = p["memory"]["last_session"]
            lines.append(f"  Última sesión: {ls.get('date', '')[:10]}")

    await _reply(update, "\n".join(lines))


async def cmd_proyecto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global _active_project
    if not await _guard(update, context):
        return
    if not context.args:
        await _reply(update, f"Proyecto activo: `{_active_project}`")
        return
    name = context.args[0]
    project = get_project(name)
    if not project:
        await _reply(update, f"Proyecto `{name}` no encontrado.")
        return
    _active_project = name
    await _reply(update, f"Proyecto activo cambiado a: `{name}`")


async def cmd_estado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    import httpx
    from config.settings import LITELLM_PROXY_URL

    # Check LiteLLM
    try:
        resp = httpx.get(f"{LITELLM_PROXY_URL}/health/liveliness", timeout=3)
        litellm_ok = resp.status_code == 200
    except Exception:
        litellm_ok = False

    sessions = len(_active_sessions)
    costs = get_cost_summary()

    await _reply(update, (
        f"*Estado de la Plataforma*\n\n"
        f"LiteLLM Proxy: {'OK' if litellm_ok else 'DOWN'}\n"
        f"Proyecto activo: `{_active_project}`\n"
        f"Sesiones activas: {sessions}\n"
        f"Costo total LLM: ${costs['total_usd']:.4f}\n"
    ))


async def cmd_costos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    summary = get_cost_summary()

    lines = [f"*Costos LLM — Total: ${summary['total_usd']:.4f}*\n"]
    lines.append("*Por modelo:*")
    for model, cost in sorted(summary["by_model"].items(), key=lambda x: -x[1]):
        lines.append(f"  {model}: ${cost:.4f}")
    lines.append("\n*Por proyecto:*")
    for project, cost in sorted(summary["by_project"].items(), key=lambda x: -x[1]):
        lines.append(f"  {project}: ${cost:.4f}")

    await _reply(update, "\n".join(lines))


async def cmd_secret(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return

    args = context.args
    if len(args) < 3:
        await _reply(update, "Uso: `/secret PROYECTO NOMBRE VALOR`")
        return

    project = args[0]
    name    = args[1]
    value   = " ".join(args[2:])

    try:
        store_secret(project, name, value)
        # Eliminar el mensaje con el secret por seguridad
        try:
            await update.effective_message.delete()
        except Exception:
            pass
        await _reply(update, f"Secret `{name}` guardado para proyecto `{project}`.")
    except Exception as e:
        await _reply(update, f"Error guardando secret: {e}")


async def cmd_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    import json
    from pathlib import Path
    from agent.deploy import check_service_health

    servers_file = Path("/opt/ai_engineering/data/servers.json")
    if not servers_file.exists():
        await _reply(update, "No hay servidores registrados.")
        return

    servers = json.loads(servers_file.read_text())
    lines = ["*Monitor de Servidores*\n"]

    for srv in servers:
        ip  = srv.get("ip", "?")
        user = srv.get("user", "root")
        key  = srv.get("ssh_key", "/home/aidev/.ssh/id_ed25519")
        services = srv.get("services", [])

        lines.append(f"*{ip}* ({srv.get('purpose', '?')})")
        for svc in services:
            try:
                result = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: check_service_health(ip, user, key, svc)
                )
                status = "OK" if result["active"] else "DOWN"
                lines.append(f"  {svc}: {status}")
            except Exception as e:
                lines.append(f"  {svc}: ERROR ({e})")

    await _reply(update, "\n".join(lines))


async def cmd_cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return
    if not _active_sessions:
        await _reply(update, "No hay sesiones activas.")
        return
    for sid, task in list(_active_sessions.items()):
        task.cancel()
    _active_sessions.clear()
    await _reply(update, "Sesión(es) cancelada(s).")


# ─────────────────────────────────────────────────────────────
#  FEATURE REQUEST — mensaje libre
# ─────────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await _guard(update, context):
        return

    text = update.effective_message.text or ""
    if not text.strip():
        return

    project = get_project(_active_project)
    if not project:
        await _reply(update, f"Proyecto `{_active_project}` no encontrado. Registra el proyecto primero.")
        return

    await _reply(update, (
        f"Recibido. Iniciando agente para: `{_active_project}`\n\n"
        f"_Te enviaré propuestas técnicas en breve..._"
    ))

    async def _run_agent():
        try:
            from agent.engineering_agent import run_feature_request
            result = await run_feature_request(
                feature_request=text,
                project_name=_active_project,
            )
            summary = result.get("result_summary", "Sin resumen")
            await _reply(update, f"*Resultado:*\n{summary}")
        except asyncio.CancelledError:
            await _reply(update, "Sesión cancelada.")
        except Exception as e:
            logger.exception(f"Error en agente: {e}")
            await _reply(update, f"Error en agente: {str(e)[:300]}")

    session_id = f"tg_{update.effective_message.message_id}"
    task = asyncio.create_task(_run_agent())
    _active_sessions[session_id] = task

    def _cleanup(fut):
        _active_sessions.pop(session_id, None)

    task.add_done_callback(_cleanup)


# ─────────────────────────────────────────────────────────────
#  CALLBACK QUERY — botones de propuesta / autorización
# ─────────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_director(update):
        await update.callback_query.answer("No autorizado.")
        return

    query = update.callback_query
    await query.answer()

    data = query.data or ""
    parts = data.split(":")

    if len(parts) < 3:
        return

    action     = parts[0]
    session_id = parts[1]
    choice     = parts[2]

    if action == "proposal":
        resolved = resolve_decision(session_id, choice)
        if resolved:
            label = {"a": "Opción A", "b": "Opción B", "custom": "Personalizada"}.get(choice, choice)
            await query.edit_message_text(
                f"{query.message.text}\n\n*Elección: {label}*",
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text(
                f"{query.message.text}\n\n_(sin sesión activa para esta elección)_",
                parse_mode="Markdown",
            )

    elif action == "auth":
        approved = choice == "approve"
        resolve_decision(session_id, "DIRECTOR_APPROVED" if approved else "REJECTED")
        status = "Autorizado" if approved else "Rechazado"
        await query.edit_message_text(
            f"{query.message.text}\n\n*{status}*",
            parse_mode="Markdown",
        )


# ─────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────

def create_application() -> Application:
    """Crea y configura la aplicación del bot."""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("proyectos", cmd_proyectos))
    app.add_handler(CommandHandler("proyecto",  cmd_proyecto))
    app.add_handler(CommandHandler("estado",    cmd_estado))
    app.add_handler(CommandHandler("costos",    cmd_costos))
    app.add_handler(CommandHandler("secret",    cmd_secret))
    app.add_handler(CommandHandler("monitor",   cmd_monitor))
    app.add_handler(CommandHandler("cancelar",  cmd_cancelar))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))

    return app


def run_bot() -> None:
    """Inicia el bot en modo polling."""
    logger.info("Iniciando bot de Telegram (AI Engineering)...")
    app = create_application()
    app.run_polling(allowed_updates=["message", "callback_query"])
