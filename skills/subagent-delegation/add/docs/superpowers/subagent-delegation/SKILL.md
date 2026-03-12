## Skill: Subagent Delegation

For tasks with independent subtasks, spawn parallel subagents using `schedule_task`:

### When to use:
- Multiple independent research tasks
- Parallel file processing
- Fan-out + collect patterns

### How to spawn a subagent:
```python
# Each subagent gets a FULLY SELF-CONTAINED prompt
# Include all context they need — they have no memory
tool_schedule_task(
    prompt="Analyze file X and return summary. File path: /workspace/group/...",
    schedule_type="once",
    schedule_value="now",  # immediate
)
```

### Rules:
- Each subagent prompt must be 100% self-contained
- Never rely on shared state between subagents
- Collect results by having subagents write to `/workspace/group/output/`
