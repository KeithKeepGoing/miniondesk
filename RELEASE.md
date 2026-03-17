# Release Notes

## MinionDesk v2.5.0 — UnifiedClaw Enterprise Phase 1 Preview (Upcoming)

### Overview
This upcoming release begins MinionDesk's integration into the **UnifiedClaw** unified framework, with focus on knowledge enhancement and enterprise tool standardization.

### Planned Features

#### Knowledge Base Enhancement (Phase 1)
- `sqlite-vec` integration for semantic/vector search
- Hybrid search combining vector similarity + FTS5 keywords
- Embedding via Gemini text-embedding-004 API

#### Agent Fitness Feedback
- Agent runtime reports response quality scores back to Gateway
- Foundation for Evolution Engine integration (Phase 2)

#### MemoryBus Interface
- Unified memory access interface (preview)
- Scope: private / department / company

### Architecture Evolution

```
v2.x (Current)                    v3.x (UnifiedClaw Target)
──────────────────                ─────────────────────────
FTS5-only KB search        →      Hybrid: vector + FTS5
Isolated group memory      →      Universal Memory Bus
No evolution engine        →      Evolution Engine (from EvoClaw)
Basic RBAC (3 roles)       →      Unified RBAC (+ agent roles)
5 channels                 →      7+ channels (+ Matrix)
Ad-hoc tool interface      →      EnterpriseTool standard
```

---

## MinionDesk v2.4.21 — 2026-03-18

### Summary
Documentation and architecture planning release.

### Changes
- **Docs**: Added ARCHITECTURE.md with UnifiedClaw enterprise roadmap
- **Docs**: Added SECURITY.md with vulnerability reporting policy
- **Docs**: Added CHANGELOG.md version history
- **Docs**: Added RELEASE.md
- **Tracking**: 17 security issues created (3 Critical, 5 High, 5 Medium)
- **Tracking**: 11 architecture roadmap issues created (Phases 1-3)

### Security Notes
3 CRITICAL issues require immediate attention:
- Issue #193: Admin CLI authentication
- Issue #194: API key environment variable exposure
- Issue #195: Bash tool allowlist migration

---

## MinionDesk v2.4.20 — 2026-03-17

### Summary
Major release with enterprise integrations.

### Added
- Microsoft Teams channel (HMAC-SHA256)
- IBM Notes/HCL Domino email integration
- HPC tools (LSF bjobs, Slurm squeue, FlexLM)
- Minion persona system (Phil/Kevin/Stuart/Bob)
- Enterprise RBAC with LDAP/AD
- Workflow engine (expense/IT/leave)
- Three-tier memory system
- Multi-provider LLM support

---

*NanoClaw → MinionDesk → UnifiedClaw enterprise branch*
