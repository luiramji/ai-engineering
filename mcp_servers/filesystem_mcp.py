"""
AI Engineering — Filesystem MCP Server

Tools: read_file, write_file, list_directory, search_files,
       create_directory, delete_file, file_exists, get_file_tree
"""
import os
import fnmatch
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("filesystem")

# Raíz permitida — el agente solo puede operar dentro de /opt/ai_engineering
ALLOWED_ROOT = Path("/opt/ai_engineering")


def _safe_path(path: str) -> Path:
    """Resuelve y valida que el path esté dentro de ALLOWED_ROOT."""
    resolved = Path(path).resolve()
    if not str(resolved).startswith(str(ALLOWED_ROOT)):
        raise PermissionError(
            f"Acceso denegado: '{resolved}' está fuera de {ALLOWED_ROOT}"
        )
    return resolved


# ─────────────────────────────────────────────────────────────
#  TOOLS
# ─────────────────────────────────────────────────────────────

@mcp.tool()
def read_file(path: str) -> str:
    """Lee el contenido completo de un archivo.

    Args:
        path: Ruta absoluta o relativa a /opt/ai_engineering.
    Returns:
        Contenido del archivo como string.
    """
    try:
        p = _safe_path(path)
        return p.read_text(encoding="utf-8", errors="replace")
    except PermissionError as e:
        return f"ERROR: {e}"
    except FileNotFoundError:
        return f"ERROR: Archivo no encontrado: {path}"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Escribe o sobreescribe un archivo con el contenido dado.
    Crea los directorios intermedios si no existen.

    Args:
        path: Ruta absoluta del archivo a escribir.
        content: Contenido completo a escribir.
    Returns:
        Mensaje de éxito o error.
    """
    try:
        p = _safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"OK: Archivo escrito en {p} ({len(content)} bytes)"
    except PermissionError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


@mcp.tool()
def list_directory(path: str, show_hidden: bool = False) -> str:
    """Lista el contenido de un directorio.

    Args:
        path: Ruta del directorio a listar.
        show_hidden: Incluir archivos que comienzan con '.'. Default False.
    Returns:
        Lista de entradas con tipo (FILE/DIR) y tamaño.
    """
    try:
        p = _safe_path(path)
        if not p.is_dir():
            return f"ERROR: '{path}' no es un directorio"
        entries = []
        for item in sorted(p.iterdir()):
            if not show_hidden and item.name.startswith("."):
                continue
            if item.is_dir():
                entries.append(f"DIR  {item.name}/")
            else:
                size = item.stat().st_size
                entries.append(f"FILE {item.name} ({size} bytes)")
        return "\n".join(entries) if entries else "(directorio vacío)"
    except PermissionError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


@mcp.tool()
def get_file_tree(path: str, max_depth: int = 4) -> str:
    """Retorna el árbol de archivos de un directorio hasta max_depth niveles.
    Excluye __pycache__, .git, venv, node_modules automáticamente.

    Args:
        path: Ruta raíz del árbol.
        max_depth: Profundidad máxima. Default 4.
    Returns:
        Árbol de archivos como string indentado.
    """
    SKIP = {"__pycache__", ".git", "venv", ".venv", "node_modules", ".mypy_cache", ".pytest_cache"}

    def _tree(p: Path, prefix: str, depth: int) -> list[str]:
        if depth == 0:
            return ["    (max depth reached)"]
        lines = []
        try:
            items = sorted(p.iterdir())
        except PermissionError:
            return ["    (permission denied)"]
        for i, item in enumerate(items):
            if item.name in SKIP or item.name.startswith("."):
                continue
            connector = "└── " if i == len(items) - 1 else "├── "
            lines.append(f"{prefix}{connector}{item.name}{'/' if item.is_dir() else ''}")
            if item.is_dir():
                extension = "    " if i == len(items) - 1 else "│   "
                lines.extend(_tree(item, prefix + extension, depth - 1))
        return lines

    try:
        p = _safe_path(path)
        lines = [str(p) + "/"]
        lines.extend(_tree(p, "", max_depth))
        return "\n".join(lines)
    except PermissionError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


@mcp.tool()
def search_files(directory: str, pattern: str, content_search: str = "") -> str:
    """Busca archivos por nombre (glob) y opcionalmente por contenido.

    Args:
        directory: Directorio raíz donde buscar.
        pattern: Patrón glob, e.g. '*.py', 'test_*.py', '*.yaml'.
        content_search: Si se provee, filtra archivos que contengan este texto.
    Returns:
        Lista de rutas relativas de archivos encontrados.
    """
    try:
        base = _safe_path(directory)
        results = []
        for p in base.rglob(pattern):
            if not p.is_file():
                continue
            if "__pycache__" in str(p) or ".git" in str(p):
                continue
            if content_search:
                try:
                    text = p.read_text(encoding="utf-8", errors="ignore")
                    if content_search not in text:
                        continue
                except Exception:
                    continue
            results.append(str(p))
        if not results:
            return f"No se encontraron archivos con patrón '{pattern}'" + (
                f" y contenido '{content_search}'" if content_search else ""
            )
        return "\n".join(sorted(results))
    except PermissionError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


@mcp.tool()
def create_directory(path: str) -> str:
    """Crea un directorio y todos sus padres si no existen.

    Args:
        path: Ruta del directorio a crear.
    Returns:
        Mensaje de éxito o error.
    """
    try:
        p = _safe_path(path)
        p.mkdir(parents=True, exist_ok=True)
        return f"OK: Directorio creado: {p}"
    except PermissionError as e:
        return f"ERROR: {e}"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


@mcp.tool()
def file_exists(path: str) -> str:
    """Verifica si un archivo o directorio existe.

    Args:
        path: Ruta a verificar.
    Returns:
        'true' o 'false' según exista o no.
    """
    try:
        p = _safe_path(path)
        return "true" if p.exists() else "false"
    except PermissionError as e:
        return f"ERROR: {e}"


if __name__ == "__main__":
    mcp.run()
