"""
AI Engineering — Git MCP Server

Tools: git_status, git_diff, git_log, git_add, git_commit,
       git_push, git_pull, git_create_branch, git_checkout
El agente NUNCA hace push a main/master directamente — siempre via rama.
"""
import subprocess
import os
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("git")

ALLOWED_ROOT = Path("/opt/ai_engineering")
GIT_USER_NAME  = os.getenv("GIT_USER_NAME",  "AI Engineering Bot")
GIT_USER_EMAIL = os.getenv("GIT_USER_EMAIL", "ai-bot@ai-engineering.local")

PROTECTED_BRANCHES = {"main", "master", "production", "prod"}


def _run_git(args: list[str], cwd: str) -> tuple[int, str]:
    """Ejecuta un comando git y retorna (returncode, output)."""
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"]     = GIT_USER_NAME
    env["GIT_AUTHOR_EMAIL"]    = GIT_USER_EMAIL
    env["GIT_COMMITTER_NAME"]  = GIT_USER_NAME
    env["GIT_COMMITTER_EMAIL"] = GIT_USER_EMAIL
    result = subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    output = (result.stdout + result.stderr).strip()
    return result.returncode, output


def _validate_repo(repo_path: str) -> tuple[Path | None, str]:
    """Valida que el repo_path sea un repositorio git dentro del área permitida."""
    try:
        p = Path(repo_path).resolve()
        if not str(p).startswith(str(ALLOWED_ROOT)):
            return None, f"ERROR: '{p}' está fuera de {ALLOWED_ROOT}"
        if not (p / ".git").exists():
            return None, f"ERROR: '{p}' no es un repositorio git"
        return p, ""
    except Exception as e:
        return None, f"ERROR: {e}"


# ─────────────────────────────────────────────────────────────
#  TOOLS
# ─────────────────────────────────────────────────────────────

@mcp.tool()
def git_status(repo_path: str) -> str:
    """Muestra el estado del working tree (archivos modificados, staged, untracked).

    Args:
        repo_path: Ruta al repositorio git.
    Returns:
        Salida de `git status`.
    """
    p, err = _validate_repo(repo_path)
    if err:
        return err
    _, out = _run_git(["status", "--short", "--branch"], str(p))
    return out or "(working tree limpio)"


@mcp.tool()
def git_diff(repo_path: str, staged: bool = False) -> str:
    """Muestra diferencias en el working tree o staged area.

    Args:
        repo_path: Ruta al repositorio git.
        staged: Si True, muestra diff del área staged (--cached). Default False.
    Returns:
        Diff en formato unified.
    """
    p, err = _validate_repo(repo_path)
    if err:
        return err
    args = ["diff"]
    if staged:
        args.append("--cached")
    args.extend(["--stat", "--patch"])
    _, out = _run_git(args, str(p))
    return out or "(sin diferencias)"


@mcp.tool()
def git_log(repo_path: str, n: int = 10) -> str:
    """Muestra los últimos n commits del repositorio.

    Args:
        repo_path: Ruta al repositorio git.
        n: Número de commits a mostrar. Default 10.
    Returns:
        Log formateado con hash, autor, fecha y mensaje.
    """
    p, err = _validate_repo(repo_path)
    if err:
        return err
    _, out = _run_git(
        ["log", f"-{min(n, 50)}", "--pretty=format:%h │ %an │ %ar │ %s"],
        str(p),
    )
    return out or "(sin commits)"


@mcp.tool()
def git_add(repo_path: str, paths: list[str] = None) -> str:
    """Agrega archivos al staging area.

    Args:
        repo_path: Ruta al repositorio git.
        paths: Lista de rutas a agregar. Si es None o vacío, agrega todos los cambios.
    Returns:
        Confirmación del staging.
    """
    p, err = _validate_repo(repo_path)
    if err:
        return err
    if not paths:
        rc, out = _run_git(["add", "-A"], str(p))
    else:
        rc, out = _run_git(["add"] + paths, str(p))
    if rc != 0:
        return f"ERROR git add: {out}"
    # Mostrar qué quedó en staged
    _, status = _run_git(["status", "--short"], str(p))
    return f"OK: Archivos en staging:\n{status}"


@mcp.tool()
def git_commit(repo_path: str, message: str) -> str:
    """Crea un commit con los archivos en staging.

    Args:
        repo_path: Ruta al repositorio git.
        message: Mensaje del commit (convencional: 'feat: ...', 'fix: ...').
    Returns:
        Hash del commit creado o error.
    """
    p, err = _validate_repo(repo_path)
    if err:
        return err
    if not message.strip():
        return "ERROR: El mensaje de commit no puede estar vacío"
    full_message = f"{message}\n\nCo-authored-by: AI Engineering Bot <ai-bot@ai-engineering.local>"
    rc, out = _run_git(["commit", "-m", full_message], str(p))
    if rc != 0:
        return f"ERROR git commit: {out}"
    return f"OK: {out}"


@mcp.tool()
def git_push(repo_path: str, branch: str = "", force: bool = False) -> str:
    """Hace push de la rama actual o especificada al remoto origin.

    NUNCA hace push a main/master — usa ramas de feature.

    Args:
        repo_path: Ruta al repositorio git.
        branch: Nombre de la rama. Si vacío, usa la rama actual.
        force: Si True, usa --force-with-lease (más seguro que --force).
    Returns:
        Resultado del push.
    """
    p, err = _validate_repo(repo_path)
    if err:
        return err

    # Obtener rama actual si no se especifica
    if not branch:
        _, branch = _run_git(["branch", "--show-current"], str(p))
        branch = branch.strip()

    if branch in PROTECTED_BRANCHES:
        return (
            f"ERROR: Push directo a '{branch}' está bloqueado. "
            f"Crea una rama de feature y haz PR."
        )

    args = ["push", "origin", branch, "--set-upstream"]
    if force:
        args.append("--force-with-lease")

    rc, out = _run_git(args, str(p))
    if rc != 0:
        return f"ERROR git push: {out}"
    return f"OK: Push a origin/{branch}\n{out}"


@mcp.tool()
def git_pull(repo_path: str) -> str:
    """Hace pull --rebase del remoto origin en la rama actual.

    Args:
        repo_path: Ruta al repositorio git.
    Returns:
        Resultado del pull.
    """
    p, err = _validate_repo(repo_path)
    if err:
        return err
    rc, out = _run_git(["pull", "--rebase", "origin"], str(p))
    if rc != 0:
        return f"ERROR git pull: {out}"
    return f"OK: {out}"


@mcp.tool()
def git_create_branch(repo_path: str, branch_name: str) -> str:
    """Crea y hace checkout a una nueva rama de feature.

    El nombre de la rama se normaliza (espacios → guiones, minúsculas).
    Prefija automáticamente con 'ai/' si no tiene prefijo.

    Args:
        repo_path: Ruta al repositorio git.
        branch_name: Nombre deseado para la rama.
    Returns:
        Confirmación de la rama creada.
    """
    p, err = _validate_repo(repo_path)
    if err:
        return err

    # Normalizar nombre
    normalized = branch_name.lower().replace(" ", "-").replace("_", "-")
    if not any(normalized.startswith(pref) for pref in ("ai/", "feat/", "fix/", "chore/")):
        normalized = f"ai/{normalized}"

    rc, out = _run_git(["checkout", "-b", normalized], str(p))
    if rc != 0:
        return f"ERROR creando rama: {out}"
    return f"OK: Rama '{normalized}' creada y activa\n{out}"


@mcp.tool()
def git_checkout(repo_path: str, branch: str) -> str:
    """Cambia a una rama existente.

    Args:
        repo_path: Ruta al repositorio git.
        branch: Nombre de la rama destino.
    Returns:
        Confirmación o error.
    """
    p, err = _validate_repo(repo_path)
    if err:
        return err
    rc, out = _run_git(["checkout", branch], str(p))
    if rc != 0:
        return f"ERROR git checkout: {out}"
    return f"OK: {out}"


if __name__ == "__main__":
    mcp.run()
