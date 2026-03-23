"""
AI Engineering — Story Manager

CRUD para User Stories y Sprints en metodología Scrum.
Stories almacenadas en: /opt/ai_engineering/data/stories/{project_id}.json
Sprints almacenados en: /opt/ai_engineering/data/sprints/{project_id}.json
"""
import json
import logging
import sys
import uuid
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, "/opt/ai_engineering")
from config.settings import DATA_DIR

logger = logging.getLogger(__name__)

STORIES_DIR = DATA_DIR / "stories"
SPRINTS_DIR = DATA_DIR / "sprints"

STORIES_DIR.mkdir(parents=True, exist_ok=True)
SPRINTS_DIR.mkdir(parents=True, exist_ok=True)


def _stories_path(project_id: str) -> Path:
    return STORIES_DIR / f"{project_id}.json"


def _sprints_path(project_id: str) -> Path:
    return SPRINTS_DIR / f"{project_id}.json"


# ─────────────────────────────────────────────────────────────
#  STORIES
# ─────────────────────────────────────────────────────────────

def get_stories(project_id: str) -> list:
    """Retorna todas las user stories del proyecto."""
    path = _stories_path(project_id)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[story_manager] Error leyendo stories de {project_id}: {e}")
        return []


def get_story(project_id: str, story_id: str) -> dict | None:
    """Retorna una story específica o None si no existe."""
    stories = get_stories(project_id)
    return next((s for s in stories if s["id"] == story_id), None)


def save_stories(project_id: str, stories: list) -> None:
    """Persiste la lista completa de stories para un proyecto."""
    path = _stories_path(project_id)
    path.write_text(json.dumps(stories, indent=2, ensure_ascii=False), encoding="utf-8")


def upsert_story(project_id: str, story: dict) -> dict:
    """Crea o actualiza una user story. Asigna id/created_at si faltan."""
    stories = get_stories(project_id)

    if not story.get("id"):
        story["id"] = f"story-{str(uuid.uuid4())[:8]}"
    if not story.get("created_at"):
        story["created_at"] = datetime.now().isoformat()

    # Defaults
    story.setdefault("status", "backlog")
    story.setdefault("completed_at", None)
    story.setdefault("session_id", "")
    story.setdefault("branch", "")
    story.setdefault("pr_url", "")
    story.setdefault("commit_hash", "")
    story.setdefault("clarification_question", "")
    story.setdefault("story_points", 3)
    story.setdefault("priority", "medium")
    story.setdefault("acceptance_criteria", [])

    idx = next((i for i, s in enumerate(stories) if s["id"] == story["id"]), None)
    if idx is not None:
        stories[idx] = story
    else:
        stories.append(story)

    save_stories(project_id, stories)
    return story


def update_story_status(project_id: str, story_id: str, status: str, **kwargs) -> dict:
    """Actualiza el estado de una story y campos adicionales opcionales."""
    stories = get_stories(project_id)
    idx = next((i for i, s in enumerate(stories) if s["id"] == story_id), None)
    if idx is None:
        raise ValueError(f"Story '{story_id}' no encontrada en proyecto '{project_id}'")

    stories[idx]["status"] = status
    if status == "done" and not stories[idx].get("completed_at"):
        stories[idx]["completed_at"] = datetime.now().isoformat()

    for k, v in kwargs.items():
        stories[idx][k] = v

    save_stories(project_id, stories)
    return stories[idx]


def delete_story(project_id: str, story_id: str) -> bool:
    """Elimina una story. Retorna True si existía."""
    stories = get_stories(project_id)
    before = len(stories)
    stories = [s for s in stories if s["id"] != story_id]
    if len(stories) < before:
        save_stories(project_id, stories)
        return True
    return False


def get_backlog(project_id: str) -> list:
    """Retorna stories con status == 'backlog'."""
    return [s for s in get_stories(project_id) if s.get("status") == "backlog"]


# ─────────────────────────────────────────────────────────────
#  SPRINTS
# ─────────────────────────────────────────────────────────────

def get_sprints(project_id: str) -> list:
    """Retorna todos los sprints del proyecto."""
    path = _sprints_path(project_id)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[story_manager] Error leyendo sprints de {project_id}: {e}")
        return []


def _save_sprints(project_id: str, sprints: list) -> None:
    path = _sprints_path(project_id)
    path.write_text(json.dumps(sprints, indent=2, ensure_ascii=False), encoding="utf-8")


def get_current_sprint(project_id: str) -> dict | None:
    """Retorna el sprint activo (status == 'active') o None."""
    return next((s for s in get_sprints(project_id) if s.get("status") == "active"), None)


def create_sprint(
    project_id: str,
    goal: str,
    story_ids: list,
    start_date: str,
    end_date: str,
) -> dict:
    """Crea un nuevo sprint y mueve las stories seleccionadas al sprint."""
    sprints = get_sprints(project_id)
    number = len(sprints) + 1
    sprint_id = f"sprint-{number:03d}"

    # Calcular puntos totales
    stories = get_stories(project_id)
    story_map = {s["id"]: s for s in stories}
    total_points = sum(story_map.get(sid, {}).get("story_points", 0) for sid in story_ids)

    sprint = {
        "id": sprint_id,
        "project": project_id,
        "number": number,
        "goal": goal,
        "start_date": start_date,
        "end_date": end_date,
        "status": "active",
        "story_ids": story_ids,
        "total_points": total_points,
        "completed_points": 0,
        "review_summary": "",
    }

    sprints.append(sprint)
    _save_sprints(project_id, sprints)

    # Mover stories al sprint
    for sid in story_ids:
        try:
            update_story_status(project_id, sid, "sprint")
        except Exception as e:
            logger.warning(f"[story_manager] No se pudo mover story {sid} al sprint: {e}")

    logger.info(f"[story_manager] Sprint {sprint_id} creado para '{project_id}' con {len(story_ids)} stories")
    return sprint


def update_sprint(project_id: str, sprint_id: str, **kwargs) -> dict:
    """Actualiza campos de un sprint."""
    sprints = get_sprints(project_id)
    idx = next((i for i, s in enumerate(sprints) if s["id"] == sprint_id), None)
    if idx is None:
        raise ValueError(f"Sprint '{sprint_id}' no encontrado en proyecto '{project_id}'")

    for k, v in kwargs.items():
        sprints[idx][k] = v

    _save_sprints(project_id, sprints)
    return sprints[idx]
