"""
AI Engineering — Nodos del Grafo LangGraph (v2)

Flujo completo:
  setup → analyze → propose → [await_director] → design → implement
       → pipeline → (fix →)* → commit → pr → deploy → finalize → END

Puntos de control con Director:
  - propose: envía dos opciones, espera elección
  - errors > 3 intentos: notifica al Director
  - creación de servidor: requiere autorización
"""
import logging
import sys
import re
import uuid
import warnings
from functools import partial
from pathlib import Path
from typing import Any

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.callbacks import BaseCallbackHandler

warnings.filterwarnings("ignore", message=".*create_react_agent.*", category=DeprecationWarning)

sys.path.insert(0, "/opt/ai_engineering")

from config.settings import (
    LITELLM_PROXY_URL, LITELLM_MASTER_KEY,
    AGENT_MODEL, FAST_MODEL, REVIEW_MODEL, LONG_CTX_MODEL,
    PIPELINE_MAX_RETRIES, SERVER1_HOST, SERVER1_USER, SERVER1_SSH_KEY,
)
from agent.state import EngineeringState
from agent.prompts import (
    ANALYZE_SYSTEM, PROPOSE_SYSTEM, DESIGN_SYSTEM, IMPLEMENT_SYSTEM,
    TEST_SYSTEM, FIX_SYSTEM, COMMIT_SYSTEM, PR_SYSTEM,
)
from agent.cost_tracker import record_call
from agent.project_manager import update_memory, add_roadmap_proposal, get_project

logger = logging.getLogger(__name__)

MAX_RETRIES = PIPELINE_MAX_RETRIES


# ─────────────────────────────────────────────────────────────
#  CALLBACK: logging + cost tracking
# ─────────────────────────────────────────────────────────────

class _PhaseLogger(BaseCallbackHandler):
    """Registra tool calls, LLM activity y costos."""

    def __init__(self, project: str = "", task: str = ""):
        super().__init__()
        self._project = project
        self._task = task
        self._last_model = ""

    def on_tool_start(self, serialized, input_str, **kwargs):
        name = serialized.get("name", "?")
        arg  = str(input_str)[:160].replace("\n", " ")
        logger.info(f"[TOOL] {name} <- {arg}")

    def on_tool_end(self, output, **kwargs):
        out = str(output)
        logger.info(f"[TOOL] -> {out[:200].replace(chr(10), ' ')}{'...' if len(out) > 200 else ''}")

    def on_tool_error(self, error, **kwargs):
        logger.warning(f"[TOOL ERROR] {str(error)[:200]}")

    def on_llm_start(self, serialized, prompts, **kwargs):
        self._last_model = serialized.get("kwargs", {}).get("model_name", "unknown")
        logger.info(f"[LLM] {self._last_model} generando...")

    def on_llm_end(self, response, **kwargs):
        try:
            usage = response.llm_output.get("token_usage", {})
            inp = usage.get("prompt_tokens", 0)
            out = usage.get("completion_tokens", 0)
            cost = record_call(self._last_model, inp, out, self._project, self._task)
            logger.info(f"[LLM] in={inp} out={out} cost=${cost:.4f}")
        except Exception:
            logger.info("[LLM] listo")


# ─────────────────────────────────────────────────────────────
#  LLM CLIENT
# ─────────────────────────────────────────────────────────────

def _llm(model: str = AGENT_MODEL, max_tokens: int = 8192) -> ChatOpenAI:
    return ChatOpenAI(
        model=model,
        base_url=f"{LITELLM_PROXY_URL}/v1",
        api_key=LITELLM_MASTER_KEY,
        max_tokens=max_tokens,
    )


# ─────────────────────────────────────────────────────────────
#  REACT AGENT HELPER
# ─────────────────────────────────────────────────────────────

async def _run_react_phase(
    system_prompt: str,
    user_message: str,
    tools: list,
    model: str = AGENT_MODEL,
    project: str = "",
    task: str = "",
) -> str:
    from langgraph.prebuilt import create_react_agent

    agent = create_react_agent(model=_llm(model), tools=tools, prompt=system_prompt)
    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=user_message)]},
        config={"callbacks": [_PhaseLogger(project, task)]},
    )
    last = result["messages"][-1]
    return last.content if hasattr(last, "content") else str(last)


# ─────────────────────────────────────────────────────────────
#  NODO: setup
# ─────────────────────────────────────────────────────────────

async def setup(state: EngineeringState) -> dict[str, Any]:
    """Inicializa el estado y valida que el proyecto exista."""
    project_name = state.get("project_name", "unknown")
    project_path = state.get("project_path", "")

    if not project_path:
        project_path = f"/opt/ai_engineering/projects/{project_name}"

    if not Path(project_path).exists():
        return {
            "phase": "error",
            "error": f"Proyecto '{project_name}' no encontrado en {project_path}",
        }

    project_data = get_project(project_name) or {}
    session_id   = str(uuid.uuid4())[:8]

    logger.info(f"[setup] Proyecto: {project_name} | sesión: {session_id}")

    return {
        "phase": "analyze",
        "project_path": project_path,
        "project_data": project_data,
        "session_id": session_id,
        "retry_count": 0,
        "max_retries": MAX_RETRIES,
        "error": None,
        "notifications_sent": [],
        "requires_director_auth": False,
        "auth_reason": "",
    }


# ─────────────────────────────────────────────────────────────
#  NODO: analyze_codebase
# ─────────────────────────────────────────────────────────────

async def analyze_codebase(state: EngineeringState, tools: list) -> dict[str, Any]:
    """Fase 1: Analiza el codebase con Gemini (contexto largo) o Haiku."""
    logger.info(f"[analyze] {state['project_name']}")

    # Elegir modelo según tamaño estimado del proyecto
    model = FAST_MODEL  # default rápido

    user_msg = (
        f"PROYECTO: {state['project_name']}\n"
        f"RUTA: {state['project_path']}\n\n"
        f"INSTRUCCIÓN DEL DIRECTOR:\n{state['feature_request']}\n\n"
        f"Analiza el codebase y produce el análisis técnico completo."
    )

    fs_tools = [t for t in tools if t.name.startswith(("read_", "list_", "get_file", "search_", "file_exists"))]

    analysis = await _run_react_phase(
        ANALYZE_SYSTEM, user_msg, fs_tools,
        model=model, project=state["project_name"], task="analyze",
    )

    logger.info(f"[analyze] {len(analysis)} chars")
    return {
        "phase": "propose",
        "analysis": analysis,
        "messages": [HumanMessage(content=f"ANÁLISIS:\n{analysis}")],
    }


# ─────────────────────────────────────────────────────────────
#  NODO: propose_solutions
# ─────────────────────────────────────────────────────────────

async def propose_solutions(state: EngineeringState) -> dict[str, Any]:
    """Fase 2: Genera dos propuestas técnicas para el Director."""
    logger.info("[propose] Generando propuestas técnicas")

    llm = _llm(AGENT_MODEL, max_tokens=4096)

    messages = [
        SystemMessage(content=PROPOSE_SYSTEM),
        HumanMessage(content=(
            f"INSTRUCCIÓN:\n{state['feature_request']}\n\n"
            f"ANÁLISIS DEL CODEBASE:\n{state['analysis']}\n\n"
            f"Genera dos propuestas técnicas alternativas."
        )),
    ]

    response = await llm.ainvoke(messages, config={"callbacks": [_PhaseLogger(state["project_name"], "propose")]})
    content = response.content

    # Extraer propuestas A y B
    proposal_a = _extract_between(content, "## OPCIÓN A", "## OPCIÓN B")
    proposal_b = _extract_after(content, "## OPCIÓN B")

    if not proposal_a or not proposal_b:
        proposal_a = content[:len(content)//2]
        proposal_b = content[len(content)//2:]

    # Guardar en roadmap del proyecto
    add_roadmap_proposal(state["project_name"], proposal_a, proposal_b)

    # Notificar al Director via Telegram (importación lazy)
    try:
        from tg_bot.notifier import send_proposal_to_director
        msg_id = await send_proposal_to_director(
            project=state["project_name"],
            request=state["feature_request"][:200],
            option_a=proposal_a[:800],
            option_b=proposal_b[:800],
            session_id=state.get("session_id", ""),
        )
    except Exception as e:
        logger.warning(f"[propose] No se pudo notificar al Director: {e}")
        msg_id = ""

    logger.info(f"[propose] Propuestas enviadas al Director (msg_id={msg_id})")

    return {
        "phase": "await_decision",
        "proposal_a": proposal_a,
        "proposal_b": proposal_b,
        "decision_message_id": msg_id,
        "messages": [HumanMessage(content=f"PROPUESTAS:\n{content}")],
    }


def _extract_between(text: str, start_marker: str, end_marker: str) -> str:
    try:
        start = text.index(start_marker)
        end   = text.index(end_marker, start + len(start_marker))
        return text[start:end].strip()
    except ValueError:
        return ""


def _extract_after(text: str, marker: str) -> str:
    try:
        idx = text.index(marker)
        return text[idx:].strip()
    except ValueError:
        return ""


# ─────────────────────────────────────────────────────────────
#  NODO: design_solution
# ─────────────────────────────────────────────────────────────

async def design_solution(state: EngineeringState) -> dict[str, Any]:
    """Fase 3: Diseña el plan técnico basado en la propuesta elegida."""
    logger.info("[design] Diseñando plan de implementación")

    chosen = state.get("chosen_proposal", "")
    if not chosen:
        chosen = state.get("proposal_a", "") or state.get("analysis", "")

    llm = _llm(AGENT_MODEL, max_tokens=6000)

    messages = [
        SystemMessage(content=DESIGN_SYSTEM),
        HumanMessage(content=(
            f"INSTRUCCIÓN:\n{state['feature_request']}\n\n"
            f"ANÁLISIS DEL CODEBASE:\n{state['analysis']}\n\n"
            f"PROPUESTA ELEGIDA:\n{chosen}\n\n"
            f"Produce el plan técnico detallado de implementación."
        )),
    ]

    response = await llm.ainvoke(messages, config={"callbacks": [_PhaseLogger(state["project_name"], "design")]})
    design = response.content

    logger.info(f"[design] {len(design)} chars")
    return {
        "phase": "implement",
        "design": design,
        "messages": [HumanMessage(content=f"DISEÑO:\n{design}")],
    }


# ─────────────────────────────────────────────────────────────
#  NODO: implement_code
# ─────────────────────────────────────────────────────────────

async def implement_code(state: EngineeringState, tools: list) -> dict[str, Any]:
    """Fase 4: Implementa el código según el plan técnico."""
    logger.info("[implement] Implementando")

    user_msg = (
        f"INSTRUCCIÓN:\n{state['feature_request']}\n\n"
        f"PLAN TÉCNICO:\n{state['design']}\n\n"
        f"PROYECTO: {state['project_name']} en {state['project_path']}\n\n"
        f"Implementa el plan. Usa rutas absolutas para todos los archivos."
    )

    impl_tools = [t for t in tools if t.name in (
        "read_file", "write_file", "create_directory", "file_exists",
        "list_directory", "get_file_tree", "run_command",
    )]

    summary = await _run_react_phase(
        IMPLEMENT_SYSTEM, user_msg, impl_tools,
        model=AGENT_MODEL, project=state["project_name"], task="implement",
    )

    logger.info(f"[implement] {len(summary)} chars")
    return {
        "phase": "pipeline",
        "implementation_summary": summary,
        "messages": [HumanMessage(content=f"IMPLEMENTACIÓN:\n{summary}")],
    }


# ─────────────────────────────────────────────────────────────
#  NODO: run_pipeline
# ─────────────────────────────────────────────────────────────

async def run_pipeline(state: EngineeringState, tools: list) -> dict[str, Any]:
    """Fase 5: Ejecuta pytest + semgrep + bandit."""
    logger.info("[pipeline] Ejecutando pipeline de calidad")

    # Ejecutar pipeline directamente (no via LLM para mayor control)
    from pipeline.quality import run_full_pipeline
    import asyncio

    loop = asyncio.get_event_loop()
    pipeline_result = await loop.run_in_executor(
        None, run_full_pipeline, state["project_path"]
    )

    passed = pipeline_result["all_passed"]
    summary = pipeline_result["summary"]

    logger.info(f"[pipeline] {'PASS' if passed else 'FAIL'}")

    return {
        "phase": "commit" if passed else "fix",
        "pipeline_results": pipeline_result,
        "tests_passed": passed,
        "test_results": summary,
        "messages": [HumanMessage(content=f"PIPELINE:\n{summary}")],
    }


# ─────────────────────────────────────────────────────────────
#  NODO: fix_code
# ─────────────────────────────────────────────────────────────

async def fix_code(state: EngineeringState, tools: list) -> dict[str, Any]:
    """Fase 5b: Corrige errores del pipeline."""
    retry = state.get("retry_count", 0) + 1
    max_r = state.get("max_retries", MAX_RETRIES)

    logger.info(f"[fix] Intento {retry}/{max_r}")

    if retry > max_r:
        # Notificar al Director
        try:
            from tg_bot.notifier import send_error_to_director
            await send_error_to_director(
                project=state["project_name"],
                error=state["test_results"],
                session_id=state.get("session_id", ""),
            )
        except Exception as e:
            logger.warning(f"[fix] No se pudo notificar al Director: {e}")

        return {
            "phase": "error",
            "error": (
                f"Pipeline fallido tras {retry - 1} intentos.\n"
                f"Director notificado. Resultado:\n{state['test_results']}"
            ),
        }

    # Extraer output detallado de los fallos
    pipeline_results = state.get("pipeline_results", {})
    fail_details = []
    if not pipeline_results.get("pytest", {}).get("passed"):
        fail_details.append("PYTEST:\n" + pipeline_results.get("pytest", {}).get("output", "")[:3000])
    if not pipeline_results.get("semgrep", {}).get("passed"):
        fail_details.append("SEMGREP:\n" + pipeline_results.get("semgrep", {}).get("output", "")[:2000])
    if not pipeline_results.get("bandit", {}).get("passed"):
        fail_details.append("BANDIT:\n" + pipeline_results.get("bandit", {}).get("output", "")[:2000])

    user_msg = (
        f"PROYECTO: {state['project_name']} en {state['project_path']}\n\n"
        f"ERRORES DEL PIPELINE:\n" + "\n\n".join(fail_details) + "\n\n"
        f"IMPLEMENTACIÓN QUE FALLÓ:\n{state['implementation_summary']}\n\n"
        f"Analiza y corrige los errores. Intento {retry}/{max_r}."
    )

    fix_tools = [t for t in tools if t.name in (
        "read_file", "write_file", "run_command", "create_directory", "file_exists",
    )]

    fix_summary = await _run_react_phase(
        FIX_SYSTEM, user_msg, fix_tools,
        model=AGENT_MODEL, project=state["project_name"], task=f"fix_{retry}",
    )

    return {
        "phase": "pipeline",
        "retry_count": retry,
        "implementation_summary": state["implementation_summary"] + f"\n\nCORRECCIÓN {retry}:\n{fix_summary}",
        "messages": [HumanMessage(content=f"CORRECCIÓN {retry}:\n{fix_summary}")],
    }


# ─────────────────────────────────────────────────────────────
#  NODO: commit_push
# ─────────────────────────────────────────────────────────────

async def commit_push(state: EngineeringState, tools: list) -> dict[str, Any]:
    """Fase 6: Crea rama, commit y push a GitHub."""
    logger.info("[commit] Creando commit y push")

    user_msg = (
        f"PROYECTO: {state['project_name']} en {state['project_path']}\n\n"
        f"INSTRUCCIÓN ORIGINAL:\n{state['feature_request']}\n\n"
        f"IMPLEMENTACIÓN:\n{state['implementation_summary']}\n\n"
        f"Crea una rama de feature (prefijo ai/), haz commit y push."
    )

    git_tools = [t for t in tools if t.name in (
        "git_status", "git_diff", "git_add", "git_commit",
        "git_push", "git_create_branch", "git_log",
    )]

    commit_output = await _run_react_phase(
        COMMIT_SYSTEM, user_msg, git_tools,
        model=FAST_MODEL, project=state["project_name"], task="commit",
    )

    # Extraer hash del commit
    hash_match = re.search(r"\b([0-9a-f]{7,40})\b", commit_output)
    commit_hash = hash_match.group(1) if hash_match else "unknown"

    # Extraer nombre de la rama
    branch_match = re.search(r"ai/[\w\-]+", commit_output)
    branch_name = branch_match.group(0) if branch_match else "ai/feature"

    logger.info(f"[commit] hash={commit_hash} branch={branch_name}")

    return {
        "phase": "pr",
        "commit_hash": commit_hash,
        "branch_name": branch_name,
        "messages": [HumanMessage(content=f"COMMIT:\n{commit_output}")],
    }


# ─────────────────────────────────────────────────────────────
#  NODO: create_pr
# ─────────────────────────────────────────────────────────────

async def create_pr(state: EngineeringState, tools: list) -> dict[str, Any]:
    """Fase 7: Crea Pull Request en GitHub y hace merge automático a main."""
    logger.info("[pr] Creando Pull Request")

    branch = state.get("branch_name", "ai/feature")

    user_msg = (
        f"PROYECTO: {state['project_name']} en {state['project_path']}\n"
        f"RAMA: {branch}\n"
        f"INSTRUCCIÓN: {state['feature_request']}\n"
        f"IMPLEMENTACIÓN: {state['implementation_summary'][:500]}\n\n"
        f"Crea el Pull Request de {branch} hacia main con el comando gh."
    )

    bash_tools = [t for t in tools if t.name == "run_command"]

    pr_output = await _run_react_phase(
        PR_SYSTEM, user_msg, bash_tools,
        model=FAST_MODEL, project=state["project_name"], task="pr",
    )

    # Extraer URL del PR
    url_match = re.search(r"https://github\.com/[^\s]+/pull/\d+", pr_output)
    pr_url = url_match.group(0) if url_match else ""

    # Auto-merge si se pudo crear el PR
    if pr_url:
        try:
            from agent.deploy import _exec, _get_ssh_client
            # Merge automático via gh CLI local
            import subprocess
            pr_num = pr_url.split("/")[-1]
            result = subprocess.run(
                ["gh", "pr", "merge", pr_num, "--merge", "--auto", "--delete-branch"],
                cwd=state["project_path"],
                capture_output=True, text=True, timeout=30,
            )
            logger.info(f"[pr] auto-merge: {result.stdout.strip()[:200]}")
        except Exception as e:
            logger.warning(f"[pr] auto-merge falló: {e}")

    logger.info(f"[pr] URL: {pr_url}")

    return {
        "phase": "deploy",
        "pr_url": pr_url,
        "messages": [HumanMessage(content=f"PR:\n{pr_output}")],
    }


# ─────────────────────────────────────────────────────────────
#  NODO: deploy
# ─────────────────────────────────────────────────────────────

async def deploy_project(state: EngineeringState) -> dict[str, Any]:
    """Fase 8: Deploy al servidor de producción via SSH."""
    logger.info("[deploy] Iniciando deploy")

    project_data = state.get("project_data", {})
    servers = project_data.get("servers", [])

    if not servers:
        logger.info("[deploy] Sin servidores configurados, saltando")
        return {
            "phase": "done",
            "deploy_result": {"success": True, "summary": "No hay servidores de deploy configurados"},
        }

    # Deploy al primer servidor de producción
    prod_server = next(
        (s for s in servers if s.get("purpose") == "production"),
        servers[0]
    )

    import asyncio
    from agent.deploy import deploy_project as _deploy

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: _deploy(
            host=prod_server.get("ip", SERVER1_HOST),
            user=prod_server.get("user", "tracker"),
            ssh_key=prod_server.get("ssh_key", SERVER1_SSH_KEY),
            deploy_path=prod_server.get("deploy_path", "/opt/tracker_master"),
            service_name=prod_server.get("service_name", "tracker-bot"),
        )
    )

    logger.info(f"[deploy] {'OK' if result['success'] else 'FAIL'}")

    return {
        "phase": "done",
        "deploy_result": result,
    }


# ─────────────────────────────────────────────────────────────
#  NODO: finalize
# ─────────────────────────────────────────────────────────────

async def finalize(state: EngineeringState) -> dict[str, Any]:
    """Nodo final: genera resumen y notifica al Director."""

    if state.get("phase") == "error":
        summary = (
            f"Error en AI Engineering.\n\n"
            f"Proyecto: {state.get('project_name')}\n"
            f"Error: {state.get('error', 'desconocido')}\n"
            f"Sesión: {state.get('session_id', 'N/A')}"
        )
    else:
        deploy_ok = state.get("deploy_result", {}).get("success", False)
        summary = (
            f"Feature implementado exitosamente.\n\n"
            f"Proyecto: {state.get('project_name')}\n"
            f"Feature: {state.get('feature_request', '')[:100]}\n"
            f"Rama: {state.get('branch_name', 'N/A')}\n"
            f"Commit: {state.get('commit_hash', 'N/A')}\n"
            f"PR: {state.get('pr_url', 'N/A')}\n"
            f"Pipeline: {'PASS' if state.get('tests_passed') else 'N/A'}\n"
            f"Deploy: {'OK' if deploy_ok else 'N/A'}\n"
            f"Sesión: {state.get('session_id', 'N/A')}"
        )

    # Actualizar memoria del proyecto
    try:
        impl_summary = state.get("implementation_summary", "")
        if impl_summary:
            update_memory(state.get("project_name", ""), {
                "last_session": {
                    "date": __import__("datetime").datetime.now().isoformat(),
                    "feature": state.get("feature_request", "")[:200],
                    "commit": state.get("commit_hash", ""),
                    "pr": state.get("pr_url", ""),
                }
            })
    except Exception as e:
        logger.warning(f"[finalize] Error actualizando memoria: {e}")

    # Notificar al Director
    try:
        from tg_bot.notifier import send_completion_to_director
        await send_completion_to_director(
            project=state.get("project_name", ""),
            summary=summary,
            session_id=state.get("session_id", ""),
        )
    except Exception as e:
        logger.warning(f"[finalize] No se pudo notificar al Director: {e}")

    return {"result_summary": summary}


# ─────────────────────────────────────────────────────────────
#  ROUTER
# ─────────────────────────────────────────────────────────────

def route_phase(state: EngineeringState) -> str:
    """Router condicional — decide el siguiente nodo según la fase actual."""
    return state.get("phase", "error")
