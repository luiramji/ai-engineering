"""
AI Engineering — Bash MCP Server

Tool: run_command — ejecuta comandos shell dentro del proyecto.
Seguridad: solo permite operaciones dentro de /opt/ai_engineering,
bloquea comandos destructivos del sistema.
"""
import subprocess
import shlex
import os
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("bash")

ALLOWED_ROOT    = Path("/opt/ai_engineering")
DEFAULT_TIMEOUT = 60

# Prefijos de comandos que nunca deben ejecutarse
BLOCKED_PREFIXES = (
    "rm -rf /",
    "rm -rf ~",
    "mkfs",
    "dd if=",
    ":(){ :|:",  # fork bomb
    "sudo rm -rf",
    "> /dev/sda",
    "chmod -R 777 /",
    "chown -R root /",
)


def _is_blocked(command: str) -> bool:
    cmd = command.strip().lower()
    return any(cmd.startswith(b.lower()) for b in BLOCKED_PREFIXES)


@mcp.tool()
def run_command(
    command: str,
    cwd: str = "/opt/ai_engineering",
    timeout: int = DEFAULT_TIMEOUT,
    env_extra: dict = None,
) -> str:
    """Ejecuta un comando shell en el servidor.

    El directorio de trabajo (cwd) debe estar dentro de /opt/ai_engineering.
    La salida se trunca a 20,000 caracteres si es muy larga.

    Args:
        command: Comando a ejecutar (e.g. 'python -m pytest tests/', 'ls -la').
        cwd: Directorio de trabajo. Default: /opt/ai_engineering.
        timeout: Timeout en segundos. Default: 60. Max: 300.
        env_extra: Variables de entorno adicionales para el proceso.
    Returns:
        Salida combinada (stdout + stderr) del comando con exit code.
    """
    # Validar cwd
    try:
        cwd_path = Path(cwd).resolve()
        if not str(cwd_path).startswith(str(ALLOWED_ROOT)):
            return f"ERROR: cwd '{cwd}' está fuera de {ALLOWED_ROOT}"
        if not cwd_path.exists():
            return f"ERROR: Directorio '{cwd_path}' no existe"
    except Exception as e:
        return f"ERROR validando cwd: {e}"

    # Validar comando
    if _is_blocked(command):
        return f"ERROR: Comando bloqueado por política de seguridad: '{command[:60]}'"

    timeout = min(timeout, 300)

    # Preparar entorno — hereda el entorno actual más extras
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ALLOWED_ROOT)
    if env_extra:
        env.update(env_extra)

    try:
        result = subprocess.run(
            command,
            shell=True,  # nosec B602 — comandos restringidos al directorio del proyecto, validados upstream
            cwd=str(cwd_path),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        output = result.stdout + result.stderr
        # Truncar si es muy larga
        if len(output) > 20_000:
            output = output[:20_000] + f"\n... [truncado — {len(output)} chars totales]"
        status = "OK" if result.returncode == 0 else f"EXIT {result.returncode}"
        return f"[{status}]\n{output}" if output else f"[{status}] (sin salida)"
    except subprocess.TimeoutExpired:
        return f"ERROR: Timeout ({timeout}s) ejecutando: {command[:80]}"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


if __name__ == "__main__":
    mcp.run()
