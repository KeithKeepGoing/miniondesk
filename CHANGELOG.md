# Changelog

## [Unreleased] — UnifiedClaw Alignment

### Architecture (Phase 1 — Implemented)
- [x] WebSocket IPC bridge (WSBridge, port 8769)
- [x] Universal Memory Bus (SharedMemoryStore + VectorStore, ~/.miniondesk/memory.db)
- [x] Agent Identity Layer (stable SHA-256 IDs, ~/.miniondesk/agents.db)
- [ ] FitnessReporter for agent→gateway fitness feedback (Phase 2)

### Architecture (Planned — Phase 2)
- [ ] Enterprise Agent Identity Layer (LDAP DN binding)
- [ ] Cross-agent enterprise knowledge sharing
- [ ] Department knowledge auto-injection

### Added
- ARCHITECTURE alignment issues (8 issues created for UnifiedClaw phases)
- Comprehensive README with UnifiedClaw roadmap section

### Fixed (In Progress)
- See Issues #193-#209 for active security/architecture fixes

---

## [2.4.20] — 2026-03-17

### Added
- Microsoft Teams integration with HMAC-SHA256 verification
- IBM Notes/HCL Domino email integration
- LSF/Slurm HPC job management tools
- FlexLM EDA license monitoring
- Minion persona system (Phil/Kevin/Stuart/Bob)
- Workflow engine (expense, IT ticket, leave request)
- SECURITY.md — vulnerability reporting policy

### Security
- HMAC-SHA256 Teams webhook verification
- Non-root container execution (minion, UID 1000)
- IC-specific DLP rules
- 17 security/architecture issues tracked

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
