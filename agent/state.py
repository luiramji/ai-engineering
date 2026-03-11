"""
AI Engineering — Estado del Grafo LangGraph (v2)

Estado completo del agente de ingeniería autónoma.
Soporta el flujo completo: análisis → propuestas → implementación → pipeline → PR → deploy.
"""
from typing import Annotated, Optional, Any
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages


class EngineeringState(TypedDict):
    """Estado completo del agente de ingeniería."""

    # ── Input ────────────────────────────────────────────────
    feature_request: str           # Instrucción en lenguaje natural
    project_name: str              # ID del proyecto (e.g. 'tracker_master')
    project_path: str              # Ruta absoluta al codebase del proyecto

    # ── Contexto de proyecto ──────────────────────────────────
    project_data: dict             # Datos del proyecto desde projects.json
    session_id: str                # ID único de la sesión (para tracking)

    # ── Conversación con el LLM ──────────────────────────────
    messages: Annotated[list, add_messages]

    # ── Fase actual del flujo ────────────────────────────────
    # analyze | propose | await_decision | implement | pipeline | fix | pr | deploy | done | error
    phase: str

    # ── Análisis ─────────────────────────────────────────────
    analysis: str                  # Análisis del codebase

    # ── Propuestas (dos opciones técnicas) ───────────────────
    proposal_a: str                # Opción técnica A
    proposal_b: str                # Opción técnica B
    chosen_proposal: str           # "a" | "b" | custom text después de decisión del Director
    decision_message_id: str       # ID del mensaje Telegram con botones de selección

    # ── Implementación ───────────────────────────────────────
    branch_name: str               # Rama de feature (ai/feature-name)
    design: str                    # Plan técnico detallado basado en la propuesta elegida
    implementation_summary: str    # Qué se implementó

    # ── Pipeline de calidad ──────────────────────────────────
    pipeline_results: dict         # Resultado de pytest + semgrep + bandit
    tests_passed: bool             # True si todo el pipeline pasó
    test_results: str              # Output del pipeline formateado
    retry_count: int               # Intentos de corrección (max 3)
    max_retries: int               # Límite (default: 3)

    # ── Pull Request ─────────────────────────────────────────
    pr_url: str                    # URL del PR creado en GitHub
    commit_hash: str               # Hash del commit final

    # ── Deploy ───────────────────────────────────────────────
    deploy_result: dict            # Resultado del deploy SSH

    # ── Control de flujo ────────────────────────────────────
    error: Optional[str]           # Error si el agente falla
    requires_director_auth: bool   # True si necesita autorización pendiente
    auth_reason: str               # Por qué necesita autorización

    # ── Output final ────────────────────────────────────────
    result_summary: str            # Resumen final para el usuario
    notifications_sent: list       # Lista de notificaciones enviadas
