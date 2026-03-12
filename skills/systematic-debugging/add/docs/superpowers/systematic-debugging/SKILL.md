## Skill: Systematic Debugging

When debugging issues, follow this protocol:

### Phase 1: Root Cause Investigation
- Reproduce the error reliably
- Read the FULL error message and stack trace
- Identify the exact line and function where failure occurs

### Phase 2: Hypothesis Formation
- List 2-3 possible root causes
- Rank by probability

### Phase 3: Evidence Gathering
- Add targeted logging or print statements
- Run tests to confirm/deny each hypothesis
- Check git log for recent changes

### Phase 4: Fix & Verify
- Implement the minimal fix
- Verify the original error is gone
- Verify no regressions introduced
- Remove debug logging

NEVER guess-and-patch. Always understand before fixing.
