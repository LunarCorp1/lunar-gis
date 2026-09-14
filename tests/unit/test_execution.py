import pytest

from lunar_gis.agent.execution import (
    ConfirmationArtifact,
    ConfirmationStatus,
    ControlledExecutor,
)
from lunar_gis.agent.governance import (
    InMemoryAuditSink,
    PermissionDecision,
    PermissionPolicy,
    PolicyDecision,
    PolicyEngine,
)
from lunar_gis.agent.registry import (
    ToolExecutionContext,
    ToolRisk,
    ToolSpec,
    ToolVersion,
    ToolRegistry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spec(name: str = "test.tool", risk: str = "read", has_handler: bool = True) -> ToolSpec:
    def handler(data: dict) -> dict:
        return {"result": data.get("x", 0) + 1}

    return ToolSpec(
        name=name,
        version=ToolVersion(1, 0, 0),
        risk=ToolRisk(risk),
        handler=handler if has_handler else None,
    )


def _registry_with(spec: ToolSpec) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(spec)
    return reg


def _ctx(session_id: str | None = None) -> ToolExecutionContext:
    return ToolExecutionContext(session_id=session_id)


def _confirmation(
    tool_name: str,
    tool_version: ToolVersion,
    input_data: dict,
    context: ToolExecutionContext,
) -> ConfirmationArtifact:
    return ConfirmationArtifact.create(tool_name, tool_version, input_data, context)


# ===========================================================================
# ConfirmationArtifact
# ===========================================================================


@pytest.mark.unit
class TestConfirmationArtifact:
    def test_create_and_matches(self) -> None:
        ctx = _ctx()
        artifact = ConfirmationArtifact.create("a.b", ToolVersion(1, 0, 0), {"x": 5}, ctx)
        assert artifact.matches("a.b", ToolVersion(1, 0, 0), {"x": 5}, ctx)

    def test_wrong_tool(self) -> None:
        ctx = _ctx()
        artifact = ConfirmationArtifact.create("a.b", ToolVersion(1, 0, 0), {"x": 5}, ctx)
        status = artifact.status_for("other.tool", ToolVersion(1, 0, 0), {"x": 5}, ctx)
        assert status == ConfirmationStatus.WRONG_TOOL

    def test_wrong_version(self) -> None:
        ctx = _ctx()
        artifact = ConfirmationArtifact.create("a.b", ToolVersion(1, 0, 0), {"x": 5}, ctx)
        status = artifact.status_for("a.b", ToolVersion(2, 0, 0), {"x": 5}, ctx)
        assert status == ConfirmationStatus.WRONG_TOOL

    def test_wrong_input(self) -> None:
        ctx = _ctx()
        artifact = ConfirmationArtifact.create("a.b", ToolVersion(1, 0, 0), {"x": 5}, ctx)
        status = artifact.status_for("a.b", ToolVersion(1, 0, 0), {"x": 99}, ctx)
        assert status == ConfirmationStatus.WRONG_INPUT

    def test_wrong_context(self) -> None:
        ctx1 = _ctx(session_id="s1")
        ctx2 = _ctx(session_id="s2")
        artifact = ConfirmationArtifact.create("a.b", ToolVersion(1, 0, 0), {"x": 5}, ctx1)
        assert artifact.matches("a.b", ToolVersion(1, 0, 0), {"x": 5}, ctx1)
        status = artifact.status_for("a.b", ToolVersion(1, 0, 0), {"x": 5}, ctx2)
        assert status == ConfirmationStatus.WRONG_CONTEXT

    def test_valid(self) -> None:
        ctx = _ctx()
        artifact = ConfirmationArtifact.create("a.b", ToolVersion(1, 0, 0), {"x": 5}, ctx)
        assert artifact.status_for("a.b", ToolVersion(1, 0, 0), {"x": 5}, ctx) == ConfirmationStatus.VALID

    def test_different_input_not_valid(self) -> None:
        ctx = _ctx()
        artifact = ConfirmationArtifact.create("a.b", ToolVersion(1, 0, 0), {"x": 5}, ctx)
        assert not artifact.matches("a.b", ToolVersion(1, 0, 0), {"x": 6}, ctx)

    def test_not_reusable_for_different_tool(self) -> None:
        ctx1 = _ctx()
        ctx2 = _ctx()
        artifact = ConfirmationArtifact.create("a.b", ToolVersion(1, 0, 0), {"x": 5}, ctx1)
        assert not artifact.matches("c.d", ToolVersion(1, 0, 0), {"x": 5}, ctx2)

    def test_canonical_json_deterministic(self) -> None:
        ctx = _ctx()
        artifact1 = ConfirmationArtifact.create("a.b", ToolVersion(1, 0, 0), {"x": 5, "y": 3}, ctx)
        artifact2 = ConfirmationArtifact.create("a.b", ToolVersion(1, 0, 0), {"y": 3, "x": 5}, ctx)
        assert artifact1.input_fingerprint == artifact2.input_fingerprint

    def test_no_secrets_in_fingerprint(self) -> None:
        ctx = _ctx()
        artifact = ConfirmationArtifact.create("a.b", ToolVersion(1, 0, 0), {"x": "secret_value"}, ctx)
        # Fingerprint is SHA-256 hex digest, not the original data
        assert len(artifact.input_fingerprint) == 64
        assert "secret_value" not in artifact.input_fingerprint

    def test_attributes(self) -> None:
        ctx = _ctx()
        artifact = ConfirmationArtifact.create("a.b", ToolVersion(1, 0, 0), {"x": 5}, ctx)
        assert artifact.tool_name == "a.b"
        assert artifact.tool_version == ToolVersion(1, 0, 0)
        assert artifact.input_fingerprint
        assert artifact.context_fingerprint


# ===========================================================================
# ControlledExecutor - successful execution
# ===========================================================================


@pytest.mark.unit
class TestControlledExecutorSuccess:
    def test_registered_tool_executes(self) -> None:
        spec = _spec("calc.add", risk="low")
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        result = executor.execute("calc.add", {"x": 5}, _ctx())
        assert result.success is True
        assert result.tool_name == "calc.add"
        assert result.output is not None

    def test_correct_output(self) -> None:
        spec = _spec("calc.add", risk="low")
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        result = executor.execute("calc.add", {"x": 5}, _ctx())
        assert result.output is not None
        assert result.output.data == {"result": 6}

    def test_handler_receives_input(self) -> None:
        received = []

        def handler(data: dict) -> dict:
            received.append(data)
            return {"result": data.get("x", 0) + 1}

        spec = ToolSpec(
            name="test.handler",
            version=ToolVersion(),
            risk=ToolRisk.LOW,
            handler=handler,
        )
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        executor.execute("test.handler", {"x": 42}, _ctx())
        assert received == [{"x": 42}]

    def test_success_audit_emitted(self) -> None:
        spec = _spec("calc.add", risk="low")
        reg = _registry_with(spec)
        sink = InMemoryAuditSink()
        executor = ControlledExecutor(registry=reg, audit_sink=sink)
        executor.execute("calc.add", {"x": 5}, _ctx())
        records = sink.records()
        assert len(records) == 2
        assert records[0].event_type == "tool_execution_started"
        assert records[1].event_type == "tool_execution_succeeded"
        assert records[1].success is True

    def test_success_audit_carries_metadata(self) -> None:
        spec = _spec("calc.add", risk="low")
        reg = _registry_with(spec)
        sink = InMemoryAuditSink()
        executor = ControlledExecutor(registry=reg, audit_sink=sink)
        executor.execute("calc.add", {"x": 5}, _ctx(session_id="sess-1"))
        records = sink.records()
        assert records[0].tool_name == "calc.add"
        assert records[0].tool_version == ToolVersion(1, 0, 0)
        assert records[0].risk == ToolRisk.LOW
        assert records[0].session_id == "sess-1"
        assert records[1].session_id == "sess-1"

    def test_low_risk_no_confirmation(self) -> None:
        spec = _spec("calc.add", risk="low")
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        result = executor.execute("calc.add", {"x": 5}, _ctx())
        assert result.success is True

    def test_medium_risk_requires_confirmation(self) -> None:
        spec = _spec("calc.modify", risk="medium")
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        result = executor.execute("calc.modify", {"x": 5}, _ctx())
        assert result.success is False
        assert result.error is not None
        assert "Confirmation required" in result.error

    def test_high_risk_requires_confirmation(self) -> None:
        spec = _spec("calc.delete", risk="high")
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        result = executor.execute("calc.delete", {}, _ctx())
        assert result.success is False
        assert result.error is not None
        assert "Confirmation required" in result.error


# ===========================================================================
# ControlledExecutor - unknown tool
# ===========================================================================


@pytest.mark.unit
class TestControlledExecutorUnknownTool:
    def test_unknown_tool_rejected(self) -> None:
        reg = ToolRegistry()
        executor = ControlledExecutor(registry=reg)
        result = executor.execute("unknown.tool", {}, _ctx())
        assert result.success is False
        assert result.error is not None
        assert "Unknown tool" in result.error

    def test_handler_not_injected_for_unknown_tool(self) -> None:
        called = False

        def handler() -> None:
            nonlocal called
            called = True

        reg = ToolRegistry()
        # Register one tool, try to execute a different one
        reg.register(ToolSpec("known.tool", ToolVersion(), ToolRisk.READ, handler))
        executor = ControlledExecutor(registry=reg)
        executor.execute("unknown.tool", {}, _ctx())
        assert called is False

    def test_unknown_tool_audited(self) -> None:
        reg = ToolRegistry()
        sink = InMemoryAuditSink()
        executor = ControlledExecutor(registry=reg, audit_sink=sink)
        executor.execute("unknown.tool", {}, _ctx(session_id="sess-2"))
        records = sink.records()
        assert len(records) == 1
        assert records[0].event_type == "tool_execution_unknown_tool"
        assert records[0].permission == PermissionDecision.DENY
        assert records[0].tool_name == "unknown.tool"
        assert records[0].success is False
        assert records[0].error == "unknown tool: unknown.tool"
        assert records[0].session_id == "sess-2"

    def test_no_network_lookup_for_unknown_tool(self) -> None:
        reg = ToolRegistry()
        executor = ControlledExecutor(registry=reg)
        result = executor.execute("nonexistent.tool", {}, _ctx())
        assert result.success is False


# ===========================================================================
# ControlledExecutor - permission denial
# ===========================================================================


@pytest.mark.unit
class TestControlledExecutorPermission:
    def test_permission_denied(self) -> None:
        spec = _spec("calc.add", risk="low")
        reg = _registry_with(spec)
        policy = PolicyEngine(permission_policy=PermissionPolicy(allowed_risks=frozenset()))
        executor = ControlledExecutor(registry=reg, policy_engine=policy)
        result = executor.execute("calc.add", {"x": 5}, _ctx())
        assert result.success is False
        assert result.error is not None
        assert "Permission denied" in result.error

    def test_deny_cannot_be_overridden_by_confirmation(self) -> None:
        from lunar_gis.agent.governance import PermissionPolicy, ConfirmationPolicy

        policy = PolicyEngine(
            permission_policy=PermissionPolicy(allowed_risks=frozenset()),
            confirmation_policy=ConfirmationPolicy(require_confirmation_risks=frozenset({ToolRisk.READ})),
        )
        spec = _spec("calc.add", risk="low")
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg, policy_engine=policy)
        artifact = ConfirmationArtifact.create("calc.add", ToolVersion(1, 0, 0), {"x": 5}, _ctx())
        result = executor.execute("calc.add", {"x": 5}, _ctx(), confirmation=artifact)
        assert result.success is False
        assert result.error is not None
        assert "Permission denied" in result.error

    def test_permission_denial_audited(self) -> None:
        from lunar_gis.agent.governance import PermissionPolicy

        spec = _spec("calc.add", risk="low")
        reg = _registry_with(spec)
        sink = InMemoryAuditSink()
        policy = PolicyEngine(permission_policy=PermissionPolicy(allowed_risks=frozenset()))
        executor = ControlledExecutor(registry=reg, policy_engine=policy, audit_sink=sink)
        executor.execute("calc.add", {"x": 5}, _ctx())
        records = sink.records()
        assert len(records) == 1
        assert records[0].event_type == "tool_execution_denied"
        assert records[0].permission == PermissionDecision.DENY
        assert records[0].success is False
        assert records[0].error == "permission denied"

    def test_handler_not_invoked_on_deny(self) -> None:
        called = False

        def handler(data: dict) -> dict:
            nonlocal called
            called = True
            return {"done": True}

        spec = ToolSpec(
            name="secret.tool",
            version=ToolVersion(),
            risk=ToolRisk.HIGH,
            handler=handler,
        )
        reg = _registry_with(spec)
        policy = PolicyEngine(permission_policy=PermissionPolicy(allowed_risks=frozenset()))
        executor = ControlledExecutor(registry=reg, policy_engine=policy)
        result = executor.execute("secret.tool", {}, _ctx())
        assert called is False
        assert result.success is False


# ===========================================================================
# ControlledExecutor - confirmation enforcement
# ===========================================================================


@pytest.mark.unit
class TestControlledExecutorConfirmation:
    def test_required_confirmation_absent(self) -> None:
        spec = _spec("calc.modify", risk="medium")
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        result = executor.execute("calc.modify", {}, _ctx())
        assert result.success is False
        assert result.error is not None
        assert "Confirmation required" in result.error

    def test_required_confirmation_wrong_tool(self) -> None:
        spec = _spec("calc.modify", risk="medium")
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        artifact = _confirmation("other.tool", ToolVersion(), {}, _ctx())
        result = executor.execute("calc.modify", {}, _ctx(), confirmation=artifact)
        assert result.success is False

    def test_required_confirmation_wrong_input(self) -> None:
        spec = _spec("calc.modify", risk="medium")
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        ctx = _ctx()
        artifact = ConfirmationArtifact.create("calc.modify", ToolVersion(1, 0, 0), {"x": 1}, ctx)
        result = executor.execute("calc.modify", {"x": 2}, ctx, confirmation=artifact)
        assert result.success is False

    def test_required_confirmation_wrong_version(self) -> None:
        spec = _spec("calc.modify", risk="medium")
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        ctx = _ctx()
        # Create artifact bound to version 2.0.0; spec is 1.0.0
        artifact = ConfirmationArtifact.create("calc.modify", ToolVersion(2, 0, 0), {"x": 5}, ctx)
        result = executor.execute("calc.modify", {"x": 5}, ctx, confirmation=artifact)
        assert result.success is False
        assert result.error is not None
        assert "Confirmation required" in result.error

    def test_valid_confirmation_allows_execution(self) -> None:
        spec = _spec("calc.modify", risk="medium")
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        ctx = _ctx()
        artifact = _confirmation("calc.modify", ToolVersion(1, 0, 0), {"x": 5}, ctx)
        result = executor.execute("calc.modify", {"x": 5}, ctx, confirmation=artifact)
        assert result.success is True

    def test_not_required_no_confirmation_needed(self) -> None:
        spec = _spec("calc.add", risk="low")
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        result = executor.execute("calc.add", {"x": 5}, _ctx())
        assert result.success is True

    def test_confirmation_not_reusable(self) -> None:
        spec = _spec("calc.modify", risk="medium")
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        ctx = _ctx()
        artifact = _confirmation("calc.modify", ToolVersion(1, 0, 0), {"x": 5}, ctx)
        # Try to use artifact for different input
        result = executor.execute("calc.modify", {"x": 99}, ctx, confirmation=artifact)
        assert result.success is False

    def test_confirmation_does_not_override_deny(self) -> None:
        from lunar_gis.agent.governance import ConfirmationPolicy

        policy = PolicyEngine(
            permission_policy=PermissionPolicy(allowed_risks=frozenset()),
            confirmation_policy=ConfirmationPolicy(require_confirmation_risks=frozenset({ToolRisk.READ})),
        )
        spec = _spec("calc.add", risk="low")
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg, policy_engine=policy)
        artifact = ConfirmationArtifact.create("calc.add", ToolVersion(1, 0, 0), {"x": 5}, _ctx())
        result = executor.execute("calc.add", {"x": 5}, _ctx(), confirmation=artifact)
        assert result.success is False
        assert result.error is not None
        assert "Permission denied" in result.error

    def test_confirmation_missing_audited(self) -> None:
        spec = _spec("calc.modify", risk="medium")
        reg = _registry_with(spec)
        sink = InMemoryAuditSink()
        executor = ControlledExecutor(registry=reg, audit_sink=sink)
        executor.execute("calc.modify", {}, _ctx())
        records = sink.records()
        assert len(records) == 1
        assert records[0].event_type == "tool_execution_confirmation_required"
        assert records[0].success is False
        assert records[0].error == "confirmation required but absent or invalid"
        assert records[0].tool_name == "calc.modify"


# ===========================================================================
# ControlledExecutor - handler errors
# ===========================================================================


@pytest.mark.unit
class TestControlledExecutorHandlerErrors:
    def test_handler_exception_becomes_failed_result(self) -> None:
        def broken_handler(data: dict) -> dict:
            raise ValueError("something went wrong")

        spec = ToolSpec(
            name="broken.tool",
            version=ToolVersion(),
            risk=ToolRisk.LOW,
            handler=broken_handler,
        )
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        result = executor.execute("broken.tool", {}, _ctx())
        assert result.success is False
        assert result.error is not None
        assert result.tool_name == "broken.tool"

    def test_handler_exception_does_not_escape(self) -> None:
        def broken_handler(data: dict) -> dict:
            raise RuntimeError("critical failure")

        spec = ToolSpec(
            name="broken.tool",
            version=ToolVersion(),
            risk=ToolRisk.LOW,
            handler=broken_handler,
        )
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        result = executor.execute("broken.tool", {}, _ctx())
        assert result.success is False

    def test_handler_failure_audited(self) -> None:
        def broken_handler(data: dict) -> dict:
            raise ValueError("boom")

        spec = ToolSpec(
            name="broken.tool",
            version=ToolVersion(),
            risk=ToolRisk.LOW,
            handler=broken_handler,
        )
        reg = _registry_with(spec)
        sink = InMemoryAuditSink()
        executor = ControlledExecutor(registry=reg, audit_sink=sink)
        executor.execute("broken.tool", {}, _ctx(session_id="sess-3"))
        records = sink.records()
        assert len(records) == 2
        assert records[0].event_type == "tool_execution_started"
        assert records[1].event_type == "tool_execution_failed"
        assert records[1].success is False
        assert records[1].error == "boom"
        assert records[1].tool_name == "broken.tool"
        assert records[1].session_id == "sess-3"

    def test_handler_none_returns_error(self) -> None:
        spec = ToolSpec(
            name="nohandler.tool",
            version=ToolVersion(),
            risk=ToolRisk.LOW,
            handler=None,
        )
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        result = executor.execute("nohandler.tool", {}, _ctx())
        assert result.success is False
        assert result.error is not None
        assert "no registered handler" in result.error


# ===========================================================================
# ControlledExecutor - input validation
# ===========================================================================


@pytest.mark.unit
class TestControlledExecutorInputValidation:
    def test_missing_required_field_rejected(self) -> None:
        schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
        spec = ToolSpec(
            name="validated.tool",
            version=ToolVersion(),
            risk=ToolRisk.LOW,
            input_schema=schema,
        )
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        result = executor.execute("validated.tool", {}, _ctx())
        assert result.success is False

    def test_valid_input_accepted(self) -> None:
        schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}

        def handler(data: dict) -> dict:
            return {"accepted": data["name"]}

        spec = ToolSpec(
            name="validated.tool",
            version=ToolVersion(),
            risk=ToolRisk.LOW,
            input_schema=schema,
            handler=handler,
        )
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        result = executor.execute("validated.tool", {"name": "test"}, _ctx())
        assert result.success is True
        assert result.output is not None
        assert result.output.data == {"accepted": "test"}

    def test_unexpected_field_rejected(self) -> None:
        schema = {"type": "object", "properties": {"name": {"type": "string"}}, "additionalProperties": False}
        spec = ToolSpec(
            name="strict.tool",
            version=ToolVersion(),
            risk=ToolRisk.LOW,
            input_schema=schema,
        )
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        result = executor.execute("strict.tool", {"name": "test", "extra": True}, _ctx())
        assert result.success is False

    def test_wrong_type_rejected(self) -> None:
        schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
        spec = ToolSpec(
            name="typed.tool",
            version=ToolVersion(),
            risk=ToolRisk.LOW,
            input_schema=schema,
        )
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        result = executor.execute("typed.tool", {"count": "not_int"}, _ctx())
        assert result.success is False

    def test_input_validation_failure_audited(self) -> None:
        schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
        called = []

        def handler(data: dict) -> dict:
            called.append(True)
            return {"ok": True}

        spec = ToolSpec(
            name="validated.tool",
            version=ToolVersion(),
            risk=ToolRisk.LOW,
            input_schema=schema,
            handler=handler,
        )
        reg = _registry_with(spec)
        sink = InMemoryAuditSink()
        executor = ControlledExecutor(registry=reg, audit_sink=sink)
        result = executor.execute("validated.tool", {}, _ctx())
        assert result.success is False
        assert called == []
        records = sink.records()
        assert len(records) == 1
        assert records[0].event_type == "tool_execution_failed"
        assert records[0].success is False


# ===========================================================================
# ControlledExecutor - audit integrity / fail-closed
# ===========================================================================


class _FailingAuditSink:
    def append(self, record: object) -> None:
        raise RuntimeError("sink down")

    def records(self) -> tuple:
        return ()

    def clear(self) -> None:
        pass


class _FailAfterFirstAuditSink:
    def __init__(self) -> None:
        self._count = 0

    def append(self, record: object) -> None:
        self._count += 1
        if self._count > 1:
            raise RuntimeError("sink down after intent record")

    def records(self) -> tuple:
        return ()

    def clear(self) -> None:
        pass


class _RaisingPolicyEngine(PolicyEngine):
    def evaluate(self, spec: object, context: object) -> PolicyDecision:
        raise RuntimeError("policy blowup")


@pytest.mark.unit
class TestControlledExecutorAuditIntegrity:
    def test_intent_audit_written_before_handler(self) -> None:
        events: list[str] = []

        def handler(data: dict) -> dict:
            events.append("handler")
            return {"ok": True}

        spec = ToolSpec("order.tool", ToolVersion(), ToolRisk.LOW, handler)
        reg = _registry_with(spec)
        sink = InMemoryAuditSink()
        executor = ControlledExecutor(registry=reg, audit_sink=sink)
        result = executor.execute("order.tool", {}, _ctx())
        assert result.success is True
        records = sink.records()
        assert len(records) == 2
        assert records[0].event_type == "tool_execution_started"
        assert records[1].event_type == "tool_execution_succeeded"

    def test_intent_audit_failure_blocks_execution(self) -> None:
        called = []

        def handler(data: dict) -> dict:
            called.append(True)
            return {"ok": True}

        spec = ToolSpec("sink.tool", ToolVersion(), ToolRisk.LOW, handler)
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg, audit_sink=_FailingAuditSink())
        result = executor.execute("sink.tool", {}, _ctx())
        assert called == []
        assert result.success is False
        assert result.error is not None
        assert "not be written before execution" in result.error

    def test_sink_failure_on_deny_does_not_raise(self) -> None:
        from lunar_gis.agent.governance import PermissionPolicy

        spec = _spec("calc.add", risk="low")
        reg = _registry_with(spec)
        policy = PolicyEngine(permission_policy=PermissionPolicy(allowed_risks=frozenset()))
        executor = ControlledExecutor(registry=reg, policy_engine=policy, audit_sink=_FailingAuditSink())
        result = executor.execute("calc.add", {"x": 5}, _ctx())
        assert result.success is False
        assert result.error is not None
        assert "Permission denied" in result.error

    def test_sink_failure_on_unknown_tool_does_not_raise(self) -> None:
        reg = ToolRegistry()
        executor = ControlledExecutor(registry=reg, audit_sink=_FailingAuditSink())
        result = executor.execute("unknown.tool", {}, _ctx())
        assert result.success is False
        assert result.error is not None
        assert "Unknown tool" in result.error

    def test_sink_failure_on_handler_error_does_not_raise(self) -> None:
        def broken_handler(data: dict) -> dict:
            raise ValueError("boom")

        spec = ToolSpec("broken.tool", ToolVersion(), ToolRisk.LOW, broken_handler)
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg, audit_sink=_FailingAuditSink())
        result = executor.execute("broken.tool", {}, _ctx())
        assert result.success is False
        assert result.error is not None

    def test_terminal_audit_failure_after_intent_returns_failure(self) -> None:
        def handler(data: dict) -> dict:
            return {"ok": True}

        spec = ToolSpec("ok.tool", ToolVersion(), ToolRisk.LOW, handler)
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg, audit_sink=_FailAfterFirstAuditSink())
        result = executor.execute("ok.tool", {}, _ctx())
        assert result.success is False
        assert result.error is not None
        assert "terminal audit record" in result.error

    def test_governance_raise_audited_with_synthesized_deny(self) -> None:
        called = []

        def handler(data: dict) -> dict:
            called.append(True)
            return {"ok": True}

        spec = ToolSpec("policy.tool", ToolVersion(), ToolRisk.LOW, handler)
        reg = _registry_with(spec)
        sink = InMemoryAuditSink()
        executor = ControlledExecutor(registry=reg, policy_engine=_RaisingPolicyEngine(), audit_sink=sink)
        result = executor.execute("policy.tool", {}, _ctx())
        assert called == []
        assert result.success is False
        records = sink.records()
        assert len(records) == 1
        assert records[0].event_type == "tool_execution_failed"
        assert records[0].permission == PermissionDecision.DENY
        assert records[0].success is False
        assert records[0].tool_name == "policy.tool"


# ===========================================================================
# ControlledExecutor - output validation
# ===========================================================================


@pytest.mark.unit
class TestControlledExecutorOutputValidation:
    def test_valid_output_succeeds(self) -> None:
        schema = {"type": "object", "properties": {"result": {"type": "integer"}}}

        def handler(data: dict) -> dict:
            return {"result": 42}

        spec = ToolSpec(
            name="output.tool",
            version=ToolVersion(),
            risk=ToolRisk.LOW,
            output_schema=schema,
            handler=handler,
        )
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        result = executor.execute("output.tool", {}, _ctx())
        assert result.success is True

    def test_no_output_schema_passes_through(self) -> None:
        def handler(data: dict) -> dict:
            return {"anything": "goes"}

        spec = ToolSpec(
            name="free.tool",
            version=ToolVersion(),
            risk=ToolRisk.LOW,
            handler=handler,
        )
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        result = executor.execute("free.tool", {}, _ctx())
        assert result.success is True

    def test_non_dict_output_normalized(self) -> None:
        def handler(data: dict) -> dict:
            return 42  # type: ignore[return-value]

        spec = ToolSpec(
            name="scalar.tool",
            version=ToolVersion(),
            risk=ToolRisk.LOW,
            handler=handler,
        )
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        result = executor.execute("scalar.tool", {}, _ctx())
        assert result.success is True
        assert result.output is not None
        assert result.output.data == {"result": 42}


# ===========================================================================
# ControlledExecutor - security regression
# ===========================================================================


@pytest.mark.unit
class TestSecurityRegression:
    def test_no_exec_in_executor(self) -> None:
        import lunar_gis.agent.execution as exec_mod

        source = exec_mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'"):
                continue
            for dangerous in ("exec(", "eval(", "compile(", "__import__("):
                assert dangerous not in stripped, f"Found {dangerous!r}"

    def test_no_subprocess_in_executor(self) -> None:
        import lunar_gis.agent.execution as exec_mod

        source = exec_mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'"):
                continue
            assert "subprocess" not in stripped
            assert "os.popen" not in stripped

    def test_no_qgis_imports(self) -> None:
        import lunar_gis.agent.execution as exec_mod

        source = exec_mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'"):
                continue
            assert "from qgis" not in stripped
            assert "import qgis" not in stripped

    def test_no_network_imports(self) -> None:
        import lunar_gis.agent.execution as exec_mod

        source = exec_mod.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'"):
                continue
            for net in ("import requests", "import urllib", "import http", "import socket"):
                assert net not in stripped

    def test_no_callable_injection(self) -> None:
        reg = ToolRegistry()
        executor = ControlledExecutor(registry=reg)
        assert not hasattr(executor, "execute_callable")
        assert not hasattr(executor, "execute_source")

    def test_handler_not_serialized_in_result(self) -> None:
        spec = _spec("test.tool", risk="low")
        reg = _registry_with(spec)
        executor = ControlledExecutor(registry=reg)
        result = executor.execute("test.tool", {"x": 5}, _ctx())
        d = result.to_dict()
        assert "handler" not in d

    def test_no_handler_invoked_on_unknown_tool(self) -> None:
        called = False

        def handler() -> None:
            nonlocal called
            called = True

        reg = ToolRegistry()
        reg.register(ToolSpec("known.tool", ToolVersion(), ToolRisk.READ, handler))
        executor = ControlledExecutor(registry=reg)
        executor.execute("unknown.tool", {}, _ctx())
        assert called is False
