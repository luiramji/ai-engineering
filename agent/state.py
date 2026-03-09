"""
AI Engineering — Estado del Grafo

Cada campo es leído y escrito por los nodos del grafo.
El campo `messages` acumula el historial de conversación con el LLM.
"""
from typing import Annotated, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class EngineeringState(TypedDict):
    """Estado completo del agente de ingeniería."""

    # ── Input ────────────────────────────────────────────────
    feature_request: str           # Feature request en lenguaje natural
    project_name: str              # Nombre del proyecto activo (e.g. 'tracker_master')
    project_path: str              # Ruta absoluta al proyecto

    # ── Conversación con el LLM ──────────────────────────────
    # add_messages acumula el historial — no reemplaza
    messages: Annotated[list, add_messages]

    # ── Fase actual del flujo ────────────────────────────────
    # Valores: analyze | design | implement | test | commit | done | error
    phase: str

    # ── Resultados de cada fase ──────────────────────────────
    analysis: str                  # Resumen del análisis del codebase
    design: str                    # Diseño de la solución (plan técnico)
    implementation_summary: str    # Qué se implementó
    test_results: str              # Salida de pytest
    tests_passed: bool             # True si todos los tests pasaron
    commit_hash: str               # Hash del commit final

    # ── Control de flujo ────────────────────────────────────
    retry_count: int               # Reintentos de implementación tras test fallidos
    max_retries: int               # Límite de reintentos (default: 2)
    error: Optional[str]           # Descripción del error si el agente falla

    # ── Output final ────────────────────────────────────────
    result_summary: str            # Resumen final para el usuario
