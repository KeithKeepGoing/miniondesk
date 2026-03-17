# Changelog

## [Unreleased] — UnifiedClaw Enterprise Roadmap

### Architecture (Planned)
- [ ] sqlite-vec semantic search for KnowledgeBase (Phase 1)
- [ ] Port Evolution Engine from EvoClaw (Phase 2)
- [ ] Universal Memory Bus — enterprise edition (Phase 2)
- [ ] Enterprise Agent Identity Layer (Phase 2)
- [ ] Enterprise tool standardization / BaseTool interface (Phase 3)
- [ ] RBAC upgrade with agent roles (Phase 3)
- [ ] Matrix channel support (Phase 3)
- [ ] Merge into UnifiedClaw (Phase 3)

### Phase 1 In Progress
- [ ] sqlite-vec integration into knowledge_base.py
- [ ] Hybrid search (vector + FTS5)
- [ ] Agent fitness feedback mechanism

---

## [2.4.21] — 2026-03-18

### Added
- ARCHITECTURE.md — UnifiedClaw enterprise architecture roadmap
- SECURITY.md — Vulnerability reporting policy
- CHANGELOG.md — This file (version history)
- RELEASE.md — Release notes

### Architecture Issues Created
- 11 architecture roadmap issues (Phases 1-3)
- 3 CRITICAL security issues identified
- 5 HIGH severity issues identified

### Notes
- MinionDesk contributes: Enterprise tools (LDAP/Jira/HPC/Workflow) + RBAC
- MinionDesk gains: Evolution Engine + Universal Memory Bus (from EvoClaw)
- Target: UnifiedClaw unified framework

---

All notable changes to MinionDesk will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security
- [ ] Migrate API key injection from os.environ to ToolContext (CRITICAL)
- [ ] Add authentication to admin.py CLI
- [ ] Add LDAP TLS certificate validation
- [ ] Add WebSocket Origin validation in webportal.py

### Added
- SECURITY.md - Security vulnerability reporting policy
- CHANGELOG.md - This file

### To Be Fixed
- Bash tool: migrate from blocklist to allowlist approach
- Workflow get_status(): add RBAC authorization check
- Audit log: implement fail-hard on audit failure
- RBAC: reject unknown roles instead of silent downgrade

## [2.4.20] - 2026-03-17

### Added
- Microsoft Teams channel integration with HMAC-SHA256 verification
- IBM Notes/HCL Domino email integration
- HPC tool integrations (LSF bjobs, Slurm squeue, FlexLM lmstat)
- Minion persona system (Phil/Kevin/Stuart/Bob)
- Enterprise RBAC with LDAP/AD integration
- Knowledge base with FTS5 full-text search
- Workflow engine for expense reports, IT tickets, leave requests
- Three-tier memory system (Hot 8KB / Warm 30-day / Cold FTS5)
- Multi-provider LLM support (Claude, Gemini, OpenAI, Ollama, vLLM)
- Web portal with FastAPI + WebSocket
- Health monitoring endpoint (/health, /metrics)

### Security
- Added HMAC-SHA256 verification for Teams webhook
- Implemented prompt injection detection (immune.py)
- Added IC-specific DLP rules
- Container runs as non-root user (minion, UID 1000)
