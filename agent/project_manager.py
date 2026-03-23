"""
AI Engineering — Project Manager

CRUD sobre /opt/ai_engineering/data/projects.json.
Gestiona proyectos, memoria viva, servidores y checklists.
"""
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECTS_FILE = Path("/opt/ai_engineering/data/projects.json")


def _load() -> list[dict]:
    if not _PROJECTS_FILE.exists():
        return []
    try:
        return json.loads(_PROJECTS_FILE.read_text())
    except Exception as e:
        logger.error(f"ProjectManager: error cargando projects.json: {e}")
        return []


def _save(data: list[dict]) -> None:
    _PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PROJECTS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_all() -> list[dict]:
    return _load()


def get_project(project_id: str) -> Optional[dict]:
    for p in _load():
        if p.get("id") == project_id or p.get("name") == project_id:
            return p
    return None


def upsert_project(project: dict) -> dict:
    """Crea o actualiza un proyecto."""
    data = _load()
    project["updated_at"] = _now()
    for i, p in enumerate(data):
        if p.get("id") == project.get("id"):
            data[i] = project
            _save(data)
            return project
    project.setdefault("created_at", _now())
    data.append(project)
    _save(data)
    return project


def delete_project(project_id: str) -> bool:
    """Elimina un proyecto del registro. No toca el repo local."""
    data = _load()
    filtered = [p for p in data if p.get("id") != project_id]
    if len(filtered) == len(data):
        return False
    _save(filtered)
    return True


def update_memory(project_id: str, memory_update: dict) -> bool:
    """Actualiza la memoria viva de un proyecto."""
    data = _load()
    for i, p in enumerate(data):
        if p.get("id") == project_id:
            mem = p.get("memory", {})
            for k, v in memory_update.items():
                if isinstance(v, list) and isinstance(mem.get(k), list):
                    mem[k] = v  # reemplaza lista completa
                elif isinstance(v, dict) and isinstance(mem.get(k), dict):
                    mem[k].update(v)
                else:
                    mem[k] = v
            p["memory"] = mem
            p["updated_at"] = _now()
            data[i] = p
            _save(data)
            return True
    return False


def add_checklist_item(project_id: str, task: str, status: str = "pending") -> bool:
    """Agrega un item al checklist del proyecto."""
    data = _load()
    for i, p in enumerate(data):
        if p.get("id") == project_id:
            checklist = p.get("checklist", [])
            checklist.append({
                "task": task,
                "status": status,
                "created_at": _now(),
                "updated_at": _now(),
            })
            p["checklist"] = checklist
            p["updated_at"] = _now()
            data[i] = p
            _save(data)
            return True
    return False


def update_checklist_item(project_id: str, task_index: int, status: str) -> bool:
    """Actualiza el estado de un item del checklist."""
    data = _load()
    for i, p in enumerate(data):
        if p.get("id") == project_id:
            checklist = p.get("checklist", [])
            if 0 <= task_index < len(checklist):
                checklist[task_index]["status"] = status
                checklist[task_index]["updated_at"] = _now()
                p["checklist"] = checklist
                p["updated_at"] = _now()
                data[i] = p
                _save(data)
                return True
    return False


def add_roadmap_proposal(project_id: str, option_a: str, option_b: str) -> bool:
    """Agrega dos propuestas técnicas al roadmap para decisión del Director."""
    data = _load()
    for i, p in enumerate(data):
        if p.get("id") == project_id:
            mem = p.get("memory", {})
            roadmap = mem.get("roadmap", [])
            roadmap.append({
                "status": "pending_decision",
                "created_at": _now(),
                "option_a": option_a,
                "option_b": option_b,
                "chosen": None,
            })
            mem["roadmap"] = roadmap
            p["memory"] = mem
            p["updated_at"] = _now()
            data[i] = p
            _save(data)
            return True
    return False


def set_roadmap_decision(project_id: str, proposal_index: int, choice: str) -> bool:
    """Registra la decisión del Director sobre una propuesta."""
    data = _load()
    for i, p in enumerate(data):
        if p.get("id") == project_id:
            mem = p.get("memory", {})
            roadmap = mem.get("roadmap", [])
            if 0 <= proposal_index < len(roadmap):
                roadmap[proposal_index]["chosen"] = choice
                roadmap[proposal_index]["status"] = "decided"
                roadmap[proposal_index]["decided_at"] = _now()
                mem["roadmap"] = roadmap
                p["memory"] = mem
                p["updated_at"] = _now()
                data[i] = p
                _save(data)
                return True
    return False
