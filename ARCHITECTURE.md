# MinionDesk Architecture

> Enterprise branch of the UnifiedClaw family.
> EvoClaw (personal) <-> MinionDesk (enterprise) -> UnifiedClaw (unified)

## Current Architecture (v2.4.x)

```
[Enterprise Channels]
  Telegram / Discord / Slack / Teams / WhatsApp / Web Portal
       |
       v
[Python] host/ — Gateway + Orchestrator
  ├── channels/           Multi-channel adapters
  ├── enterprise/         LDAP, RBAC, workflows, Jira, audit
  ├── memory/             Three-tier: hot (8KB) / warm (30d) / cold (FTS5)
  ├── memory_bus/         [Phase 1] Universal Memory Bus
  ├── identity/           [Phase 1] Agent Identity Layer
  ├── ws_bridge.py        [Phase 1] WebSocket IPC (port 8769)
  ├── immune.py           Prompt injection + IC DLP
  ├── dept_router.py      Department routing
  ├── task_scheduler.py   Cron/interval/once scheduler
  ├── dashboard.py        Web dashboard (port 8080)
  └── webportal.py        FastAPI + WebSocket chat (port 8082)
       |
       | IPC: file-based (legacy) + WebSocket (Phase 1, port 8769)
       v
[Python] container/ — Agent Runtime (Docker, non-root)
  ├── runner/             Multi-provider LLM agent
  │   ├── providers/      Claude, Gemini, OpenAI, Ollama, vLLM
  │   └── tools/          File, web, enterprise tool wrappers
  └── Dockerfile          Non-root, minimal attack surface
```

## Phase Roadmap

### Phase 1: Foundation (current)

- **MemoryBus** (`host/memory_bus/`)
  - Hot memory: per-group 8KB fast store
  - SharedMemoryStore: cross-agent key-value with TTL
  - VectorStore: embedding-based semantic search (sqlite-vec ready)
  - DB: `~/.miniondesk/memory.db`

- **AgentIdentity** (`host/identity/`)
  - Stable SHA-256 agent IDs (deterministic from name+role+deployment)
  - Registration, heartbeat, lookup
  - DB: `~/.miniondesk/agents.db`

- **WSBridge** (`host/ws_bridge.py`)
  - WebSocket IPC replacing file-based polling
  - JSON protocol: task, result, heartbeat, memory_sync, identity
  - Port 8769 (evoclaw uses 8768)

### Phase 2: Intelligence Layer

- **FitnessReporter**: Agent -> gateway fitness feedback loop
- **Enterprise Knowledge Injection**: Department-aware auto-context
- **Cross-Agent Knowledge Sharing**: Shared memory namespaces
- **SdkApi**: REST API for external integrations (port 8770; evoclaw uses 8767)

### Phase 3: Unified Protocol

- **Cross-Bot Protocol**: MinionDesk <-> EvoClaw communication
- **Unified Identity**: Shared agent identity across deployments
- **Federation**: Multi-instance MinionDesk coordination

## Port Assignments

| Service    | MinionDesk | EvoClaw | Notes                    |
|------------|-----------|---------|--------------------------|
| WSBridge   | 8769      | 8768    | WebSocket IPC            |
| SdkApi     | 8770      | 8767    | REST API (Phase 2)       |
| Dashboard  | 8080      | —       | Web dashboard            |
| WebPortal  | 8082      | —       | FastAPI + WebSocket chat |

## Integration Points with EvoClaw

MinionDesk and EvoClaw share the same Phase 1/2/3 architecture but serve
different domains (enterprise vs personal). Key integration points:

1. **Memory Bus Protocol**: Same SharedMemoryStore schema, enabling cross-bot
   memory sync in Phase 3
2. **Agent Identity**: Same SHA-256 ID scheme, allowing unified identity in Phase 3
3. **WSBridge Protocol**: Same JSON message format, enabling cross-bot IPC in Phase 3
4. **Port separation**: No conflicts when running side-by-side
