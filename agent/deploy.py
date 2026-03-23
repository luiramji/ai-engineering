"""
AI Engineering — Deploy via SSH

Despliega proyectos en servidores remotos via SSH con paramiko.
Gestiona el ciclo: git pull → restart service → verificar estado.
"""
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_ssh_client(host: str, user: str, key_path: str = None, password: str = None):
    """Crea y retorna un cliente SSH autenticado (key o password)."""
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # nosec B507 — hosts internos conocidos
    kwargs = {"hostname": host, "username": user, "timeout": 15, "auth_timeout": 15}
    if key_path:
        kwargs["key_filename"] = str(Path(key_path).expanduser())
    elif password:
        kwargs["password"] = password
    client.connect(**kwargs)
    return client


def _exec(client, command: str, timeout: int = 60) -> tuple[int, str]:
    """Ejecuta un comando via SSH y retorna (exit_code, output)."""
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)  # nosec B601 — comandos internos controlados
    stdout.channel.recv_exit_status()  # wait
    output = stdout.read().decode() + stderr.read().decode()
    rc = stdout.channel.recv_exit_status()
    return rc, output[:10_000]


def deploy_project(
    host: str,
    user: str,
    ssh_key: str = None,
    deploy_path: str = "",
    service_name: str = "",
    branch: str = "main",
    password: str = None,
) -> dict:
    """
    Despliega un proyecto via SSH:
      1. git pull --rebase origin {branch}
      2. pip install -r requirements.txt (si existe)
      3. systemctl restart {service_name}
      4. systemctl is-active {service_name}

    Returns:
        {"success": bool, "steps": [{"step": str, "ok": bool, "output": str}], "summary": str}
    """
    steps = []

    logger.info(f"[deploy] Iniciando deploy en {user}@{host}:{deploy_path}")

    try:
        client = _get_ssh_client(host, user, key_path=ssh_key, password=password)
    except Exception as e:
        return {
            "success": False,
            "steps": [{"step": "ssh_connect", "ok": False, "output": str(e)}],
            "summary": f"Error conectando via SSH a {user}@{host}: {e}",
        }

    try:
        # 1. git pull
        rc, out = _exec(client, f"cd {deploy_path} && git pull --rebase origin {branch}", timeout=60)
        steps.append({"step": "git_pull", "ok": rc == 0, "output": out.strip()})

        # 2. pip install (si hay requirements.txt)
        rc2, _ = _exec(client, f"test -f {deploy_path}/requirements.txt && echo yes || echo no")
        has_reqs = "yes" in _
        if has_reqs:
            venv_python = f"{deploy_path}/venv/bin/pip"
            rc3, out3 = _exec(
                client,
                f"cd {deploy_path} && {venv_python} install -r requirements.txt -q",
                timeout=120,
            )
            steps.append({"step": "pip_install", "ok": rc3 == 0, "output": out3.strip()[:1000]})

        # 3. restart service
        rc4, out4 = _exec(client, f"sudo systemctl restart {service_name}", timeout=30)
        steps.append({"step": "service_restart", "ok": rc4 == 0, "output": out4.strip()})

        # 4. verificar estado (esperar 3s para que arranque)
        time.sleep(3)
        rc5, out5 = _exec(client, f"sudo systemctl is-active {service_name}")
        active = out5.strip() == "active"
        steps.append({"step": "service_status", "ok": active, "output": out5.strip()})

        all_ok = all(s["ok"] for s in steps)
        summary = (
            f"Deploy {'exitoso' if all_ok else 'con errores'} en {user}@{host}\n"
            + "\n".join(
                f"  {'OK' if s['ok'] else 'FAIL'} {s['step']}: {s['output'][:100]}"
                for s in steps
            )
        )

        logger.info(f"[deploy] {'OK' if all_ok else 'FAIL'} — {host}")
        return {"success": all_ok, "steps": steps, "summary": summary}

    except Exception as e:
        logger.error(f"[deploy] Error: {e}")
        return {
            "success": False,
            "steps": steps,
            "summary": f"Error durante deploy: {e}",
        }
    finally:
        client.close()


def check_service_health(
    host: str,
    user: str,
    ssh_key: str = None,
    service_name: str = "",
    password: str = None,
) -> dict:
    """Verifica si un servicio está activo en un servidor remoto.

    Returns:
        {"active": bool, "status_output": str}
    """
    try:
        client = _get_ssh_client(host, user, key_path=ssh_key, password=password)
        rc, out = _exec(client, f"sudo systemctl is-active {service_name}")
        client.close()
        active = out.strip() == "active"
        return {"active": active, "status_output": out.strip()}
    except Exception as e:
        return {"active": False, "status_output": str(e)}
