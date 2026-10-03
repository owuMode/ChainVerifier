# Recovery

Reserved for the future LLM-assisted recovery planner.

Current implementation of recovery is deterministic (see
`core/agent/recovery.py`): retry on transient failure, fail on
permanent failure, respect `max_retries`.

When adaptive recovery is introduced (re-planning with new context
after a failure), it will use this prompt. Until then, this file is
a placeholder and is not loaded.