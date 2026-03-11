"""
AI Engineering — Agente Principal de Ingeniería (v2)

Flujo completo:
  setup → analyze → propose → [Director elige] → design → implement
       → pipeline → (fix)*max3 → commit → pr → deploy → finalize → END

Uso:
    from agent.engineering_agent import run_feature_request, stream_feature_request

    result = await run_feature_request(
        project_name="tracker_master",
        feature_request="Agrega endpoint para listar usuarios con paginación",
    )
"""
import asyncio
import logging
import sys
import uuid
from functools import partial
from typing import AsyncIterator

sys.path.insert(0, "/opt/ai_engineering")

from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import StateGraph, START, END

from config.settings import VENV_PYTHON, MCP_SERVERS_DIR, PROJECTS_DIR
from agent.state import EngineeringState
from agent.nodes import (
    setup, analyze_codebase, propose_solutions,
    design_solution, implement_code, run_pipeline,
    fix_code, commit_push, create_pr, deploy_project,
    finalize, route_phase,
)
from agent.project_manager import get_project

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
#  MCP CONNECTIONS
# ─────────────────────────────────────────────────────────────

def _mcp_connections() -> dict:
    """Define las conexiones a los MCP servers via stdio."""
    py = VENV_PYTHON
    sd = str(MCP_SERVERS_DIR)
    return {
        "filesystem": {"transport": "stdio", "command": py, "args": [f"{sd}/filesystem_mcp.py"]},
        "bash":       {"transport": "stdio", "command": py, "args": [f"{sd}/bash_mcp.py"]},
        "git":        {"transport": "stdio", "command": py, "args": [f"{sd}/git_mcp.py"]},
        "pytest":     {"transport": "stdio", "command": py, "args": [f"{sd}/pytest_mcp.py"]},
        "vultr":      {"transport": "stdio", "command": py, "args": [f"{sd}/vultr_mcp.py"]},
    }


# ─────────────────────────────────────────────────────────────
#  GRAFO
# ─────────────────────────────────────────────────────────────

def _build_graph(tools: list):
    """Construye el StateGraph completo del agente v2."""
    builder = StateGraph(EngineeringState)

    # Nodos sin tools
    builder.add_node("setup",             setup)
    builder.add_node("propose_solutions", propose_solutions)
    builder.add_node("design_solution",   design_solution)
    builder.add_node("deploy_project",    deploy_project)
    builder.add_node("finalize",          finalize)

    # Nodos con tools
    builder.add_node("analyze_codebase", partial(analyze_codebase, tools=tools))
    builder.add_node("implement_code",   partial(implement_code,   tools=tools))
    builder.add_node("run_pipeline",     partial(run_pipeline,     tools=tools))
    builder.add_node("fix_code",         partial(fix_code,         tools=tools))
    builder.add_node("commit_push",      partial(commit_push,      tools=tools))
    builder.add_node("create_pr",        partial(create_pr,        tools=tools))

    # Edges fijos
    builder.add_edge(START,              "setup")
    builder.add_edge("analyze_codebase", "propose_solutions")
    builder.add_edge("design_solution",  "implement_code")
    builder.add_edge("implement_code",   "run_pipeline")
    builder.add_edge("commit_push",      "create_pr")
    builder.add_edge("create_pr",        "deploy_project")
    builder.add_edge("deploy_project",   "finalize")
    builder.add_edge("finalize",         END)

    # Edges condicionales
    builder.add_conditional_edges(
        "setup",
        route_phase,
        {"analyze": "analyze_codebase", "error": "finalize"},
    )

    # Después de propuestas: esperar decisión del Director
    # En modo autónomo (CI/API) se usa proposal_a directamente
    builder.add_conditional_edges(
        "propose_solutions",
        route_phase,
        {
            "await_decision": "design_solution",  # el handler externo debe setear chosen_proposal
            "design": "design_solution",
            "error": "finalize",
        },
    )

    builder.add_conditional_edges(
        "run_pipeline",
        route_phase,
        {"commit": "commit_push", "fix": "fix_code", "error": "finalize"},
    )

    builder.add_conditional_edges(
        "fix_code",
        route_phase,
        {"pipeline": "run_pipeline", "error": "finalize"},
    )

    return builder.compile()


# ─────────────────────────────────────────────────────────────
#  ENTRY POINTS
# ─────────────────────────────────────────────────────────────

async def run_feature_request(
    feature_request: str,
    project_name: str = "tracker_master",
    project_path: str = "",
    chosen_proposal: str = "a",  # auto-elegir propuesta A en modo autónomo
    skip_proposal: bool = False,  # saltarse la propuesta y ir directo a diseño
) -> dict:
    """
    Ejecuta un feature request de forma autónoma.

    En modo skip_proposal=True salta la fase de propuestas (útil para tareas simples).
    En modo normal, genera propuestas y espera decisión del Director.
    """
    if not project_path:
        project_path = str(PROJECTS_DIR / project_name)

    project_data = get_project(project_name) or {}

    initial_state: EngineeringState = {
        "feature_request": feature_request,
        "project_name": project_name,
        "project_path": project_path,
        "project_data": project_data,
        "session_id": str(uuid.uuid4())[:8],
        "messages": [],
        "phase": "setup",
        "analysis": "",
        "proposal_a": "",
        "proposal_b": "",
        "chosen_proposal": chosen_proposal,
        "decision_message_id": "",
        "branch_name": "",
        "design": "",
        "implementation_summary": "",
        "pipeline_results": {},
        "tests_passed": False,
        "test_results": "",
        "retry_count": 0,
        "max_retries": 3,
        "pr_url": "",
        "commit_hash": "",
        "deploy_result": {},
        "error": None,
        "requires_director_auth": False,
        "auth_reason": "",
        "result_summary": "",
        "notifications_sent": [],
    }

    logger.info(f"Iniciando feature request: '{feature_request[:80]}'")
    logger.info(f"Proyecto: {project_name} en {project_path}")

    mcp_client = MultiServerMCPClient(_mcp_connections())
    tools = await mcp_client.get_tools()
    logger.info(f"MCP tools: {[t.name for t in tools]}")

    graph = _build_graph(tools)
    final_state = await graph.ainvoke(initial_state)

    logger.info(f"Feature request completado — fase: {final_state.get('phase')}")
    return final_state


async def stream_feature_request(
    feature_request: str,
    project_name: str = "tracker_master",
    project_path: str = "",
    chosen_proposal: str = "a",
) -> AsyncIterator[dict]:
    """
    Versión streaming de run_feature_request.
    Emite eventos de cada nodo conforme avanza el grafo.
    """
    if not project_path:
        project_path = str(PROJECTS_DIR / project_name)

    project_data = get_project(project_name) or {}

    initial_state: EngineeringState = {
        "feature_request": feature_request,
        "project_name": project_name,
        "project_path": project_path,
        "project_data": project_data,
        "session_id": str(uuid.uuid4())[:8],
        "messages": [],
        "phase": "setup",
        "analysis": "",
        "proposal_a": "",
        "proposal_b": "",
        "chosen_proposal": chosen_proposal,
        "decision_message_id": "",
        "branch_name": "",
        "design": "",
        "implementation_summary": "",
        "pipeline_results": {},
        "tests_passed": False,
        "test_results": "",
        "retry_count": 0,
        "max_retries": 3,
        "pr_url": "",
        "commit_hash": "",
        "deploy_result": {},
        "error": None,
        "requires_director_auth": False,
        "auth_reason": "",
        "result_summary": "",
        "notifications_sent": [],
    }

    mcp_client = MultiServerMCPClient(_mcp_connections())
    tools = await mcp_client.get_tools()
    graph = _build_graph(tools)

    async for event in graph.astream(initial_state, stream_mode="updates"):
        for node_name, state_updates in event.items():
            yield {
                "node": node_name,
                "phase": state_updates.get("phase", ""),
                **{k: v for k, v in state_updates.items() if k not in ("messages", "project_data")},
            }
