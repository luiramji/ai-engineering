"""
AI Engineering — Agente Principal de Ingeniería

LangGraph agent que recibe feature requests en lenguaje natural
y los ejecuta de forma autónoma:
  setup → analyze → design → implement → test → (fix →)* commit → done

Uso:
    from agent.engineering_agent import run_feature_request

    result = await run_feature_request(
        project_name="tracker_master",
        feature_request="Agrega validación de email en el registro de usuarios",
    )
    print(result["result_summary"])
"""
import asyncio
import logging
import sys
from functools import partial
from typing import AsyncIterator

sys.path.insert(0, "/opt/ai_engineering")

from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import StateGraph, START, END

from config.settings import VENV_PYTHON, MCP_SERVERS_DIR, PROJECTS_DIR
from agent.state import EngineeringState
from agent.nodes import (
    setup, analyze_codebase, design_solution,
    implement_code, run_tests, fix_code, commit_push,
    finalize, route_phase,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
#  CONFIGURACIÓN MCP SERVERS
# ─────────────────────────────────────────────────────────────

def _mcp_connections() -> dict:
    """Define las conexiones a los cuatro MCP servers via stdio."""
    py = VENV_PYTHON
    servers_dir = str(MCP_SERVERS_DIR)
    return {
        "filesystem": {
            "transport": "stdio",
            "command": py,
            "args": [f"{servers_dir}/filesystem_mcp.py"],
        },
        "bash": {
            "transport": "stdio",
            "command": py,
            "args": [f"{servers_dir}/bash_mcp.py"],
        },
        "git": {
            "transport": "stdio",
            "command": py,
            "args": [f"{servers_dir}/git_mcp.py"],
        },
        "pytest": {
            "transport": "stdio",
            "command": py,
            "args": [f"{servers_dir}/pytest_mcp.py"],
        },
    }


# ─────────────────────────────────────────────────────────────
#  CONSTRUCCIÓN DEL GRAFO
# ─────────────────────────────────────────────────────────────

def _build_graph(tools: list):
    """
    Construye el StateGraph con todos los nodos y edges.
    Los nodos que necesitan herramientas reciben `tools` via partial.
    """
    builder = StateGraph(EngineeringState)

    # Nodos que NO necesitan tools
    builder.add_node("setup",          setup)
    builder.add_node("design_solution", design_solution)
    builder.add_node("finalize",        finalize)

    # Nodos que necesitan tools (inyectados via partial)
    builder.add_node("analyze_codebase", partial(analyze_codebase, tools=tools))
    builder.add_node("implement_code",   partial(implement_code,   tools=tools))
    builder.add_node("run_tests",        partial(run_tests,        tools=tools))
    builder.add_node("fix_code",         partial(fix_code,         tools=tools))
    builder.add_node("commit_push",      partial(commit_push,      tools=tools))

    # ── Edges fijos ──────────────────────────────────────────
    builder.add_edge(START,             "setup")
    builder.add_edge("analyze_codebase", "design_solution")
    builder.add_edge("design_solution",  "implement_code")
    builder.add_edge("implement_code",   "run_tests")
    builder.add_edge("commit_push",      "finalize")
    builder.add_edge("finalize",         END)

    # ── Edges condicionales ──────────────────────────────────
    # setup → analyze | finalize (si error)
    builder.add_conditional_edges(
        "setup",
        route_phase,
        {"analyze": "analyze_codebase", "error": "finalize"},
    )

    # run_tests → commit | fix | finalize (si error)
    builder.add_conditional_edges(
        "run_tests",
        route_phase,
        {
            "commit": "commit_push",
            "fix":    "fix_code",
            "error":  "finalize",
        },
    )

    # fix_code → test (reintentar) | error → finalize
    builder.add_conditional_edges(
        "fix_code",
        route_phase,
        {"test": "run_tests", "error": "finalize"},
    )

    return builder.compile()


# ─────────────────────────────────────────────────────────────
#  ENTRY POINT PRINCIPAL
# ─────────────────────────────────────────────────────────────

async def run_feature_request(
    feature_request: str,
    project_name: str = "tracker_master",
    project_path: str = "",
) -> dict:
    """
    Ejecuta un feature request de forma autónoma.

    Args:
        feature_request: Descripción en lenguaje natural de lo que se debe implementar.
        project_name: Nombre del proyecto (debe existir en /opt/ai_engineering/projects/).
        project_path: Ruta absoluta al proyecto. Si vacío, se infiere de project_name.

    Returns:
        Estado final del grafo con `result_summary` y todos los detalles.
    """
    if not project_path:
        project_path = str(PROJECTS_DIR / project_name)

    initial_state: EngineeringState = {
        "feature_request": feature_request,
        "project_name": project_name,
        "project_path": project_path,
        "messages": [],
        "phase": "setup",
        "analysis": "",
        "design": "",
        "implementation_summary": "",
        "test_results": "",
        "tests_passed": False,
        "commit_hash": "",
        "retry_count": 0,
        "max_retries": 2,
        "error": None,
        "result_summary": "",
    }

    logger.info(f"Iniciando feature request: '{feature_request[:80]}'")
    logger.info(f"Proyecto: {project_name} en {project_path}")

    async with MultiServerMCPClient(_mcp_connections()) as mcp_client:
        tools = mcp_client.get_tools()
        logger.info(f"MCP tools cargadas: {[t.name for t in tools]}")

        graph = _build_graph(tools)
        final_state = await graph.ainvoke(initial_state)

    logger.info(f"Feature request completado — fase final: {final_state.get('phase')}")
    return final_state


async def stream_feature_request(
    feature_request: str,
    project_name: str = "tracker_master",
    project_path: str = "",
) -> AsyncIterator[dict]:
    """
    Versión streaming de run_feature_request.
    Emite eventos de cada nodo conforme avanza el grafo.

    Uso:
        async for event in stream_feature_request("..."):
            print(event["phase"], event.get("analysis", ""))
    """
    if not project_path:
        project_path = str(PROJECTS_DIR / project_name)

    initial_state: EngineeringState = {
        "feature_request": feature_request,
        "project_name": project_name,
        "project_path": project_path,
        "messages": [],
        "phase": "setup",
        "analysis": "",
        "design": "",
        "implementation_summary": "",
        "test_results": "",
        "tests_passed": False,
        "commit_hash": "",
        "retry_count": 0,
        "max_retries": 2,
        "error": None,
        "result_summary": "",
    }

    async with MultiServerMCPClient(_mcp_connections()) as mcp_client:
        tools = mcp_client.get_tools()
        graph = _build_graph(tools)

        async for event in graph.astream(initial_state, stream_mode="updates"):
            # event es un dict: {node_name: state_updates}
            for node_name, state_updates in event.items():
                yield {
                    "node": node_name,
                    "phase": state_updates.get("phase", ""),
                    **{k: v for k, v in state_updates.items() if k != "messages"},
                }


# ─────────────────────────────────────────────────────────────
#  CLI — para pruebas directas
# ─────────────────────────────────────────────────────────────

async def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="AI Engineering Agent CLI")
    parser.add_argument("feature_request", help="Feature request en lenguaje natural")
    parser.add_argument("--project", default="tracker_master", help="Nombre del proyecto")
    parser.add_argument("--stream", action="store_true", help="Modo streaming")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.stream:
        print(f"\n{'='*60}\nAI Engineering Agent — Streaming\n{'='*60}\n")
        async for event in stream_feature_request(args.feature_request, args.project):
            node = event.get("node", "")
            phase = event.get("phase", "")
            print(f"\n[{node.upper()}] → fase: {phase}")
            if "analysis" in event and event["analysis"]:
                print(f"Análisis ({len(event['analysis'])} chars) ✓")
            if "design" in event and event["design"]:
                print(f"Diseño ({len(event['design'])} chars) ✓")
            if "implementation_summary" in event and event["implementation_summary"]:
                print(f"Implementación ✓")
            if "test_results" in event and event["test_results"]:
                tests_ok = event.get("tests_passed", False)
                print(f"Tests: {'✓ PASARON' if tests_ok else '✗ FALLARON'}")
            if "result_summary" in event and event["result_summary"]:
                print(f"\n{event['result_summary']}")
    else:
        result = await run_feature_request(args.feature_request, args.project)
        print(f"\n{result.get('result_summary', 'Sin resumen')}")


if __name__ == "__main__":
    asyncio.run(_cli())
