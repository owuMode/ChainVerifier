# tests/unit/test_agent_policies.py
from core.agent.policies import AgentPolicy, FailureKind
from core.tasks.models import Task


def _task(**overrides) -> Task:
    base = dict(
        task_id="t",
        status="CREATED",
        goal="x",
        max_steps=3,
        max_retries=1,
        max_model_calls=5,
    )
    base.update(overrides)
    return Task(**base)


def test_classify_transient():
    assert AgentPolicy.classify_failure("network_error", "") is FailureKind.TRANSIENT
    assert AgentPolicy.classify_failure(None, "connection reset by peer") is FailureKind.TRANSIENT


def test_classify_permanent():
    assert AgentPolicy.classify_failure("policy_denied", "") is FailureKind.PERMANENT
    assert AgentPolicy.classify_failure("validation_error", "") is FailureKind.PERMANENT
    assert AgentPolicy.classify_failure(None, "missing required field") is FailureKind.PERMANENT


def test_classify_unknown():
    assert AgentPolicy.classify_failure(None, None) is FailureKind.UNKNOWN
    assert AgentPolicy.classify_failure("weird", "something") is FailureKind.UNKNOWN


def test_can_retry():
    t = _task()
    assert AgentPolicy.can_retry(t)
    t.retry_count = 1
    assert not AgentPolicy.can_retry(t)


def test_should_retry_rules():
    t = _task()
    assert AgentPolicy.should_retry(t, FailureKind.TRANSIENT)
    assert not AgentPolicy.should_retry(t, FailureKind.PERMANENT)