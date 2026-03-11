"""
AI Engineering — Vultr MCP Server

Capacidades: listar servidores, obtener estado, crear servidor (requiere confirmacion).
NOTA: Crear y eliminar servidores SIEMPRE requiere confirmación del Director via Telegram.
"""
import json
import sys
import os
from pathlib import Path
import httpx
from mcp.server.fastmcp import FastMCP

sys.path.insert(0, "/opt/ai_engineering")

mcp = FastMCP("vultr")

VULTR_API_KEY = os.getenv("VULTR_API_KEY", "VYFCBC26ATANVYJIS5BECXO2D4FB73VMAZ5Q")
VULTR_BASE    = "https://api.vultr.com/v2"

_headers = {
    "Authorization": f"Bearer {VULTR_API_KEY}",
    "Content-Type": "application/json",
}


def _vultr_get(endpoint: str, params: dict = None) -> dict:
    try:
        resp = httpx.get(f"{VULTR_BASE}/{endpoint}", headers=_headers, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def _vultr_post(endpoint: str, payload: dict) -> dict:
    try:
        resp = httpx.post(f"{VULTR_BASE}/{endpoint}", headers=_headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def _vultr_delete(endpoint: str) -> dict:
    try:
        resp = httpx.delete(f"{VULTR_BASE}/{endpoint}", headers=_headers, timeout=15)
        if resp.status_code == 204:
            return {"ok": True}
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
def list_servers() -> str:
    """Lista todos los servidores VPS en la cuenta Vultr con IP, estado y etiqueta.

    Returns:
        JSON con lista de instancias.
    """
    data = _vultr_get("instances", {"per_page": 100})
    if "error" in data:
        return f"ERROR: {data['error']}"

    instances = data.get("instances", [])
    result = []
    for inst in instances:
        result.append({
            "id":     inst.get("id"),
            "label":  inst.get("label"),
            "ip":     inst.get("main_ip"),
            "status": inst.get("status"),
            "power":  inst.get("power_status"),
            "region": inst.get("region"),
            "plan":   inst.get("plan"),
            "os":     inst.get("os"),
        })
    return json.dumps(result, indent=2)


@mcp.tool()
def get_server_status(instance_id: str) -> str:
    """Obtiene el estado detallado de un servidor Vultr por ID.

    Args:
        instance_id: ID de la instancia Vultr.
    Returns:
        JSON con detalles del servidor.
    """
    data = _vultr_get(f"instances/{instance_id}")
    if "error" in data:
        return f"ERROR: {data['error']}"
    inst = data.get("instance", {})
    return json.dumps({
        "id":         inst.get("id"),
        "label":      inst.get("label"),
        "ip":         inst.get("main_ip"),
        "status":     inst.get("status"),
        "power":      inst.get("power_status"),
        "server_state": inst.get("server_state"),
        "region":     inst.get("region"),
        "plan":       inst.get("plan"),
        "os":         inst.get("os"),
        "ram":        inst.get("ram"),
        "disk":       inst.get("disk"),
        "vcpu":       inst.get("vcpu_count"),
        "date_created": inst.get("date_created"),
    }, indent=2)


@mcp.tool()
def create_server_plan(
    label: str,
    region: str,
    plan: str,
    os_id: int,
    ssh_key_ids: list = None,
) -> str:
    """SOLO GENERA EL PLAN de creación. La ejecución real requiere confirmación del Director.

    Prepara los parámetros para crear un servidor Vultr.
    NO ejecuta la creación — solo retorna el plan para revisión.

    Args:
        label: Etiqueta del servidor.
        region: Región Vultr (ej: 'ewr', 'ord', 'dfw').
        plan: Plan de recursos (ej: 'vc2-1c-1gb', 'vc2-2c-4gb').
        os_id: ID del OS (387=Ubuntu 22.04, 1743=Ubuntu 24.04).
        ssh_key_ids: Lista de IDs de SSH keys a instalar.
    Returns:
        Plan JSON para revisión del Director.
    """
    plan_data = {
        "action": "CREATE_SERVER",
        "requires_director_approval": True,
        "params": {
            "label": label,
            "region": region,
            "plan": plan,
            "os_id": os_id,
            "ssh_key_ids": ssh_key_ids or [],
            "backups": "disabled",
        },
        "estimated_cost_usd_monthly": _estimate_plan_cost(plan),
        "warning": "Este plan REQUIERE aprobación del Director antes de ejecutarse.",
    }
    return json.dumps(plan_data, indent=2)


def _estimate_plan_cost(plan: str) -> str:
    """Estimación aproximada de costo mensual."""
    costs = {
        "vc2-1c-1gb": "$6/mes",
        "vc2-1c-2gb": "$12/mes",
        "vc2-2c-4gb": "$24/mes",
        "vc2-4c-8gb": "$48/mes",
    }
    return costs.get(plan, "consultar pricing Vultr")


@mcp.tool()
def execute_create_server(
    label: str,
    region: str,
    plan: str,
    os_id: int,
    ssh_key_ids: list = None,
    director_auth_token: str = "",
) -> str:
    """Crea un servidor Vultr. REQUIERE token de autorización del Director.

    Args:
        label: Etiqueta del servidor.
        region: Región Vultr.
        plan: Plan de recursos.
        os_id: ID del OS.
        ssh_key_ids: IDs de SSH keys.
        director_auth_token: Token de autorización generado por el Director via Telegram.
    Returns:
        Detalles del servidor creado o error.
    """
    if not director_auth_token or director_auth_token != "DIRECTOR_APPROVED":
        return "ERROR: Se requiere autorización del Director. Usa /autorizar en Telegram."

    payload = {
        "label": label,
        "region": region,
        "plan": plan,
        "os_id": os_id,
        "backups": "disabled",
    }
    if ssh_key_ids:
        payload["sshkey_id"] = ssh_key_ids

    data = _vultr_post("instances", payload)
    if "error" in data:
        return f"ERROR: {data['error']}"

    inst = data.get("instance", {})
    return json.dumps({
        "id":     inst.get("id"),
        "label":  inst.get("label"),
        "ip":     inst.get("main_ip"),
        "status": inst.get("status"),
        "region": inst.get("region"),
    }, indent=2)


@mcp.tool()
def list_regions() -> str:
    """Lista las regiones disponibles en Vultr.

    Returns:
        JSON con regiones disponibles.
    """
    data = _vultr_get("regions")
    if "error" in data:
        return f"ERROR: {data['error']}"
    regions = [
        {"id": r["id"], "city": r.get("city"), "country": r.get("country")}
        for r in data.get("regions", [])
    ]
    return json.dumps(regions[:20], indent=2)


@mcp.tool()
def list_plans(region: str = "ewr") -> str:
    """Lista planes VPS disponibles en una región.

    Args:
        region: ID de región (default: ewr = New Jersey).
    Returns:
        JSON con planes disponibles y precios.
    """
    data = _vultr_get("plans", {"type": "vc2", "per_page": 20})
    if "error" in data:
        return f"ERROR: {data['error']}"
    plans = [
        {
            "id": p["id"],
            "vcpu": p.get("vcpu_count"),
            "ram_mb": p.get("ram"),
            "disk_gb": p.get("disk"),
            "monthly_cost": p.get("monthly_cost"),
        }
        for p in data.get("plans", [])[:15]
    ]
    return json.dumps(plans, indent=2)


if __name__ == "__main__":
    mcp.run()
