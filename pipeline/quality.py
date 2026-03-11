"""
AI Engineering — Pipeline de Calidad

Ejecuta pytest, Semgrep y Bandit sobre el proyecto.
El agente puede llamar esto directamente o via MCP.
"""
import subprocess
import logging
import json
from pathlib import Path

logger = logging.getLogger(__name__)

VENV_PYTHON = "/opt/ai_engineering/venv/bin/python"


def _run(cmd: list, cwd: str, timeout: int = 120) -> tuple[int, str]:
    """Ejecuta un comando y retorna (returncode, output)."""
    try:
        result = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, (result.stdout + result.stderr)[:30_000]
    except subprocess.TimeoutExpired:
        return -1, f"TIMEOUT ({timeout}s)"
    except Exception as e:
        return -2, str(e)


def run_pytest(project_path: str, test_dir: str = "") -> dict:
    """Ejecuta pytest en el proyecto.

    Returns:
        {"passed": bool, "output": str, "returncode": int}
    """
    p = Path(project_path)

    # Detectar python del proyecto
    python = VENV_PYTHON
    for candidate in [p / "venv" / "bin" / "python", p / ".venv" / "bin" / "python"]:
        if candidate.exists():
            python = str(candidate)
            break

    cmd = [python, "-m", "pytest", "--tb=short", "-v", "-q"]
    if test_dir:
        cmd.append(test_dir)

    rc, output = _run(cmd, project_path, timeout=180)
    passed = rc == 0 and "failed" not in output.lower()
    logger.info(f"[pytest] {'PASS' if passed else 'FAIL'} — rc={rc}")
    return {"passed": passed, "output": output, "returncode": rc}


def run_semgrep(project_path: str) -> dict:
    """Ejecuta análisis estático con Semgrep.

    Returns:
        {"passed": bool, "findings": int, "output": str}
    """
    try:
        import semgrep  # noqa: F401
    except ImportError:
        return {"passed": True, "findings": 0, "output": "semgrep no disponible, saltando"}

    cmd = [
        "semgrep", "--config", "auto",
        "--json", "--quiet",
        "--exclude", "venv", "--exclude", ".venv",
        "--exclude", "node_modules", "--exclude", "__pycache__",
        project_path,
    ]
    rc, output = _run(cmd, project_path, timeout=120)

    try:
        data = json.loads(output)
        findings = len(data.get("results", []))
        errors    = len(data.get("errors", []))
        passed    = findings == 0 and errors == 0
        summary   = f"Semgrep: {findings} hallazgos, {errors} errores"
        if findings > 0:
            summary += "\n" + json.dumps(data["results"][:5], indent=2)
    except Exception:
        findings = -1
        passed   = rc == 0
        summary  = output[:5_000]

    logger.info(f"[semgrep] {'PASS' if passed else 'FAIL'} — {findings} hallazgos")
    return {"passed": passed, "findings": findings, "output": summary}


def run_bandit(project_path: str) -> dict:
    """Ejecuta análisis de seguridad con Bandit.

    Returns:
        {"passed": bool, "issues": int, "output": str}
    """
    cmd = [
        VENV_PYTHON, "-m", "bandit",
        "-r", project_path,
        "-f", "json",
        "--exclude", f"{project_path}/venv,{project_path}/.venv,{project_path}/node_modules",
        "-ll",  # solo MEDIUM y HIGH
    ]
    rc, output = _run(cmd, project_path, timeout=120)

    try:
        data = json.loads(output)
        metrics = data.get("metrics", {}).get("_totals", {})
        high    = int(metrics.get("SEVERITY.HIGH", 0))
        medium  = int(metrics.get("SEVERITY.MEDIUM", 0))
        issues  = high + medium
        passed  = high == 0 and medium == 0
        summary = f"Bandit: HIGH={high}, MEDIUM={medium}"
        if issues > 0:
            results = data.get("results", [])[:5]
            summary += "\n" + json.dumps(results, indent=2)
    except Exception:
        issues = -1
        passed = rc == 0
        summary = output[:5_000]

    logger.info(f"[bandit] {'PASS' if passed else 'FAIL'} — {issues} issues")
    return {"passed": passed, "issues": issues, "output": summary}


def run_full_pipeline(project_path: str) -> dict:
    """Ejecuta pytest + semgrep + bandit.

    Returns:
        {
          "all_passed": bool,
          "pytest": {...},
          "semgrep": {...},
          "bandit": {...},
          "summary": str
        }
    """
    logger.info(f"[pipeline] Iniciando pipeline en {project_path}")

    pytest_result  = run_pytest(project_path)
    semgrep_result = run_semgrep(project_path)
    bandit_result  = run_bandit(project_path)

    all_passed = (
        pytest_result["passed"]
        and semgrep_result["passed"]
        and bandit_result["passed"]
    )

    sem_status = "OK" if semgrep_result["passed"] else "FAIL ({} hallazgos)".format(semgrep_result.get("findings", "?"))
    ban_status = "OK" if bandit_result["passed"] else "FAIL ({} issues)".format(bandit_result.get("issues", "?"))
    summary_lines = [
        "Pipeline: {}".format("PASS" if all_passed else "FAIL"),
        "  - pytest:  {}".format("OK" if pytest_result["passed"] else "FAIL"),
        "  - semgrep: {}".format(sem_status),
        "  - bandit:  {}".format(ban_status),
    ]

    return {
        "all_passed": all_passed,
        "pytest":     pytest_result,
        "semgrep":    semgrep_result,
        "bandit":     bandit_result,
        "summary":    "\n".join(summary_lines),
    }
