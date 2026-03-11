"""
AI Engineering — Notificador Telegram (para el agente)

Envía mensajes, propuestas y alertas al Director via Telegram.
Se usa desde los nodos del grafo para comunicarse con el Director.
"""
import asyncio
import logging
from typing import Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USER

logger = logging.getLogger(__name__)

# Almacén en memoria de sesiones pendientes de decisión
# session_id -> asyncio.Future con la elección del Director
_pending_decisions: dict[str, asyncio.Future] = {}


def _bot() -> Bot:
    return Bot(token=TELEGRAM_BOT_TOKEN)


async def send_message(text: str, parse_mode: str = "Markdown") -> Optional[int]:
    """Envía un mensaje al Director. Retorna el message_id."""
    try:
        async with _bot() as bot:
            msg = await bot.send_message(
                chat_id=TELEGRAM_ALLOWED_USER,
                text=text,
                parse_mode=parse_mode,
            )
            return msg.message_id
    except Exception as e:
        logger.error(f"[notifier] Error enviando mensaje: {e}")
        return None


async def send_proposal_to_director(
    project: str,
    request: str,
    option_a: str,
    option_b: str,
    session_id: str,
) -> str:
    """Envía dos propuestas técnicas con botones de selección.

    Retorna el callback_data prefix para identificar la respuesta.
    """
    text = (
        f"*AI Engineering — Propuesta Técnica*\n"
        f"Proyecto: `{project}`\n"
        f"Sesión: `{session_id}`\n\n"
        f"*Instrucción:* {request}\n\n"
        f"*OPCIÓN A:*\n{option_a[:600]}\n\n"
        f"*OPCIÓN B:*\n{option_b[:600]}\n\n"
        f"_Elige una opción o envía /custom para especificar cambios._"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Opción A", callback_data=f"proposal:{session_id}:a"),
            InlineKeyboardButton("✅ Opción B", callback_data=f"proposal:{session_id}:b"),
        ],
        [
            InlineKeyboardButton("💬 Solicitar cambios", callback_data=f"proposal:{session_id}:custom"),
        ],
    ])

    try:
        async with _bot() as bot:
            msg = await bot.send_message(
                chat_id=TELEGRAM_ALLOWED_USER,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            return str(msg.message_id)
    except Exception as e:
        logger.error(f"[notifier] Error enviando propuesta: {e}")
        return ""


async def send_error_to_director(project: str, error: str, session_id: str) -> None:
    """Notifica al Director sobre un error que supera los 3 intentos."""
    text = (
        f"*AI Engineering — Error de Pipeline*\n"
        f"Proyecto: `{project}` | Sesión: `{session_id}`\n\n"
        f"El agente superó 3 intentos de corrección.\n\n"
        f"*Error:*\n```\n{error[:800]}\n```\n\n"
        f"_Usa /retomar para intervenir manualmente._"
    )
    await send_message(text)


async def send_completion_to_director(project: str, summary: str, session_id: str) -> None:
    """Notifica al Director sobre la finalización exitosa."""
    text = f"*AI Engineering — Completado*\n\n{summary}"
    await send_message(text)


async def request_vultr_authorization(
    project: str,
    action: str,
    details: str,
    session_id: str,
) -> str:
    """Solicita autorización del Director para crear/eliminar servidor Vultr.

    Retorna el message_id del mensaje de autorización.
    """
    text = (
        f"*AI Engineering — Autorización Requerida*\n"
        f"Proyecto: `{project}` | Sesión: `{session_id}`\n\n"
        f"*Acción:* {action}\n"
        f"*Detalles:*\n{details}\n\n"
        f"_Esta acción requiere tu autorización explícita._"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Autorizar", callback_data=f"auth:{session_id}:approve"),
            InlineKeyboardButton("Rechazar",  callback_data=f"auth:{session_id}:reject"),
        ],
    ])

    try:
        async with _bot() as bot:
            msg = await bot.send_message(
                chat_id=TELEGRAM_ALLOWED_USER,
                text=text,
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            return str(msg.message_id)
    except Exception as e:
        logger.error(f"[notifier] Error enviando solicitud de autorización: {e}")
        return ""


def register_pending_decision(session_id: str, future: asyncio.Future) -> None:
    """Registra un Future pendiente de decisión del Director."""
    _pending_decisions[session_id] = future


def resolve_decision(session_id: str, choice: str) -> bool:
    """Resuelve una decisión pendiente del Director."""
    future = _pending_decisions.pop(session_id, None)
    if future and not future.done():
        future.set_result(choice)
        return True
    return False
