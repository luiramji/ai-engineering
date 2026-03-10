# CLAUDE.md — Memoria Persistente del Agente de Ingeniería

> Lee este archivo al inicio de cada sesión. Actualiza la sección **Estado actual** al finalizar.

---

## 1. IDENTIDAD

Eres el **agente de ingeniería del Servidor 2 (AI Engineering)**.

Tu propósito es recibir feature requests en lenguaje natural y construir software de forma autónoma para el proyecto **Tracker Master**.

---

## 2. INFRAESTRUCTURA

| Recurso | Detalle |
|---|---|
| **Servidor 2 (este)** | IP `149.28.209.93`, usuario `aidev` |
| **Servidor 1 (producción)** | IP `144.202.66.203`, usuario `tracker`, accesible por SSH desde aidev sin contraseña |
| **LiteLLM Proxy** | `localhost:4000` |
| **Web UI** | Puerto `8080` |

**Modelos disponibles en LiteLLM Proxy:**
- `claude-haiku-4-5`
- `claude-sonnet-4-6`
- `gpt-4o-mini`
- `gpt-4o`
- `gemini-2.0-flash`
- `gemini-2.5-pro`

---

## 3. ESTRUCTURA DEL PROYECTO

```
/opt/ai_engineering/
├── CLAUDE.md                  # Este archivo — memoria persistente del agente
├── main.py                    # Punto de entrada principal de la plataforma
├── .gitignore
├── agent/                     # Agente LangGraph principal
│   ├── engineering_agent.py   # Definición del grafo LangGraph
│   ├── nodes.py               # Nodos del grafo (planificar, implementar, revisar, etc.)
│   ├── prompts.py             # Prompts del sistema
│   ├── state.py               # Definición del estado del agente
│   └── __init__.py
├── config/                    # Configuración global
│   ├── .env                   # Variables de entorno (credenciales, API keys)
│   ├── litellm_config.yaml    # Configuración del proxy LiteLLM
│   ├── settings.py            # Carga y valida configuración
│   └── __init__.py
├── logs/                      # Logs de la plataforma
│   ├── ai_engineering.log     # Log del agente
│   └── web.log                # Log del Web UI
├── mcp_servers/               # Servidores MCP disponibles para el agente
│   ├── bash_mcp.py            # Ejecutar comandos bash
│   ├── filesystem_mcp.py      # Operaciones de archivos
│   ├── git_mcp.py             # Operaciones Git
│   ├── pytest_mcp.py          # Ejecución de tests
│   └── __init__.py
├── projects/
│   └── tracker_master/        # Proyecto activo (submodule/repo independiente)
│       ├── main.py            # Entrypoint del agente Tracker Master
│       ├── config.py          # Configuración del proyecto
│       ├── sync_gps_job.py    # Job de sincronización GPS (cron)
│       ├── requirements.txt
│       ├── graph/             # Grafo LangGraph del agente tracker
│       ├── mcp/               # MCPs específicos del proyecto
│       ├── deploy/            # Scripts de despliegue
│       └── tests/             # Tests del proyecto
├── venv/                      # Entorno virtual Python del agente
└── web/                       # Web UI (puerto 8080)
    ├── app.py                 # FastAPI/Flask app
    ├── static/
    │   ├── app.js
    │   └── style.css
    └── templates/
        └── index.html
```

---

## 4. PROYECTO ACTIVO — TRACKER MASTER

**Descripción:** Plataforma de visibilidad logística para transporte de carga en Guatemala.

**Repositorio:** `git@github.com:luiramji/tracker-master.git`
**Ubicación local:** `/opt/ai_engineering/projects/tracker_master`

**Base de datos:** MariaDB en Servidor 1, schema v1.1

Tablas (7):
- `vehicles` — flota de vehículos
- `clients` — clientes
- `routes` — rutas definidas
- `deliveries` — entregas activas y completadas
- `eta_records` — historial de ETAs calculadas
- `position_snapshots` — posiciones GPS capturadas
- `dispatch_conversations` — conversaciones del dispatcher con el agente

**Stack tecnológico:**
- LangGraph (orquestación del agente)
- LiteLLM (abstracción de modelos)
- MCP (herramientas del agente)
- LangSmith (observabilidad y trazas)

---

## 5. REGLAS DE TRABAJO

1. **Nunca modificar producción directamente** — siempre trabajar via Git.
2. Los features nuevos van en rama `ai/*` (ej: `ai/feature-gps-sync`).
3. Usar **`claude-sonnet-4-6`** para diseño e implementación.
4. Usar **`claude-haiku-4-5`** para análisis y tests.
5. **Al finalizar cada sesión**, actualizar obligatoriamente la sección **Estado actual** con:
   - Qué se hizo
   - Qué quedó pendiente
   - Decisiones técnicas importantes tomadas

---

## 6. ESTADO ACTUAL

**Fecha de última actualización:** 10 marzo 2026

### Completado
- LiteLLM Proxy configurado con 6 modelos
- Agente LangGraph con flujo completo
- Web UI corriendo en puerto 8080
- Job de sincronización GPS (`sync_gps_job.py`) generado y pusheado a GitHub

### Pendiente
- [ ] Hacer Web UI servicio systemd (arranque automático)
- [ ] Crear `/opt/ai_engineering/config/.env` con credenciales del Servidor 1
- [ ] Instalar `fail2ban` en Servidor 1
- [ ] Desplegar job GPS en Servidor 1
