# MinionDesk 🤖

[![Version](https://img.shields.io/badge/version-v2.4.20-blue)](https://github.com/KeithKeepGoing/miniondesk/blob/main/CHANGELOG.md)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Docker](https://img.shields.io/badge/docker-required-blue)](https://www.docker.com/)
[![Security Issues](https://img.shields.io/badge/security%20issues-tracked-orange)](https://github.com/KeithKeepGoing/miniondesk/issues?q=label%3Asecurity)

Enterprise AI assistant platform designed for IC design companies. Complete data sovereignty (self-hosted), model-agnostic LLM support, and Docker container isolation.

> **NanoClaw lineage**: MinionDesk is the enterprise branch of the UnifiedClaw family.  
> EvoClaw (personal) ←→ MinionDesk (enterprise) → UnifiedClaw (unified, coming)

---

## 📋 Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Features](#features)
- [Enterprise Integrations](#enterprise-integrations)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Memory System](#memory-system)
- [Security & RBAC](#security--rbac)
- [UnifiedClaw Roadmap](#unifiedclaw-roadmap)
- [Known Issues & Roadmap](#known-issues--roadmap)
- [Contributing](#contributing)

---

## Overview

MinionDesk brings AI assistant capabilities to the enterprise, with:

- **Minion personas** (Phil/Kevin/Stuart/Bob) for approachable interactions
- **Complete data sovereignty** — all data stays on your infrastructure
- **IC design focus** — EDA tools, HPC integration, tape-out workflows
- **Enterprise security** — LDAP/AD, RBAC, DLP, audit logging
- **Multi-provider LLM** — Claude, Gemini, OpenAI, Ollama, vLLM

---

## Architecture

```
[Enterprise Channels]
Telegram / Discord / Slack / Teams / WhatsApp / Web Portal
     │
     ▼
[Python] host/ — Gateway + Orchestrator
  ├── channels/           Multi-channel adapters
  ├── enterprise/
  │   ├── ldap.py         LDAP/AD authentication + RBAC
  │   ├── rbac.py         Role-based access control
  │   ├── workflow.py     Approval workflow engine
  │   ├── knowledge_base.py  RAG knowledge base (FTS5)
  │   ├── jira.py         Jira ticket integration
  │   └── audit.py        Compliance audit logging
  ├── memory/
  │   ├── hot.py          MEMORY.md per group (8KB)
  │   ├── warm.py         30-day daily logs
  │   └── search.py       FTS5 full-text search
  ├── immune.py           Prompt injection detection + IC DLP
  ├── dept_router.py      Department-aware routing (HR/IT/Finance/General)
  ├── task_scheduler.py   cron/interval/once scheduler
  ├── dashboard.py        Web dashboard (port 8080)
  └── webportal.py        FastAPI + WebSocket chat (port 8082)
     │
     │ IPC (file-based → WebSocket in Phase 1)
     ▼
[Python] container/ — Agent Runtime (Docker, non-root UID 1000 "minion")
  ├── runner/
  │   ├── agent.py        Multi-provider LLM agent
  │   ├── tools/
  │   │   ├── filesystem.py   File operations
  │   │   ├── web.py          Web fetch (SSRF-safe)
  │   │   └── enterprise.py   LDAP/HPC/Jira tool wrappers
  │   └── soul.md         Minion persona + ethical principles
  └── Dockerfile          Non-root, minimal attack surface
```

### UnifiedClaw Target Architecture (v3.x)

```
[Channels] + Teams/Matrix/Signal
     │
     ▼
[Python] Gateway + Orchestrator
  ├── Universal Memory Bus  ← NEW (Phase 1)
  │   ├── Hot: MEMORY.md per agent
  │   ├── Shared: cross-agent enterprise knowledge
  │   ├── Vector: sqlite-vec semantic search
  │   └── Cold: FTS5 full-text + time decay
  ├── Enterprise Agent Identity  ← NEW (Phase 2)
  │   └── LDAP DN ↔ agent_id binding
  └── WebSocket IPC  ← NEW (Phase 1)
     │
     ▼
[Python] Agent Runtime (Docker)
  ├── Enterprise tools (LDAP/Jira/HPC/FlexLM/Workflow)
  └── FitnessReporter  ← NEW (Phase 1)
```

---

## Features

### 🤖 Minion Personas
Four distinct AI personalities for enterprise use:
- **Phil** — professional, precise, ideal for HR and finance
- **Kevin** — technical expert, for IT and engineering
- **Stuart** — friendly, approachable, for general queries
- **Bob** — concise, efficient, for quick answers

### 🏢 Department Routing
Automatic routing based on message content:
| Department | Keywords | Capabilities |
|-----------|---------|-------------|
| HR | leave, salary, policy | Leave requests, payroll queries |
| IT | VPN, hardware, ticket | IT ticket creation, troubleshooting |
| Finance | expense, budget, invoice | Expense approval workflow |
| General | (fallback) | General queries, knowledge base |

### 🧠 Three-Tier Memory System
| Layer | Storage | Capacity | Purpose |
|-------|---------|----------|---------|
| Hot | `MEMORY.md` per group | 8KB | Injected at container start |
| Warm | Daily log files | 30 days | Recent conversation history |
| Cold | SQLite FTS5 | Unlimited | Full-text search with time decay |

### 📋 Workflow Engine
YAML-defined approval workflows:
```yaml
# workflows/expense_report.yaml
name: expense_report
steps:
  - role: employee    # submit
  - role: manager     # approve/reject  
  - role: finance     # final approval
notify: [submitter, approvers]
```

---

## Enterprise Integrations

| Integration | Status | Notes |
|------------|--------|-------|
| **LDAP/Active Directory** | ✅ | RBAC with group-based roles |
| **Microsoft Teams** | ✅ | Webhook + HMAC-SHA256 |
| **Jira** | ✅ | Ticket creation & updates |
| **ServiceNow** | ✅ | IT service management |
| **GitLab** | ✅ | Weekly report automation |
| **Confluence** | ✅ | Knowledge base sync |
| **IBM Notes/HCL Domino** | ✅ | Legacy email integration |
| **LSF (bjobs/bsub)** | ✅ | HPC job management |
| **Slurm** | ✅ | HPC cluster scheduling |
| **FlexLM** | ✅ | EDA license monitoring |
| **NetApp/GPFS** | ✅ | NAS storage integration |
| **Matrix** | 🔄 Phase 3 | Private enterprise messaging |

---

## Quick Start

### Requirements
- Python 3.12+
- Docker
- LDAP server (optional, for enterprise auth)
- At least one LLM API key

### Installation
```bash
git clone https://github.com/KeithKeepGoing/miniondesk.git
cd miniondesk
cp .env.example .env
# Edit .env with your configuration
docker build -t miniondesk-agent ./container
python host/main.py
```

### Access
- **Web Portal**: http://localhost:8082
- **Dashboard**: http://localhost:8080
- **Health Check**: http://localhost:8080/health

---

## Configuration

Key environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Recommended | Claude API key |
| `GOOGLE_API_KEY` | Optional | Gemini API key |
| `TELEGRAM_BOT_TOKEN` | For Telegram | Bot token |
| `TEAMS_WEBHOOK_URL` | For Teams | Teams webhook |
| `TEAMS_APP_SECRET` | For Teams | HMAC-SHA256 secret (**required** for security) |
| `LDAP_URL` | For enterprise | ldaps://your-ad-server |
| `LDAP_BIND_DN` | For enterprise | Service account DN |
| `LDAP_BIND_PASSWORD` | For enterprise | Service account password |
| `JIRA_URL` | For Jira | https://your-jira.atlassian.net |
| `JIRA_TOKEN` | For Jira | API token |

> **IC Design Security**: MinionDesk includes built-in DLP rules to prevent leakage of IC design data (GDSII, netlist, test patterns). Configure `DLP_STRICT_MODE=true` for tape-out environments.

---

## Memory System

```
groups/
└── {group_name}/
    ├── MEMORY.md          ← Hot memory (8KB, injected at container start)
    ├── logs/
    │   └── 2026-03-18.md  ← Warm memory (daily logs, 30 days)
    └── ...

knowledge_base/
└── {project}/             ← RAG knowledge base (FTS5 indexed)
    ├── spec/
    ├── runbooks/
    └── policies/
```

---

## Security & RBAC

> See [SECURITY.md](SECURITY.md) for vulnerability reporting.

### RBAC Roles
| Role | Permissions |
|------|------------|
| `admin` | All operations + user management |
| `manager` | Approve workflows, view all reports |
| `employee` | Submit requests, view own data |

### Security Features
- ✅ LDAP/AD integration for authentication
- ✅ HMAC-SHA256 webhook verification (Teams)
- ✅ Docker container isolation (non-root, UID 1000)
- ✅ IC-specific DLP rules
- ✅ Audit logging for compliance
- ✅ Prompt injection detection
- ⚠️ **17 security/architecture issues tracked** — see [GitHub Issues](https://github.com/KeithKeepGoing/miniondesk/issues?q=label%3Asecurity)

### Known Security Issues (In Progress)
- 🔴 Admin CLI lacks authentication (Issue #193)
- 🔴 API keys in os.environ (Issue #194)  
- 🔴 Bash tool uses blocklist (Issue #195)

---

## UnifiedClaw Roadmap

MinionDesk is the **enterprise branch** of the [UnifiedClaw](https://github.com/KeithKeepGoing/evoclaw) unified framework.

### Phase 1 (Near-term)
- [ ] WebSocket IPC (replacing file polling)
- [ ] Universal Memory Bus foundation
- [ ] FitnessReporter integration
- [ ] Basic shared memory (cross-agent enterprise knowledge)

### Phase 2 (Mid-term)
- [ ] Enterprise Agent Identity (LDAP DN ↔ agent_id binding)
- [ ] Cross-project knowledge sharing
- [ ] Department knowledge auto-injection

### Phase 3 (Mid-long term)
- [ ] Matrix channel (private enterprise deployment)
- [ ] Enterprise tools extraction (for EvoClaw use)
- [ ] Multi-tenant support

### Phase 4 (Long-term)
- [ ] Cross-agent genome collaboration
- [ ] Enterprise-specific fitness metrics (workflow outcomes)
- [ ] Agent team auto-organization by department

---

## Known Issues & Roadmap

All tracked issues: [GitHub Issues](https://github.com/KeithKeepGoing/miniondesk/issues)

### Critical (Immediate)
- [ ] [#193] Admin CLI authentication
- [ ] [#194] API key environment exposure  
- [ ] [#195] Bash tool allowlist migration

### High Priority
- [ ] [#196] SQLite async race condition
- [ ] [#197] Workflow authorization check
- [ ] [#198] Audit log fail-hard

→ [Full issue list](https://github.com/KeithKeepGoing/miniondesk/issues)

---

## Contributing

### Development Setup
```bash
git clone https://github.com/KeithKeepGoing/miniondesk.git
cd miniondesk
pip install -r host/requirements.txt
python -m pytest tests/
```

### Key Areas for Contribution
1. **Enterprise tools** — New LDAP/HPC/EDA tool integrations
2. **Workflow templates** — YAML workflow definitions
3. **Security fixes** — See security issues list
4. **UnifiedClaw alignment** — Phase 1-4 architecture work
5. **Tests** — Coverage for immune.py, rbac.py, workflow.py

### Architecture Principles
- Complete data sovereignty (no external services required)
- Graceful degradation (enterprise tools optional)
- Security-first (fail-closed, audit everything)
- IC design awareness (DLP, tape-out workflows)

---

## Recent Changes

See [CHANGELOG.md](CHANGELOG.md) for full history.

| Version | Date | Highlights |
|---------|------|-----------|
| v2.4.20 | 2026-03-17 | Teams integration, HPC tools, Minion personas |
| v2.3.x | 2026-03 | LDAP/AD RBAC, Jira integration |
| v2.2.x | 2026-02 | Workflow engine, FlexLM, knowledge base |

---

*NanoClaw → MinionDesk (enterprise) | NanoClaw → EvoClaw → UnifiedClaw*
