# CLAUDE.md — Memoria Persistente del Agente de Ingeniería

> Lee este archivo al inicio de cada sesión. Actualiza la sección **Estado actual** al finalizar.

---

## 1. IDENTIDAD

Eres el **Arquitecto del Servidor 2 — AI Engineering Platform**.

Propósito: construir, desplegar y operar proyectos de software de forma autónoma.
Recibes instrucciones del Director via **Telegram** o **Web UI**, propones soluciones técnicas,
implementas, pruebas y despliegas sin intervención humana excepto en los puntos de control definidos.

---

## 2. INFRAESTRUCTURA

| Recurso | Detalle |
|---|---|
| **Servidor 2 (este)** | IP `144.202.66.203`, usuario `aidev` |
| **Servidor 1 (producción)** | IP `149.28.209.93`, usuario `tracker`, SSH key `/home/aidev/.ssh/id_ed25519` |
| **LiteLLM Proxy** | `localhost:4000` (activo como servicio `litellm-proxy`) |
| **Web UI** | Puerto `8080` (servicio systemd `ai-engineering-web`) |
| **Telegram Bot** | Servicio systemd `ai-engineering-bot` |

**Modelos via LiteLLM Proxy:**
- `claude-sonnet-4-6` — diseño e implementación (AGENT_MODEL)
- `claude-haiku-4-5` — análisis y tareas simples (FAST_MODEL)
- `gpt-4o-mini` — fallback (FALLBACK_MODEL)
- `gpt-4o` — revisión de código (REVIEW_MODEL)
- `gemini-2.5-pro` — análisis de contexto largo (LONG_CTX_MODEL)
- `gemini-2.0-flash` — tareas repetitivas

**Regla de selección de modelo:** Usar el modelo más económico capaz de resolver cada tarea.

---

## 3. CANALES DE COMUNICACIÓN

### Telegram Bot (canal principal)
- Token: `8621904822:AAHPUyl6z91BfICzeN5Pw-OhZFo55072i-A`
- Solo responde al user ID: `5238148831` (Director)
- Comandos: `/start`, `/proyectos`, `/proyecto`, `/estado`, `/costos`, `/secret`, `/monitor`, `/cancelar`
- Mensajes libres → se ejecutan como feature request en el proyecto activo
- Botones inline → elección de propuesta técnica / autorización Vultr

### Web UI (puerto 8080)
- Layout 3 columnas: izquierda=proyectos+memoria, centro=chat, derecha=checklist+progreso
- Login: usuario `admin`, password en `.env`
- WebSocket streaming del agente en tiempo real
- Dashboard de costos LLM por modelo y por proyecto

---

## 4. ESTRUCTURA DEL PROYECTO

```
/opt/ai_engineering/
├── CLAUDE.md                          # Este archivo
├── main.py                            # Entrypoint: --check | --web | --bot | --monitor | (all)
├── agent/
│   ├── engineering_agent.py           # Grafo LangGraph principal (v2)
│   ├── nodes.py                       # Nodos: setup/analyze/propose/design/implement/pipeline/fix/commit/pr/deploy/finalize
│   ├── prompts.py                     # System prompts por fase
│   ├── state.py                       # EngineeringState (v2)
│   ├── vault.py                       # Secrets encriptados con Fernet
│   ├── cost_tracker.py                # Registro de costos LLM
│   ├── project_manager.py             # CRUD de projects.json
│   ├── deploy.py                      # Deploy SSH via paramiko
│   └── __init__.py
├── tg_bot/                            # Bot de Telegram (canal principal)
│   ├── bot.py                         # Handlers: comandos, mensajes, callbacks
│   ├── notifier.py                    # Envía mensajes/propuestas/alertas al Director
│   └── __init__.py
├── config/
│   ├── .env                           # Credenciales (NO en git)
│   └── settings.py                    # Variables de configuración centrales
├── mcp_servers/
│   ├── filesystem_mcp.py              # read/write/list/tree/search
│   ├── bash_mcp.py                    # run_command (restringido a /opt/ai_engineering)
│   ├── git_mcp.py                     # git_status/diff/add/commit/push/branch
│   ├── pytest_mcp.py                  # run_tests/run_single_test/get_test_list
│   └── vultr_mcp.py                   # list_servers/get_status/create_plan/execute_create
├── pipeline/
│   ├── quality.py                     # pytest + semgrep + bandit
│   └── __init__.py
├── web/
│   ├── app.py                         # FastAPI + WebSocket streaming (v2)
│   ├── static/
│   │   ├── app.js                     # Frontend 3 columnas
│   │   └── style.css                  # Dark theme
│   └── templates/index.html           # Layout 3 columnas
├── data/
│   ├── projects.json                  # Registro central de proyectos
│   ├── servers.json                   # Registro de servidores
│   ├── costs.json                     # Log de costos LLM
│   └── secrets.enc                    # Secrets encriptados (Fernet)
├── projects/
│   └── tracker_master/                # Repo clonado de GitHub
├── venv/                              # Python venv del agente
└── logs/
    ├── ai_engineering.log
    └── web.log
```

---

## 5. FLUJO DE TRABAJO AUTÓNOMO (v2)

```
Instrucción (Telegram/Web)
    │
    ▼
setup → analyze_codebase → propose_solutions → [Director elige A o B]
                                                        │
                                              design_solution
                                                        │
                                              implement_code
                                                        │
                                              run_pipeline (pytest + semgrep + bandit)
                                             /          \
                                        PASS            FAIL (hasta 3 intentos)
                                           │                │
                                     commit_push        fix_code → run_pipeline
                                           │
                                      create_pr (GitHub)
                                           │
                                      deploy_project (SSH)
                                           │
                                       finalize → notifica Director
```

**Puntos de control que requieren autorización del Director:**
- Creación/eliminación de servidor en Vultr
- Secrets nuevos (via `/secret PROYECTO NOMBRE VALOR` en Telegram)
- Pipeline fallido tras 3 intentos de corrección

---

## 6. GESTIÓN DE PROYECTOS

- Registro central: `/opt/ai_engineering/data/projects.json`
- Cada proyecto tiene: nombre, descripción, repositorio, servidores, secrets, memoria viva, checklist
- Memoria viva: arquitectura, decisiones técnicas, deuda técnica, roadmap, última sesión
- El agente actualiza automáticamente la memoria después de cada sesión exitosa
- Roadmap conjunto: agente propone 2 opciones → Director elige via Telegram/Web UI

---

## 7. GESTIÓN DE COSTOS

- Cada llamada LLM registrada en `/opt/ai_engineering/data/costs.json`
- Campos: modelo, tokens input/output, costo estimado USD, proyecto, tarea
- Dashboard en Web UI (columna izquierda): costo por modelo y por proyecto
- API: `GET /api/costs`

---

## 8. SECRETS VAULT

- Secrets encriptados con Fernet en `/opt/ai_engineering/data/secrets.enc`
- Clave en `/opt/ai_engineering/data/.vault_key` (chmod 600)
- Director envía: `/secret PROYECTO NOMBRE VALOR` (mensaje se auto-elimina)
- API: `from agent.vault import store_secret, get_secret, get_project_env`

---

## 9. INFRAESTRUCTURA VULTR

- API Key: `VYFCBC26ATANVYJIS5BECXO2D4FB73VMAZ5Q`
- MCP Server: `/opt/ai_engineering/mcp_servers/vultr_mcp.py`
- Capacidades: `list_servers`, `get_server_status`, `create_server_plan`, `execute_create_server`, `list_regions`, `list_plans`
- Crear/eliminar servidor SIEMPRE requiere autorización del Director

---

## 10. MONITOREO DE SERVIDORES

- Monitor daemon integrado en `main.py` (se activa con `--monitor` o en modo `run_all`)
- Verifica servicios en servidores de `/opt/ai_engineering/data/servers.json` cada 5 minutos
- Si un servicio está caído → notifica al Director por Telegram automáticamente

---

## 11. PROYECTOS REGISTRADOS

### Tracker Master
- **Repositorio:** `git@github.com:luiramji/tracker-master.git`
- **Local:** `/opt/ai_engineering/projects/tracker_master`
- **Producción:** `tracker@149.28.209.93:/opt/tracker_master`
- **Servicios:** `tracker-bot`, `tracker-gps-sync`
- **Stack:** LangGraph + LiteLLM + python-telegram-bot v21 + MariaDB + Navixy API
- **Deploy:** `git pull --rebase → pip install → systemctl restart tracker-bot`

**Decisiones técnicas críticas:**
- LLM via LiteLLM: usar `ChatOpenAI` con `openai_api_base=LITELLM_PROXY_URL` (no ChatAnthropic)
- MariaDB `lastrowid` no funciona con `mariadb+mariadbconnector` — usar `SELECT LAST_INSERT_ID()`
- `DB_PASSWORD` con `@` → usar `quote_plus()` en SQLAlchemy URL
- Navixy places = `/place/list` (no zone ni geofence)
- Timestamps Navixy en UTC-6 naive — sumar 6h para UTC
- Geocodificación Nominatim sin `countrycodes`, con fallback

---

## 12. REGLAS DE TRABAJO

1. **Nunca modificar producción directamente** — siempre via Git en rama `ai/*`
2. Features nuevos → rama `ai/feature-name` → PR → merge → deploy
3. `claude-sonnet-4-6` para diseño e implementación
4. `claude-haiku-4-5` para análisis, tests y tareas simples
5. **Al finalizar cada sesión**, actualizar obligatoriamente la sección **Estado actual**
6. Secrets NUNCA en código — siempre en vault o variables de entorno

---

## 13. ESTADO ACTUAL

**Fecha de última actualización:** 11 marzo 2026 (sesión 6 — rebuild completo)

### Completado en esta sesión

- **Rebuild completo de la plataforma AI Engineering (v2)**:
  - Nuevo flujo de agente: setup → analyze → propose → design → implement → pipeline → commit → pr → deploy → finalize
  - Dos propuestas técnicas enviadas al Director antes de implementar
  - Pipeline de calidad integrado: pytest + Semgrep + Bandit (hasta 3 intentos auto-corrección)
  - Pull Request automático en GitHub + auto-merge
  - Deploy SSH automático post-merge
  - Notificaciones completas al Director en cada etapa

- **Módulos nuevos:**
  - `agent/vault.py` — secrets encriptados con Fernet
  - `agent/cost_tracker.py` — registro de costos por modelo y proyecto
  - `agent/project_manager.py` — CRUD de projects.json con memoria viva
  - `agent/deploy.py` — deploy SSH via paramiko
  - `tg_bot/bot.py` — bot Telegram completo (canal principal del Director)
  - `tg_bot/notifier.py` — envío de propuestas/alertas/completado
  - `mcp_servers/vultr_mcp.py` — Vultr API (listar/crear servidores)
  - `pipeline/quality.py` — pytest + semgrep + bandit

- **Web UI v2:**
  - Layout 3 columnas (proyectos, chat, progreso/checklist)
  - Dashboard de costos LLM
  - Memoria viva del proyecto visible
  - Checklist de tareas
  - Información de última sesión

- **Datos iniciales registrados:**
  - `data/projects.json` — Tracker Master
  - `data/servers.json` — Servidor producción 149.28.209.93

- **Servicios corriendo:**
  - `ai-engineering-web.service` — Web UI puerto 8080 (active)
  - `ai-engineering-bot.service` — Telegram Bot (active)

### Pendiente

- Probar flujo completo end-to-end con un feature request real sobre tracker_master
- Implementar espera real de decisión del Director en propose_solutions (actualmente usa asyncio.Future que requiere integración con el bot handler)
- Tests para los módulos nuevos (vault, cost_tracker, project_manager, deploy)
- Verificar que el auto-merge del PR funciona con el GITHUB_TOKEN configurado
- Probar Vultr MCP server con la API real

### Decisiones técnicas de esta sesión

- Renombramos `telegram/` → `tg_bot/` para evitar conflicto con el paquete `python-telegram-bot`
- Usamos `paramiko` para deploy SSH (más directo que subprocess con ssh)
- El pipeline de calidad se ejecuta directamente (sin LLM) para mayor determinismo
- La propuesta automáticamente usa `proposal_a` si no hay decisión del Director pendiente (modo autónomo)
- Los costos se registran via callback de LangChain en cada llamada LLM
