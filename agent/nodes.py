"""
AI Engineering — Nodos del Grafo LangGraph

Cada nodo ejecuta una fase del ciclo de ingeniería:
  analyze → design → implement → test → (fix →)* commit → done

Cada nodo usa create_react_agent para tener acceso a herramientas MCP
con su propio system prompt especializado.
"""
import logging
import sys
import warnings
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

# Suprimir warning de deprecación de create_react_agent hasta LangGraph v2.0
# El import alternativo (langchain.agents) no existe en la versión actual
warnings.filterwarnings("ignore", message=".*create_react_agent.*", category=DeprecationWarning)

# Agregar raíz al path para imports absolutos
sys.path.insert(0, "/opt/ai_engineering")

from config.settings import (
    LITELLM_PROXY_URL, LITELLM_MASTER_KEY, AGENT_MODEL, FAST_MODEL,
)
from agent.state import EngineeringState
from agent.prompts import (
    ANALYZE_SYSTEM, DESIGN_SYSTEM, IMPLEMENT_SYSTEM,
    TEST_SYSTEM, FIX_SYSTEM, COMMIT_SYSTEM,
)

logger = logging.getLogger(__name__)

MAX_RETRIES = 2


# ─────────────────────────────────────────────────────────────
#  CLIENTES LLM (via LiteLLM Proxy)
# ─────────────────────────────────────────────────────────────

def _llm(model: str = AGENT_MODEL, max_tokens: int = 8192) -> ChatOpenAI:
    """Crea un cliente LLM apuntando al LiteLLM Proxy via endpoint OpenAI-compatible.

    Usa ChatOpenAI en lugar de ChatAnthropic para evitar el endpoint /v1/messages
    de Anthropic, que en litellm-proxy-extras genera errores de importación
    con litellm.types.proxy.litellm_pre_call_utils.
    """
    return ChatOpenAI(
        model=model,
        base_url=f"{LITELLM_PROXY_URL}/v1",
        api_key=LITELLM_MASTER_KEY,
        max_tokens=max_tokens,
    )


# ─────────────────────────────────────────────────────────────
#  HELPER: ejecutar un mini-agente ReAct en una fase
# ─────────────────────────────────────────────────────────────

async def _run_react_phase(
    system_prompt: str,
    user_message: str,
    tools: list,
    model: str = AGENT_MODEL,
    max_iterations: int = 20,
) -> str:
    """
    Ejecuta un agente ReAct con las herramientas dadas y retorna
    el contenido del último mensaje AIMessage.
    """
    from langgraph.prebuilt import create_react_agent

    agent = create_react_agent(
        model=_llm(model),
        tools=tools,
        prompt=system_prompt,
    )

    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=user_message)]},
    )
    # El último mensaje es la respuesta final del agente
    last = result["messages"][-1]
    return last.content if hasattr(last, "content") else str(last)


# ─────────────────────────────────────────────────────────────
#  NODO: setup
# ─────────────────────────────────────────────────────────────

async def setup(state: EngineeringState) -> dict[str, Any]:
    """Inicializa el estado y valida que el proyecto exista."""
    project_path = state.get("project_path", "")
    project_name = state.get("project_name", "unknown")

    if not project_path:
        project_path = f"/opt/ai_engineering/projects/{project_name}"

    if not Path(project_path).exists():
        return {
            "phase": "error",
            "error": f"El proyecto '{project_name}' no existe en {project_path}",
        }

    logger.info(f"[setup] Proyecto: {project_name} en {project_path}")

    return {
        "phase": "analyze",
        "project_path": project_path,
        "retry_count": 0,
        "max_retries": MAX_RETRIES,
        "error": None,
    }


# ─────────────────────────────────────────────────────────────
#  NODO: analyze_codebase
# ─────────────────────────────────────────────────────────────

async def analyze_codebase(state: EngineeringState, tools: list) -> dict[str, Any]:
    """Fase 1: Explora el codebase y produce un análisis técnico."""
    logger.info(f"[analyze] Analizando proyecto: {state['project_name']}")

    user_msg = (
        f"PROYECTO: {state['project_name']}\n"
        f"RUTA: {state['project_path']}\n\n"
        f"FEATURE REQUEST:\n{state['feature_request']}\n\n"
        f"Analiza el codebase y produce el análisis técnico completo."
    )

    # Solo herramientas de filesystem para análisis
    fs_tools = [t for t in tools if t.name.startswith(("read_", "list_", "get_file", "search_", "file_exists"))]

    analysis = await _run_react_phase(
        system_prompt=ANALYZE_SYSTEM,
        user_message=user_msg,
        tools=fs_tools,
        model=FAST_MODEL,   # análisis con modelo rápido
    )

    logger.info(f"[analyze] Completado — {len(analysis)} chars")

    return {
        "phase": "design",
        "analysis": analysis,
        "messages": [
            SystemMessage(content="[ANALYZE PHASE COMPLETE]"),
            HumanMessage(content=f"ANÁLISIS:\n{analysis}"),
        ],
    }


# ─────────────────────────────────────────────────────────────
#  NODO: design_solution
# ─────────────────────────────────────────────────────────────

async def design_solution(state: EngineeringState) -> dict[str, Any]:
    """Fase 2: Diseña la solución técnica (sin herramientas, razonamiento puro)."""
    logger.info("[design] Diseñando solución")

    llm = _llm(AGENT_MODEL, max_tokens=4096)

    messages = [
        SystemMessage(content=DESIGN_SYSTEM),
        HumanMessage(content=(
            f"FEATURE REQUEST:\n{state['feature_request']}\n\n"
            f"ANÁLISIS DEL CODEBASE:\n{state['analysis']}\n\n"
            f"Diseña el plan técnico de implementación."
        )),
    ]

    response = await llm.ainvoke(messages)
    design = response.content

    logger.info(f"[design] Plan generado — {len(design)} chars")

    return {
        "phase": "implement",
        "design": design,
        "messages": [HumanMessage(content=f"DISEÑO:\n{design}")],
    }


# ─────────────────────────────────────────────────────────────
#  NODO: implement_code
# ─────────────────────────────────────────────────────────────

async def implement_code(state: EngineeringState, tools: list) -> dict[str, Any]:
    """Fase 3: Implementa el código según el plan técnico."""
    logger.info("[implement] Implementando solución")

    user_msg = (
        f"FEATURE REQUEST:\n{state['feature_request']}\n\n"
        f"PLAN TÉCNICO:\n{state['design']}\n\n"
        f"PROYECTO: {state['project_name']} en {state['project_path']}\n\n"
        f"Implementa el plan. Usa rutas absolutas para todos los archivos."
    )

    # Herramientas de filesystem + bash para implementación
    impl_tools = [
        t for t in tools
        if t.name in (
            "read_file", "write_file", "create_directory", "file_exists",
            "list_directory", "get_file_tree", "run_command",
        )
    ]

    summary = await _run_react_phase(
        system_prompt=IMPLEMENT_SYSTEM,
        user_message=user_msg,
        tools=impl_tools,
    )

    logger.info(f"[implement] Completado — {len(summary)} chars")

    return {
        "phase": "test",
        "implementation_summary": summary,
        "messages": [HumanMessage(content=f"IMPLEMENTACIÓN:\n{summary}")],
    }


# ─────────────────────────────────────────────────────────────
#  NODO: run_tests
# ─────────────────────────────────────────────────────────────

async def run_tests(state: EngineeringState, tools: list) -> dict[str, Any]:
    """Fase 4: Ejecuta tests y evalúa resultados."""
    logger.info("[test] Ejecutando tests")

    user_msg = (
        f"PROYECTO: {state['project_name']} en {state['project_path']}\n\n"
        f"IMPLEMENTACIÓN REALIZADA:\n{state['implementation_summary']}\n\n"
        f"Ejecuta los tests y reporta los resultados."
    )

    test_tools = [
        t for t in tools
        if t.name in ("run_tests", "run_single_test", "get_test_list", "run_command", "read_file")
    ]

    test_output = await _run_react_phase(
        system_prompt=TEST_SYSTEM,
        user_message=user_msg,
        tools=test_tools,
        model=FAST_MODEL,
    )

    # Evaluar si los tests pasaron
    passed = any(kw in test_output.lower() for kw in (
        "passed", "tests pasados", "all tests", "no tests found", "no test files"
    )) and not any(kw in test_output.lower() for kw in (
        "failed", "error", "falló", "failure"
    ))

    logger.info(f"[test] Tests {'PASARON' if passed else 'FALLARON'}")

    return {
        "phase": "commit" if passed else "fix",
        "test_results": test_output,
        "tests_passed": passed,
        "messages": [HumanMessage(content=f"TESTS:\n{test_output}")],
    }


# ─────────────────────────────────────────────────────────────
#  NODO: fix_code
# ─────────────────────────────────────────────────────────────

async def fix_code(state: EngineeringState, tools: list) -> dict[str, Any]:
    """Fase 4b: Corrige errores encontrados en los tests."""
    retry = state.get("retry_count", 0) + 1
    logger.info(f"[fix] Intento de corrección {retry}/{state.get('max_retries', MAX_RETRIES)}")

    if retry > state.get("max_retries", MAX_RETRIES):
        return {
            "phase": "error",
            "error": (
                f"Tests fallidos tras {retry - 1} intentos de corrección.\n"
                f"Último resultado:\n{state['test_results']}"
            ),
        }

    user_msg = (
        f"PROYECTO: {state['project_name']} en {state['project_path']}\n\n"
        f"RESULTADO DE TESTS:\n{state['test_results']}\n\n"
        f"IMPLEMENTACIÓN QUE FALLÓ:\n{state['implementation_summary']}\n\n"
        f"Analiza los fallos y aplica las correcciones necesarias."
    )

    fix_tools = [
        t for t in tools
        if t.name in ("read_file", "write_file", "run_command", "run_tests")
    ]

    fix_summary = await _run_react_phase(
        system_prompt=FIX_SYSTEM,
        user_message=user_msg,
        tools=fix_tools,
    )

    return {
        "phase": "test",
        "retry_count": retry,
        "implementation_summary": state["implementation_summary"] + f"\n\nCORRECCIÓN {retry}:\n{fix_summary}",
        "messages": [HumanMessage(content=f"CORRECCIÓN {retry}:\n{fix_summary}")],
    }


# ─────────────────────────────────────────────────────────────
#  NODO: commit_push
# ─────────────────────────────────────────────────────────────

async def commit_push(state: EngineeringState, tools: list) -> dict[str, Any]:
    """Fase 5: Commit y push de los cambios a una rama de feature en GitHub."""
    logger.info("[commit] Creando commit y push")

    user_msg = (
        f"PROYECTO: {state['project_name']} en {state['project_path']}\n\n"
        f"FEATURE REQUEST:\n{state['feature_request']}\n\n"
        f"IMPLEMENTACIÓN:\n{state['implementation_summary']}\n\n"
        f"Crea una rama de feature, haz commit y push con un mensaje descriptivo."
    )

    git_tools = [
        t for t in tools
        if t.name in (
            "git_status", "git_diff", "git_add", "git_commit",
            "git_push", "git_create_branch", "git_log",
        )
    ]

    commit_output = await _run_react_phase(
        system_prompt=COMMIT_SYSTEM,
        user_message=user_msg,
        tools=git_tools,
        model=FAST_MODEL,
    )

    # Extraer hash del commit del output
    import re
    hash_match = re.search(r"\b([0-9a-f]{7,40})\b", commit_output)
    commit_hash = hash_match.group(1) if hash_match else "unknown"

    logger.info(f"[commit] Push completado — hash: {commit_hash}")

    return {
        "phase": "done",
        "commit_hash": commit_hash,
        "messages": [HumanMessage(content=f"COMMIT:\n{commit_output}")],
    }


# ─────────────────────────────────────────────────────────────
#  NODO: finalize
# ─────────────────────────────────────────────────────────────

async def finalize(state: EngineeringState) -> dict[str, Any]:
    """Nodo final: genera el resumen para el usuario."""
    if state.get("phase") == "error":
        summary = (
            f"❌ El agente encontró un error y no pudo completar el feature request.\n\n"
            f"Error: {state.get('error', 'desconocido')}"
        )
    else:
        summary = (
            f"✅ Feature implementado exitosamente.\n\n"
            f"**Proyecto:** {state['project_name']}\n"
            f"**Feature:** {state['feature_request'][:100]}...\n\n"
            f"**Análisis:** realizado\n"
            f"**Diseño:** completado\n"
            f"**Implementación:** completada\n"
            f"**Tests:** {'pasaron ✓' if state.get('tests_passed') else 'no ejecutados'}\n"
            f"**Commit:** `{state.get('commit_hash', 'N/A')}`\n\n"
            f"Los cambios están en una rama de feature — abre un PR para revisión."
        )

    return {"result_summary": summary}


# ─────────────────────────────────────────────────────────────
#  ROUTER: decide next node
# ─────────────────────────────────────────────────────────────

def route_phase(state: EngineeringState) -> str:
    """Router condicional — decide el siguiente nodo según la fase actual."""
    return state.get("phase", "error")
