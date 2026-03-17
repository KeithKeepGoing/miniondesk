# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 2.4.x   | ✅ |
| < 2.4   | ❌ |

## Reporting a Vulnerability

**Do NOT open a public GitHub Issue for security vulnerabilities.**

MinionDesk handles sensitive enterprise data (IC design, employee records, financial data). We take security very seriously.

### 🔒 Private Disclosure

Please report security issues by:
1. Opening a [GitHub Security Advisory](https://github.com/KeithKeepGoing/miniondesk/security/advisories/new)
2. Or contacting the maintainer directly

### 📋 What to Include

- Type of vulnerability (e.g., RCE, SSRF, Authentication Bypass)
- Affected component (e.g., admin.py, container/runner, workflow engine)
- Steps to reproduce
- Potential impact (especially regarding enterprise data exposure)
- Suggested fix (optional)

### ⏱️ Response Timeline

- **Initial response**: Within 48 hours
- **Status update**: Within 7 days
- **Fix timeline**: 
  - Critical (CVSS 9+): Within 7 days
  - High (CVSS 7-9): Within 14 days
  - Medium/Low: Within 30 days

### 🛡️ Security Architecture

MinionDesk is designed with enterprise security in mind:
- Agent code runs in isolated Docker containers (non-root, UID 1000)
- Teams webhook uses HMAC-SHA256 verification
- RBAC with LDAP/AD integration
- Prompt injection detection via immune.py
- IC-specific DLP rules

### Known Security Considerations

- Admin CLI (`host/admin.py`) requires direct filesystem access
- Container environment variables are used for LLM API key distribution (improvement in progress)
- Bash tool uses blocklist filtering (whitelist approach planned)

### 🏆 Acknowledgments

Responsible security disclosures will be acknowledged in our CHANGELOG.
