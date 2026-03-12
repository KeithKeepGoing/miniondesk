## Skill: Verification Before Completion

NEVER claim a task is complete without running verification.

### For code changes:
1. Run syntax check: `python3 -m py_compile {file}.py`
2. Run existing tests: `python3 -m pytest tests/ -x -q`
3. Run a quick smoke test of the changed functionality

### For file operations:
1. Confirm the file exists: `ls -la {path}`
2. Check file contents are correct: `head -20 {file}`

### For database changes:
1. Query the affected table to confirm changes
2. Check no data corruption

Only after passing all checks, report: "✅ Task complete. Verified: {what was verified}"
