# Release Notes

## MinionDesk v2.4.20 (2026-03-17)

### Overview
MinionDesk is an enterprise AI assistant platform designed for IC design companies, featuring complete data sovereignty (self-hosted), model-agnostic LLM support, and Docker container isolation for security.

### Key Features in v2.4.20

#### Enterprise Integrations
- **LDAP/Active Directory**: Full RBAC with group-based role assignment
- **Microsoft Teams**: Webhook integration with HMAC-SHA256 security
- **Jira & ServiceNow**: Ticket creation and workflow automation
- **GitLab & Confluence**: Weekly report automation, knowledge base sync
- **IBM Notes/HCL Domino**: Email integration for legacy enterprise environments

#### HPC & EDA Support
- **LSF** (bjobs, bsub, bkill)
- **Slurm** (squeue, sbatch, scancel)
- **FlexLM** EDA license monitoring
- **NetApp/GPFS** NAS integration

#### AI Capabilities
- Multi-provider LLM support with automatic fallback
- Three-tier memory system for context persistence
- Department-aware routing (HR, IT, Finance, General)
- Approval workflow engine with YAML-defined processes
- RAG knowledge base with semantic search

#### Security
- Docker container isolation (non-root execution)
- Prompt injection detection
- IC-specific data loss prevention (DLP) rules
- HMAC-SHA256 webhook verification (Teams)
- Rate limiting and allowlist management

### Known Issues (Being Fixed)

See GitHub Issues for the full list. Priority items:
- Admin CLI authentication (Critical)
- API key environment variable exposure (Critical)
- Bash tool allowlist migration (Critical)
- Audit log fail-hard implementation (High)

### Installation

```bash
git clone https://github.com/KeithKeepGoing/miniondesk.git
cd miniondesk
cp .env.example .env
# Edit .env with your configuration
docker build -t miniondesk-agent ./container
python host/main.py
```

### Requirements
- Python 3.12+
- Docker
- At least one LLM provider API key (Claude, Gemini, OpenAI, or Ollama)
- Optional: LDAP server, Jira, Teams, etc.

### Upgrade Notes
No breaking changes from v2.3.x. New enterprise integrations are opt-in via environment variables.
