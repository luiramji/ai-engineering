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
    implement_sprint_story, commit_sprint_story,
)
from agent.project_manager import get_project

logger = logging.getLogger(__name__)


async def clarify_feature_request(feature_request: str, project_name: str) -> dict:
    """Pre-análisis rápido antes de iniciar el trabajo. No inicia el grafo."""
    from agent.nodes import clarify_request
    return await clarify_request(feature_request, project_name)


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

def _build_sprint_graph(tools: list):
    """
    Grafo lean para stories de sprint.
    Flujo: setup → implement_sprint_story → pipeline → fix* → commit_sprint_story → finalize → END
    Elimina: analyze_codebase, propose_solutions, design_solution, create_pr, deploy.
    """
    builder = StateGraph(EngineeringState)

    builder.add_node("setup",                 setup)
    builder.add_node("implement_sprint_story", partial(implement_sprint_story, tools=tools))
    builder.add_node("run_pipeline",           partial(run_pipeline, tools=tools))
    builder.add_node("fix_code",               partial(fix_code,     tools=tools))
    builder.add_node("commit_sprint_story",    commit_sprint_story)
    builder.add_node("finalize",               finalize)

    builder.add_edge(START,                    "setup")
    builder.add_edge("implement_sprint_story", "run_pipeline")
    builder.add_edge("commit_sprint_story",    "finalize")
    builder.add_edge("finalize",               END)

    builder.add_conditional_edges(
        "setup", route_phase,
        {"analyze": "implement_sprint_story", "error": "finalize"},
    )
    builder.add_conditional_edges(
        "run_pipeline", route_phase,
        {"commit": "commit_sprint_story", "fix": "fix_code", "error": "finalize"},
    )
    builder.add_conditional_edges(
        "fix_code", route_phase,
        {"pipeline": "run_pipeline", "error": "finalize"},
    )

    return builder.compile()


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
        "skip_proposal": False,
        "skip_notifications": False,
        "quick_pipeline": False,
        "sprint_branch": "",
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


async def _generate_handoff(project_name: str, project_path: str, goal: str, stories: list) -> str:
    """
    Genera un mensaje humano-amigable: qué se construyó, cómo acceder y cómo ejecutarlo.
    Llama al LLM una sola vez con contexto mínimo.
    """
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage, HumanMessage as HMsg
    from config.settings import LITELLM_PROXY_URL, LITELLM_MASTER_KEY, FAST_MODEL

    impl_summaries = "\n\n".join(
        f"- {s.get('title','')}: {s.get('commit_hash','')}"
        for s in stories if s.get("status") == "done"
    )

    # Leer los archivos clave del proyecto para dar contexto real
    import subprocess as _sp
    try:
        tree = _sp.run(
            ["git", "diff", "--name-only", "main", f"sprint/{project_name.replace('/','_')}"],
            cwd=project_path, capture_output=True, text=True, timeout=10,
        ).stdout.strip() or _sp.run(
            ["find", ".", "-maxdepth", "3", "-type", "f",
             "!", "-path", "./.git/*", "!", "-path", "./venv/*"],
            cwd=project_path, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except Exception:
        tree = ""

    llm = ChatOpenAI(
        model=FAST_MODEL,
        base_url=f"{LITELLM_PROXY_URL}/v1",
        api_key=LITELLM_MASTER_KEY,
        max_tokens=400,
    )

    system = (
        "Eres el asistente de un Director no-técnico. "
        "Se acaba de completar un sprint de desarrollo. "
        "Tu tarea es escribir un mensaje corto y claro (máx 8 líneas) que le diga al Director:\n"
        "1. Qué se construyó en términos simples\n"
        "2. Cómo puede verlo o probarlo (URL, comando para correrlo, archivo a abrir, etc.)\n"
        "3. Si hay algo que deba hacer a continuación\n\n"
        "Sé directo y práctico. Si es una web, da la URL o el comando. "
        "Si no tienes información suficiente para dar una URL exacta, indica cómo encontrarla. "
        "No uses jerga técnica innecesaria. No hagas listas largas."
    )

    user = (
        f"PROYECTO: {project_name}\n"
        f"RUTA LOCAL: {project_path}\n"
        f"OBJETIVO DEL SPRINT: {goal}\n"
        f"ARCHIVOS DEL PROYECTO:\n{tree[:800]}\n"
        f"STORIES COMPLETADAS:\n{impl_summaries[:600]}"
    )

    try:
        resp = await llm.ainvoke([SystemMessage(content=system), HMsg(content=user)])
        return resp.content.strip()
    except Exception as e:
        logger.warning(f"[handoff] Error generando handoff: {e}")
        return f"Proyecto en: {project_path}\nRevisa los archivos generados para ver el resultado."


async def generate_stories_from_epic(epic: str, project_name: str) -> list:
    """Descompone un épico en user stories usando el modelo rápido."""
    from agent.nodes import generate_user_stories
    project_path = str(PROJECTS_DIR / project_name)
    return await generate_user_stories(epic, project_name, project_path)


async def run_sprint(project_name: str, sprint_id: str, model: str = "") -> AsyncIterator[dict]:
    """
    Ejecuta todas las stories de un sprint de forma autónoma, una por una.

    Emite eventos: story_start, phase, analysis, proposal, design,
    implementation, tests, pr, story_done, story_failed, sprint_done.
    """
    from agent.story_manager import (
        get_sprints, get_story, update_story_status, update_sprint, get_stories,
    )

    if not model:
        model = "gpt-4o-mini"

    # Obtener el sprint
    sprints = get_sprints(project_name)
    sprint = next((s for s in sprints if s["id"] == sprint_id), None)
    if not sprint:
        yield {"type": "error", "message": f"Sprint '{sprint_id}' no encontrado"}
        return

    story_ids        = sprint.get("story_ids", [])
    completed_points = sprint.get("completed_points", 0)
    project_path     = str(PROJECTS_DIR / project_name)
    sprint_branch    = f"sprint/{sprint_id}"

    yield {
        "type": "sprint_start",
        "sprint_id": sprint_id,
        "goal": sprint.get("goal", ""),
        "total_stories": len(story_ids),
    }

    mcp_client = MultiServerMCPClient(_mcp_connections())
    tools = await mcp_client.get_tools()
    graph = _build_sprint_graph(tools)   # grafo lean — se reutiliza para cada story

    for story_id in story_ids:
        story = get_story(project_name, story_id)
        if not story:
            logger.warning(f"[run_sprint] Story '{story_id}' no encontrada, saltando")
            continue

        if story.get("status") in ("done", "cancelled"):
            continue

        yield {
            "type": "story_start",
            "story_id": story_id,
            "title": story.get("title", ""),
            "story_points": story.get("story_points", 0),
        }

        update_story_status(project_name, story_id, "in_progress")

        criteria_text = "\n".join(f"  - {c}" for c in story.get("acceptance_criteria", []))
        feature_request = (
            f"{story.get('title', '')}\n\n"
            f"{story.get('description', '')}\n\n"
            f"CRITERIOS DE ACEPTACIÓN:\n{criteria_text}"
        )

        try:
            initial_state = {
                "feature_request":      feature_request,
                "project_name":         project_name,
                "project_path":         project_path,
                "project_data":         {},
                "session_id":           str(uuid.uuid4())[:8],
                "messages":             [],
                "phase":                "setup",
                "analysis":             "",
                "proposal_a":           "",
                "proposal_b":           "",
                "chosen_proposal":      "a",
                "decision_message_id":  "",
                "branch_name":          sprint_branch,
                "design":               "",
                "implementation_summary": "",
                "pipeline_results":     {},
                "tests_passed":         False,
                "test_results":         "",
                "retry_count":          0,
                "max_retries":          2,      # menos reintentos en sprint
                "pr_url":               "",
                "commit_hash":          "",
                "deploy_result":        {},
                "error":                None,
                "requires_director_auth": False,
                "auth_reason":          "",
                "result_summary":       "",
                "notifications_sent":   [],
                "selected_model":       model,
                "clarifications":       "",
                "skip_proposal":        True,
                "skip_notifications":   True,
                "quick_pipeline":       True,   # solo pytest en sprint
                "sprint_branch":        sprint_branch,
            }

            # Acumulamos estos valores a lo largo de los nodos porque
            # finalize() sobreescribe final_state con {result_summary} y pierde el resto
            story_error   = None
            commit_hash   = ""
            branch_name   = sprint_branch

            async for event in graph.astream(initial_state, stream_mode="updates"):
                for node_name, state_updates in event.items():
                    # Capturar error en cualquier nodo que lo emita
                    if state_updates.get("error"):
                        story_error = state_updates["error"]
                    # Capturar commit info del nodo que lo produce
                    if state_updates.get("commit_hash"):
                        commit_hash = state_updates["commit_hash"]
                    if state_updates.get("branch_name"):
                        branch_name = state_updates["branch_name"]

                    phase = state_updates.get("phase", "")
                    yield {
                        "type": "phase",
                        "story_id": story_id,
                        "node": node_name,
                        "phase": phase,
                    }
                    for key, evt_type in [
                        ("implementation_summary", "implementation"),
                        ("test_results",           "tests"),
                    ]:
                        if state_updates.get(key):
                            yield {
                                "type": evt_type,
                                "story_id": story_id,
                                "content": state_updates[key],
                            }

            if story_error:
                update_story_status(project_name, story_id, "failed")
                yield {
                    "type": "story_failed",
                    "story_id": story_id,
                    "title": story.get("title", ""),
                    "error": story_error,
                }
            else:
                update_story_status(
                    project_name, story_id, "done",
                    commit_hash=commit_hash,
                    branch=branch_name,
                )
                completed_points += story.get("story_points", 0)
                update_sprint(project_name, sprint_id, completed_points=completed_points)
                yield {
                    "type": "story_done",
                    "story_id": story_id,
                    "title": story.get("title", ""),
                    "pr_url": "",
                    "commit_hash": commit_hash,
                    "story_points": story.get("story_points", 0),
                }

        except Exception as e:
            logger.error(f"[run_sprint] Error ejecutando story '{story_id}': {e}", exc_info=True)
            update_story_status(project_name, story_id, "failed")
            yield {
                "type": "story_failed",
                "story_id": story_id,
                "title": story.get("title", ""),
                "error": str(e),
            }

    # Sprint completado — generar resumen
    all_stories = get_stories(project_name)
    sprint_stories = [s for s in all_stories if s["id"] in story_ids]
    done_count   = sum(1 for s in sprint_stories if s.get("status") == "done")
    failed_count = sum(1 for s in sprint_stories if s.get("status") == "failed")

    review_summary = (
        f"Sprint {sprint_id} completado.\n"
        f"Stories completadas: {done_count}/{len(story_ids)}\n"
        f"Stories fallidas: {failed_count}/{len(story_ids)}\n"
        f"Puntos completados: {completed_points}/{sprint.get('total_points', 0)}"
    )

    # PR único para todo el sprint (si hay stories completadas)
    sprint_pr_url = ""
    if done_count > 0:
        try:
            import subprocess as _sp
            title = f"Sprint {sprint_id}: {sprint.get('goal', '')[:60]}"
            body  = f"**AI Engineering — Sprint completo**\n\n{review_summary}"
            r = _sp.run(
                ["gh", "pr", "create", "--title", title, "--body", body,
                 "--head", sprint_branch, "--base", "main"],
                cwd=project_path, capture_output=True, text=True, timeout=30,
            )
            if r.returncode == 0:
                import re as _re
                m = _re.search(r"https://github\.com/[^\s]+/pull/\d+", r.stdout)
                sprint_pr_url = m.group(0) if m else ""
                logger.info(f"[run_sprint] PR del sprint: {sprint_pr_url}")
        except Exception as e:
            logger.warning(f"[run_sprint] No se pudo crear PR del sprint: {e}")

    update_sprint(
        project_name, sprint_id,
        status="review",
        review_summary=review_summary,
        completed_points=completed_points,
    )

    # Handoff humano: qué se construyó y cómo acceder al resultado
    handoff = await _generate_handoff(project_name, project_path, sprint.get("goal", ""), sprint_stories)

    # Notificar al Director con el handoff
    try:
        from tg_bot.notifier import send_completion_to_director
        await send_completion_to_director(
            project=project_name,
            summary=f"{review_summary}\n\n{handoff}",
            session_id=sprint_id,
        )
    except Exception as e:
        logger.warning(f"[run_sprint] No se pudo notificar al Director: {e}")

    yield {
        "type": "sprint_done",
        "sprint_id": sprint_id,
        "done_count": done_count,
        "failed_count": failed_count,
        "completed_points": completed_points,
        "total_points": sprint.get("total_points", 0),
        "review_summary": review_summary,
        "sprint_pr_url": sprint_pr_url,
        "handoff": handoff,
    }


async def stream_feature_request(
    feature_request: str,
    project_name: str = "tracker_master",
    project_path: str = "",
    chosen_proposal: str = "a",
    selected_model: str = "",
    clarifications: str = "",
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
        "selected_model": selected_model,
        "clarifications": clarifications,
        "skip_proposal": False,
        "skip_notifications": False,
        "quick_pipeline": False,
        "sprint_branch": "",
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
