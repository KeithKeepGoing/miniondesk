# MinionDesk Architecture

## Vision: Toward UnifiedClaw

MinionDesk is evolving toward the **UnifiedClaw** unified framework, contributing its enterprise tools and RBAC system while gaining EvoClaw's Evolution Engine and Universal Memory Bus.

```
NanoClaw (origin)
    ├── EvoClaw    — self-evolution + multi-channel
    └── MinionDesk — enterprise tools + RBAC
            ↓
        UnifiedClaw (unified framework)
```

---

## Current Architecture (v2.x)

```
[Channels]
Telegram / WhatsApp / Discord / Microsoft Teams / LINE
     │
     ▼
[Python] host/ — Gateway + Orchestrator
  ├── channels/          Multi-channel adapters
  │   ├── telegram_channel.py
  │   ├── teams_channel.py   (HMAC-SHA256 verified)
  │   ├── discord_channel.py
  │   └── whatsapp_channel.py
  ├── main.py            Async message loop
  ├── db.py              SQLite (WAL mode)
  ├── router.py          Department-aware routing
  │   └── dept_router.py (HR/IT/Finance/Engineering/General)
  ├── enterprise/        Enterprise integrations
  │   ├── ldap.py        LDAP/AD authentication & queries
  │   ├── rbac.py        Role-based access control
  │   ├── knowledge_base.py  RAG knowledge base (FTS5)
  │   ├── workflow.py    Approval workflow engine
  │   ├── jira_tool.py   Jira ticket operations
  │   └── hpc_tools.py   LSF/Slurm HPC management
  ├── immune.py          Prompt injection detection
  ├── memory/            Three-tier memory
  │   ├── hot.py         MEMORY.md per agent
  │   ├── warm.py        30-day logs
  │   └── cold.py        FTS5 full-text search
  ├── scheduler.py       Task scheduler
  ├── health.py          Health monitoring (/health, /metrics)
  ├── dashboard.py       Web dashboard
  └── webportal.py       Web chat portal (FastAPI + WebSocket)
     │
     │ IPC
     ▼
[Python] container/ — Agent Runtime (Docker, non-root UID 1000)
  ├── runner/
  │   ├── agent.py       Multi-provider LLM
  │   │   ├── Claude / Gemini / OpenAI / Ollama / vLLM
  │   ├── tools/
  │   │   ├── filesystem.py  bash/read/write (blocklist-filtered)
  │   │   ├── web.py         web_fetch
  │   │   ├── enterprise.py  LDAP/HPC/Jira wrappers
  │   │   └── knowledge.py   KB search tool
  │   └── soul.md        Core ethical + compliance rules
  └── Dockerfile
```

---

## Target Architecture (UnifiedClaw v3.x)

```
[Channels]
Telegram / WhatsApp / Discord / Teams / Signal / iMessage / Matrix
     │
     ▼
[Python] Gateway + Orchestrator
  ├── channels/          (existing + Matrix)
  ├── memory/
  │   └── memory_bus.py  ← NEW: Universal Memory Bus
  │       ├── Hot         per-agent MEMORY.md
  │       ├── Shared      cross-department (scope: private/dept/company)
  │       ├── Vector      sqlite-vec semantic search (NEW)
  │       ├── Cold        FTS5 + time decay
  │       └── KB          KnowledgeBase integrated into bus (NEW)
  ├── identity/           ← NEW: Enterprise Agent Identity
  │   └── dept_agent_id → profile, skills, handled_tickets
  ├── evolution/          ← NEW: Ported from EvoClaw
  │   ├── genome.py      (dept-aware extension)
  │   ├── fitness.py
  │   ├── adaptive.py
  │   └── immune.py      (existing, enhanced)
  ├── rbac/              ← ENHANCED: Unified permission system
  │   ├── roles.py       (+ agent roles: public/trusted/admin)
  │   └── tool_perms.py  (tool-level RBAC)
  ├── ws_server.py        ← NEW: WebSocket API
  ├── task_scheduler.py
  └── dashboard.py / webportal.py
     │
     │ WebSocket (NEW)
     ▼
[Python] Agent Runtime (Docker, non-root UID 1000)
  ├── agent.py           Multi-provider LLM
  ├── tools/
  │   ├── base.py        ← NEW: EnterpriseTool standard interface
  │   ├── filesystem.py  (upgrade: allowlist)
  │   ├── enterprise/    ← STANDARDIZED
  │   │   ├── ldap.py
  │   │   ├── jira.py
  │   │   ├── hpc.py
  │   │   ├── flexlm.py
  │   │   └── workflow.py
  │   └── kb_search.py   ← integrated with MemoryBus
  ├── fitness_reporter.py ← NEW
  └── soul.md
```

---

## Universal Memory Bus (Enterprise Edition)

```python
class EnterpriseMemoryBus(MemoryBus):
    """Enterprise extension of the Universal Memory Bus."""
    
    async def recall(
        self,
        query: str,
        agent_id: str,
        department: str = None,   # HR/IT/Finance/Engineering
        scope: str = "all",       # private/department/company/all
        k: int = 5
    ) -> list[Memory]:
        """
        Queries: vector (sqlite-vec) + FTS5 + KnowledgeBase
        Respects RBAC: only returns memories agent has access to
        """

    async def remember(
        self,
        content: str,
        agent_id: str,
        scope: Literal["private", "department", "company"] = "private",
        classification: str = "internal"  # internal/confidential/restricted
    ) -> str: ...
```

---

## Enterprise Tool Standard Interface

```python
class EnterpriseTool(BaseTool):
    """Standard interface for all enterprise tools."""
    name: str
    description: str
    required_role: str          # Minimum RBAC role required
    requires_approval: bool     # Goes through workflow engine?
    audit_required: bool        # Must be logged to audit trail
    
    async def execute(
        self, 
        params: dict, 
        context: ToolContext
    ) -> ToolResult:
        # 1. RBAC check
        # 2. Audit log (before execution)
        # 3. Execute
        # 4. Audit log (after execution)
        ...
```

---

## RBAC Evolution

```
Current (v2.x)          Target (UnifiedClaw)
───────────────         ─────────────────────
admin                   admin
manager                 manager
employee                employee
                        agent_public    (read shared memory)
                        agent_trusted   (read/write shared)
                        agent_admin     (enterprise tools)

Tool permissions:
ldap_query    → [employee, manager, admin, agent_trusted]
hpc_submit    → [engineer, manager, admin, agent_admin]
jira_create   → [employee, manager, admin, agent_trusted]
workflow_approve → [manager, admin]
memory_shared_write → [agent_trusted, agent_admin]
```

---

## Development Roadmap

### Phase 1 — Knowledge Enhancement (Near-term)
- [ ] sqlite-vec integration into knowledge_base.py
- [ ] Hybrid search (vector + FTS5) 
- [ ] Agent fitness feedback mechanism
- [ ] MemoryBus abstract interface

### Phase 2 — Evolution + Memory Bus (Mid-term)
- [ ] Port Evolution Engine from EvoClaw (dept-aware)
- [ ] Universal Memory Bus (enterprise edition)
- [ ] Enterprise Agent Identity Layer
- [ ] Cross-department knowledge sharing (with RBAC)

### Phase 3 — UnifiedClaw Integration (Mid-long term)
- [ ] Enterprise tool standardization (BaseTool interface)
- [ ] RBAC upgrade (agent roles + tool permissions)
- [ ] Matrix channel support
- [ ] Merge with EvoClaw into UnifiedClaw

---

## Key Design Principles

1. **Data sovereignty**: All data stays on-premise (SQLite, no cloud dependencies)
2. **RBAC everywhere**: Every tool access, every memory read/write is permission-checked
3. **Audit trail**: Every enterprise tool action logged before and after
4. **Fail-hard for compliance**: Audit failures are hard errors, not warnings
5. **Department-aware**: Memory, routing, and evolution are all department-context aware

---

*NanoClaw → MinionDesk → UnifiedClaw enterprise branch*
