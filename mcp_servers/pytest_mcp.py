"""
AI Engineering — Pytest MCP Server

Tools: run_tests, run_single_test, get_test_list
Ejecuta tests via subprocess usando el virtualenv del proyecto.
"""
import subprocess
import os
import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("pytest")

ALLOWED_ROOT = Path("/opt/ai_engineering")


def _find_python(project_path: Path) -> str:
    """Encuentra el intérprete Python del virtualenv del proyecto o el global."""
    for candidate in [
        project_path / "venv" / "bin" / "python",
        project_path / ".venv" / "bin" / "python",
        ALLOWED_ROOT / "venv" / "bin" / "python",
    ]:
        if candidate.exists():
            return str(candidate)
    return "python3.11"


@mcp.tool()
def run_tests(
    project_path: str,
    test_path: str = "",
    timeout: int = 120,
    extra_args: str = "",
) -> str:
    """Ejecuta la suite de tests de un proyecto con pytest.

    Args:
        project_path: Ruta raíz del proyecto (donde está pytest.ini o pyproject.toml).
        test_path: Subdirectorio o archivo de tests específico. Default: descubrimiento automático.
        timeout: Timeout total en segundos. Default 120.
        extra_args: Argumentos adicionales para pytest (e.g. '-v -k test_login').
    Returns:
        Output de pytest con resultado de cada test y resumen final.
    """
    try:
        p = Path(project_path).resolve()
        if not str(p).startswith(str(ALLOWED_ROOT)):
            return f"ERROR: '{p}' fuera de {ALLOWED_ROOT}"
        if not p.exists():
            return f"ERROR: '{p}' no existe"

        python = _find_python(p)
        cmd = [python, "-m", "pytest"]

        if test_path:
            cmd.append(test_path)

        cmd += ["-v", "--tb=short", "--no-header", "-q"]
        if extra_args:
            cmd.extend(extra_args.split())

        env = os.environ.copy()
        env["PYTHONPATH"] = str(p)

        result = subprocess.run(
            cmd,
            cwd=str(p),
            capture_output=True,
            text=True,
            timeout=min(timeout, 300),
            env=env,
        )
        output = result.stdout + result.stderr
        if len(output) > 20_000:
            output = output[:20_000] + "\n... [truncado]"
        status = "PASSED" if result.returncode == 0 else f"FAILED (exit {result.returncode})"
        return f"[{status}]\n{output}"
    except subprocess.TimeoutExpired:
        return f"ERROR: Timeout ({timeout}s) ejecutando tests en {project_path}"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


@mcp.tool()
def run_single_test(project_path: str, test_id: str) -> str:
    """Ejecuta un test específico por su ID (module::class::function).

    Args:
        project_path: Ruta raíz del proyecto.
        test_id: ID del test, e.g. 'tests/test_auth.py::test_login_success'.
    Returns:
        Output de pytest para ese test específico.
    """
    return run_tests(project_path, test_id, timeout=60, extra_args="-v --tb=long")


@mcp.tool()
def get_test_list(project_path: str) -> str:
    """Lista todos los tests disponibles en el proyecto sin ejecutarlos.

    Args:
        project_path: Ruta raíz del proyecto.
    Returns:
        Lista de test IDs descubiertos.
    """
    try:
        p = Path(project_path).resolve()
        if not str(p).startswith(str(ALLOWED_ROOT)):
            return f"ERROR: '{p}' fuera de {ALLOWED_ROOT}"

        python = _find_python(p)
        result = subprocess.run(
            [python, "-m", "pytest", "--collect-only", "-q"],
            cwd=str(p),
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "PYTHONPATH": str(p)},
        )
        output = result.stdout + result.stderr
        return output[:10_000] if len(output) > 10_000 else output
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


if __name__ == "__main__":
    mcp.run()
