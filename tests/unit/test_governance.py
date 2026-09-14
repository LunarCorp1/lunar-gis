import json
import time

import pytest

from lunar_gis.agent.governance import (
    AuditRecord,
    AuditSink,
    ConfirmationDecision,
    ConfirmationPolicy,
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
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spec(name: str = "test.tool", risk: str = "read") -> ToolSpec:
    return ToolSpec(name=name, version=ToolVersion(1, 0, 0), risk=ToolRisk(risk))


def _ctx(session_id: str | None = None) -> ToolExecutionContext:
    return ToolExecutionContext(session_id=session_id)


def noop() -> None:
    return None


# ===========================================================================
# PermissionDecision
# ===========================================================================


@pytest.mark.unit
class TestPermissionDecision:
    def test_allow_value(self) -> None:
        assert PermissionDecision.ALLOW.value == "allow"

    def test_deny_value(self) -> None:
        assert PermissionDecision.DENY.value == "deny"

    def test_two_members(self) -> None:
        assert len(PermissionDecision) == 2


# ===========================================================================
# ConfirmationDecision
# ===========================================================================


@pytest.mark.unit
class TestConfirmationDecision:
    def test_not_required_value(self) -> None:
        assert ConfirmationDecision.NOT_REQUIRED.value == "not_required"

    def test_required_value(self) -> None:
        assert ConfirmationDecision.REQUIRED.value == "required"

    def test_two_members(self) -> None:
        assert len(ConfirmationDecision) == 2


# ===========================================================================
# PolicyDecision
# ===========================================================================


@pytest.mark.unit
class TestPolicyDecision:
    def test_construction(self) -> None:
        d = PolicyDecision(
            permission=PermissionDecision.ALLOW,
            confirmation=ConfirmationDecision.NOT_REQUIRED,
            reason="read allowed",
            tool_name="a.b",
            tool_version=ToolVersion(1, 0, 0),
            risk=ToolRisk.READ,
        )
        assert d.permission == PermissionDecision.ALLOW
        assert d.confirmation == ConfirmationDecision.NOT_REQUIRED
        assert d.reason == "read allowed"

    def test_to_dict(self) -> None:
        d = PolicyDecision(
            permission=PermissionDecision.DENY,
            confirmation=ConfirmationDecision.REQUIRED,
            reason="denied",
            tool_name="x.y",
            tool_version=ToolVersion(2, 1, 0),
            risk=ToolRisk.HIGH,
        )
        result = d.to_dict()
        assert result["permission"] == "deny"
        assert result["confirmation"] == "required"
        assert result["reason"] == "denied"
        assert result["tool_name"] == "x.y"
        assert result["tool_version"] == {"major": 2, "minor": 1, "patch": 0}
        assert result["risk"] == "high"

    def test_json_serializable(self) -> None:
        d = PolicyDecision(
            permission=PermissionDecision.ALLOW,
            confirmation=ConfirmationDecision.REQUIRED,
            reason="test",
            tool_name="a.b",
            tool_version=ToolVersion(),
            risk=ToolRisk.MEDIUM,
        )
        serialized = json.dumps(d.to_dict())
        assert isinstance(serialized, str)

    def test_frozen(self) -> None:
        d = PolicyDecision(
            permission=PermissionDecision.ALLOW,
            confirmation=ConfirmationDecision.NOT_REQUIRED,
            reason="x",
            tool_name="a.b",
            tool_version=ToolVersion(),
            risk=ToolRisk.READ,
        )
        with pytest.raises(AttributeError):
            d.permission = PermissionDecision.DENY  # type: ignore[misc]

    def test_deny_with_required_is_valid(self) -> None:
        d = PolicyDecision(
            permission=PermissionDecision.DENY,
            confirmation=ConfirmationDecision.REQUIRED,
            reason="denied",
            tool_name="a.b",
            tool_version=ToolVersion(),
            risk=ToolRisk.HIGH,
        )
        assert d.permission == PermissionDecision.DENY
        assert d.confirmation == ConfirmationDecision.REQUIRED


# ===========================================================================
# AuditRecord
# ===========================================================================


@pytest.mark.unit
class TestAuditRecord:
    def test_construction(self) -> None:
        r = AuditRecord(
            event_type="policy_evaluation",
            timestamp=1000.0,
            tool_name="a.b",
            tool_version=ToolVersion(1, 0, 0),
            risk=ToolRisk.READ,
            permission=PermissionDecision.ALLOW,
            confirmation=ConfirmationDecision.NOT_REQUIRED,
            reason="allowed",
        )
        assert r.event_type == "policy_evaluation"
        assert r.timestamp == 1000.0

    def test_to_dict_full(self) -> None:
        r = AuditRecord(
            event_type="test",
            timestamp=1234.5,
            tool_name="x.y",
            tool_version=ToolVersion(2, 0, 0),
            risk=ToolRisk.HIGH,
            permission=PermissionDecision.DENY,
            confirmation=ConfirmationDecision.REQUIRED,
            reason="denied",
            session_id="sess-123",
            success=False,
        )
        d = r.to_dict()
        assert d["event_type"] == "test"
        assert d["timestamp"] == 1234.5
        assert d["tool_name"] == "x.y"
        assert d["session_id"] == "sess-123"
        assert d["success"] is False

    def test_to_dict_optional_fields_omitted(self) -> None:
        r = AuditRecord(
            event_type="test",
            timestamp=0.0,
            tool_name="a.b",
            tool_version=ToolVersion(),
            risk=ToolRisk.READ,
            permission=PermissionDecision.ALLOW,
            confirmation=ConfirmationDecision.NOT_REQUIRED,
            reason="ok",
        )
        d = r.to_dict()
        assert "session_id" not in d
        assert "success" not in d
        assert "error" not in d

    def test_to_dict_includes_error_field(self) -> None:
        r = AuditRecord(
            event_type="tool_execution_failed",
            timestamp=0.0,
            tool_name="a.b",
            tool_version=ToolVersion(),
            risk=ToolRisk.READ,
            permission=PermissionDecision.ALLOW,
            confirmation=ConfirmationDecision.NOT_REQUIRED,
            reason="ok",
            error="handler failed",
        )
        d = r.to_dict()
        assert d["error"] == "handler failed"

    def test_json_serializable(self) -> None:
        r = AuditRecord(
            event_type="test",
            timestamp=time.time(),
            tool_name="a.b",
            tool_version=ToolVersion(),
            risk=ToolRisk.READ,
            permission=PermissionDecision.ALLOW,
            confirmation=ConfirmationDecision.NOT_REQUIRED,
            reason="ok",
        )
        serialized = json.dumps(r.to_dict())
        assert isinstance(serialized, str)

    def test_frozen(self) -> None:
        r = AuditRecord(
            event_type="test",
            timestamp=0.0,
            tool_name="a.b",
            tool_version=ToolVersion(),
            risk=ToolRisk.READ,
            permission=PermissionDecision.ALLOW,
            confirmation=ConfirmationDecision.NOT_REQUIRED,
            reason="ok",
        )
        with pytest.raises(AttributeError):
            r.event_type = "other"  # type: ignore[misc]

    def test_no_secrets_in_record(self) -> None:
        r = AuditRecord(
            event_type="test",
            timestamp=0.0,
            tool_name="a.b",
            tool_version=ToolVersion(),
            risk=ToolRisk.READ,
            permission=PermissionDecision.ALLOW,
            confirmation=ConfirmationDecision.NOT_REQUIRED,
            reason="ok",
        )
        d = r.to_dict()
        serialized = json.dumps(d)
        for word in ("api_key", "secret", "password", "token", "credential"):
            assert word not in serialized

    def test_no_handler_in_record(self) -> None:
        r = AuditRecord(
            event_type="test",
            timestamp=0.0,
            tool_name="a.b",
            tool_version=ToolVersion(),
            risk=ToolRisk.READ,
            permission=PermissionDecision.ALLOW,
            confirmation=ConfirmationDecision.NOT_REQUIRED,
            reason="ok",
        )
        d = r.to_dict()
        assert "handler" not in d


# ===========================================================================
# InMemoryAuditSink
# ===========================================================================


@pytest.mark.unit
class TestInMemoryAuditSink:
    def test_append_and_retrieve(self) -> None:
        sink = InMemoryAuditSink()
        r = AuditRecord(
            event_type="test",
            timestamp=0.0,
            tool_name="a.b",
            tool_version=ToolVersion(),
            risk=ToolRisk.READ,
            permission=PermissionDecision.ALLOW,
            confirmation=ConfirmationDecision.NOT_REQUIRED,
            reason="ok",
        )
        sink.append(r)
        assert len(sink.records()) == 1
        assert sink.records()[0] is r

    def test_records_returns_tuple(self) -> None:
        sink = InMemoryAuditSink()
        assert sink.records() == ()

    def test_clear(self) -> None:
        sink = InMemoryAuditSink()
        r = AuditRecord(
            event_type="test",
            timestamp=0.0,
            tool_name="a.b",
            tool_version=ToolVersion(),
            risk=ToolRisk.READ,
            permission=PermissionDecision.ALLOW,
            confirmation=ConfirmationDecision.NOT_REQUIRED,
            reason="ok",
        )
        sink.append(r)
        sink.clear()
        assert sink.records() == ()

    def test_rejects_non_audit_record(self) -> None:
        sink = InMemoryAuditSink()
        with pytest.raises(TypeError, match="Expected AuditRecord"):
            sink.append("not a record")  # type: ignore[arg-type]

    def test_multiple_records_order(self) -> None:
        sink = InMemoryAuditSink()
        r1 = AuditRecord(
            event_type="first",
            timestamp=0.0,
            tool_name="a.b",
            tool_version=ToolVersion(),
            risk=ToolRisk.READ,
            permission=PermissionDecision.ALLOW,
            confirmation=ConfirmationDecision.NOT_REQUIRED,
            reason="ok",
        )
        r2 = AuditRecord(
            event_type="second",
            timestamp=1.0,
            tool_name="a.b",
            tool_version=ToolVersion(),
            risk=ToolRisk.READ,
            permission=PermissionDecision.ALLOW,
            confirmation=ConfirmationDecision.NOT_REQUIRED,
            reason="ok",
        )
        sink.append(r1)
        sink.append(r2)
        assert len(sink.records()) == 2
        assert sink.records()[0].event_type == "first"
        assert sink.records()[1].event_type == "second"

    def test_implements_audit_sink_protocol(self) -> None:
        sink = InMemoryAuditSink()
        assert isinstance(sink, AuditSink)


# ===========================================================================
# PermissionPolicy
# ===========================================================================


@pytest.mark.unit
class TestPermissionPolicy:
    def test_read_allowed(self) -> None:
        policy = PermissionPolicy()
        decision = policy.evaluate(_spec(risk="read"), _ctx())
        assert decision.permission == PermissionDecision.ALLOW

    def test_low_allowed(self) -> None:
        policy = PermissionPolicy()
        decision = policy.evaluate(_spec(risk="low"), _ctx())
        assert decision.permission == PermissionDecision.ALLOW

    def test_medium_allowed(self) -> None:
        policy = PermissionPolicy()
        decision = policy.evaluate(_spec(risk="medium"), _ctx())
        assert decision.permission == PermissionDecision.ALLOW

    def test_high_allowed(self) -> None:
        policy = PermissionPolicy()
        decision = policy.evaluate(_spec(risk="high"), _ctx())
        assert decision.permission == PermissionDecision.ALLOW

    def test_all_risks_have_reason(self) -> None:
        policy = PermissionPolicy()
        for risk in ("read", "low", "medium", "high"):
            d = policy.evaluate(_spec(risk=risk), _ctx())
            assert d.reason

    def test_custom_policy_denies_high(self) -> None:
        policy = PermissionPolicy(allowed_risks=frozenset({ToolRisk.READ, ToolRisk.LOW}))
        d = policy.evaluate(_spec(risk="high"), _ctx())
        assert d.permission == PermissionDecision.DENY
        assert "not permitted" in d.reason

    def test_custom_policy_allows_read_only(self) -> None:
        policy = PermissionPolicy(allowed_risks=frozenset({ToolRisk.READ}))
        assert policy.evaluate(_spec(risk="read"), _ctx()).permission == PermissionDecision.ALLOW
        assert policy.evaluate(_spec(risk="low"), _ctx()).permission == PermissionDecision.DENY
        assert policy.evaluate(_spec(risk="medium"), _ctx()).permission == PermissionDecision.DENY
        assert policy.evaluate(_spec(risk="high"), _ctx()).permission == PermissionDecision.DENY

    def test_deny_has_tool_info(self) -> None:
        policy = PermissionPolicy(allowed_risks=frozenset({ToolRisk.READ}))
        d = policy.evaluate(_spec(name="x.y", risk="high"), _ctx())
        assert d.tool_name == "x.y"
        assert d.risk == ToolRisk.HIGH

    def test_invalid_spec_denied(self) -> None:
        policy = PermissionPolicy()
        d = policy.evaluate("not a spec", _ctx())  # type: ignore[arg-type]
        assert d.permission == PermissionDecision.DENY
        assert "Invalid" in d.reason

    def test_policy_does_not_execute_handler(self) -> None:
        call_count = 0

        def counting_handler() -> None:
            nonlocal call_count
            call_count += 1

        policy = PermissionPolicy()
        spec = ToolSpec(
            name="a.b",
            version=ToolVersion(),
            risk=ToolRisk.READ,
            handler=counting_handler,
        )
        policy.evaluate(spec, _ctx())
        assert call_count == 0

    def test_to_dict_includes_policy_info(self) -> None:
        policy = PermissionPolicy()
        d = policy.evaluate(_spec(risk="low"), _ctx()).to_dict()
        assert "permission" in d
        assert "confirmation" in d
        assert "reason" in d


# ===========================================================================
# ConfirmationPolicy
# ===========================================================================


@pytest.mark.unit
class TestConfirmationPolicy:
    def test_read_not_required(self) -> None:
        policy = ConfirmationPolicy()
        d = policy.evaluate(_spec(risk="read"), _ctx())
        assert d == ConfirmationDecision.NOT_REQUIRED

    def test_low_not_required(self) -> None:
        policy = ConfirmationPolicy()
        d = policy.evaluate(_spec(risk="low"), _ctx())
        assert d == ConfirmationDecision.NOT_REQUIRED

    def test_medium_required(self) -> None:
        policy = ConfirmationPolicy()
        d = policy.evaluate(_spec(risk="medium"), _ctx())
        assert d == ConfirmationDecision.REQUIRED

    def test_high_required(self) -> None:
        policy = ConfirmationPolicy()
        d = policy.evaluate(_spec(risk="high"), _ctx())
        assert d == ConfirmationDecision.REQUIRED

    def test_custom_policy_read_requires_confirmation(self) -> None:
        policy = ConfirmationPolicy(require_confirmation_risks=frozenset({ToolRisk.READ}))
        assert policy.evaluate(_spec(risk="read"), _ctx()) == ConfirmationDecision.REQUIRED

    def test_custom_policy_high_does_not_require(self) -> None:
        policy = ConfirmationPolicy(require_confirmation_risks=frozenset({ToolRisk.MEDIUM}))
        assert policy.evaluate(_spec(risk="high"), _ctx()) == ConfirmationDecision.NOT_REQUIRED

    def test_invalid_spec_requires_confirmation(self) -> None:
        policy = ConfirmationPolicy()
        d = policy.evaluate("not a spec", _ctx())  # type: ignore[arg-type]
        assert d == ConfirmationDecision.REQUIRED

    def test_confirmation_does_not_imply_permission(self) -> None:
        perm_policy = PermissionPolicy(allowed_risks=frozenset({ToolRisk.READ}))
        confirm_policy = ConfirmationPolicy()
        perm_d = perm_policy.evaluate(_spec(risk="high"), _ctx())
        confirm_d = confirm_policy.evaluate(_spec(risk="high"), _ctx())
        assert perm_d.permission == PermissionDecision.DENY
        assert confirm_d == ConfirmationDecision.REQUIRED


# ===========================================================================
# PolicyEngine
# ===========================================================================


@pytest.mark.unit
class TestPolicyEngine:
    def test_read_allow_not_required(self) -> None:
        engine = PolicyEngine()
        d = engine.evaluate(_spec(risk="read"), _ctx())
        assert d.permission == PermissionDecision.ALLOW
        assert d.confirmation == ConfirmationDecision.NOT_REQUIRED

    def test_low_allow_not_required(self) -> None:
        engine = PolicyEngine()
        d = engine.evaluate(_spec(risk="low"), _ctx())
        assert d.permission == PermissionDecision.ALLOW
        assert d.confirmation == ConfirmationDecision.NOT_REQUIRED

    def test_medium_allow_required(self) -> None:
        engine = PolicyEngine()
        d = engine.evaluate(_spec(risk="medium"), _ctx())
        assert d.permission == PermissionDecision.ALLOW
        assert d.confirmation == ConfirmationDecision.REQUIRED

    def test_high_allow_required(self) -> None:
        engine = PolicyEngine()
        d = engine.evaluate(_spec(risk="high"), _ctx())
        assert d.permission == PermissionDecision.ALLOW
        assert d.confirmation == ConfirmationDecision.REQUIRED

    def test_deny_overrides_confirmation(self) -> None:
        engine = PolicyEngine(permission_policy=PermissionPolicy(allowed_risks=frozenset({ToolRisk.READ})))
        d = engine.evaluate(_spec(risk="high"), _ctx())
        assert d.permission == PermissionDecision.DENY
        assert d.confirmation == ConfirmationDecision.NOT_REQUIRED

    def test_deny_with_custom_confirmation_policy(self) -> None:
        engine = PolicyEngine(
            permission_policy=PermissionPolicy(allowed_risks=frozenset({ToolRisk.READ})),
            confirmation_policy=ConfirmationPolicy(require_confirmation_risks=frozenset({ToolRisk.READ})),
        )
        d = engine.evaluate(_spec(risk="high"), _ctx())
        assert d.permission == PermissionDecision.DENY
        assert d.confirmation == ConfirmationDecision.NOT_REQUIRED

    def test_deny_all_risk_levels(self) -> None:
        engine = PolicyEngine(permission_policy=PermissionPolicy(allowed_risks=frozenset()))
        for risk in ("read", "low", "medium", "high"):
            d = engine.evaluate(_spec(risk=risk), _ctx())
            assert d.permission == PermissionDecision.DENY
            assert d.confirmation == ConfirmationDecision.NOT_REQUIRED
            assert "not permitted" in d.reason

    def test_invalid_spec_at_engine_level(self) -> None:
        engine = PolicyEngine()
        d = engine.evaluate("not a spec", _ctx())  # type: ignore[arg-type]
        assert d.permission == PermissionDecision.DENY

    def test_audit_denied_decision(self) -> None:
        engine = PolicyEngine(permission_policy=PermissionPolicy(allowed_risks=frozenset()))
        decision = engine.evaluate(_spec(risk="high"), _ctx())
        record = engine.audit(decision)
        assert record.permission == PermissionDecision.DENY
        assert record.tool_name == "test.tool"

    def test_audit_with_success_true(self) -> None:
        engine = PolicyEngine()
        decision = engine.evaluate(_spec(risk="read"), _ctx())
        record = engine.audit(decision, success=True)
        assert record.success is True

    def test_all_combinations(self) -> None:
        engine = PolicyEngine()
        for risk in ("read", "low", "medium", "high"):
            d = engine.evaluate(_spec(risk=risk), _ctx())
            assert d.permission == PermissionDecision.ALLOW
            if risk in ("medium", "high"):
                assert d.confirmation == ConfirmationDecision.REQUIRED
            else:
                assert d.confirmation == ConfirmationDecision.NOT_REQUIRED

    def test_engine_has_reason(self) -> None:
        engine = PolicyEngine()
        d = engine.evaluate(_spec(risk="high"), _ctx())
        assert "high" in d.reason
        assert "confirmation required" in d.reason

    def test_engine_to_dict(self) -> None:
        engine = PolicyEngine()
        d = engine.evaluate(_spec(risk="low"), _ctx())
        result = d.to_dict()
        assert result["permission"] == "allow"
        assert result["confirmation"] == "not_required"

    def test_audit_record_from_decision(self) -> None:
        engine = PolicyEngine()
        decision = engine.evaluate(_spec(risk="read"), _ctx())
        record = engine.audit(decision, session_id="s1")
        assert record.tool_name == "test.tool"
        assert record.permission == PermissionDecision.ALLOW
        assert record.session_id == "s1"
        assert record.timestamp > 0

    def test_audit_record_optional_fields(self) -> None:
        engine = PolicyEngine()
        decision = engine.evaluate(_spec(risk="medium"), _ctx())
        record = engine.audit(decision)
        assert record.session_id is None
        assert record.success is None
        assert record.error is None

    def test_audit_record_with_error(self) -> None:
        engine = PolicyEngine()
        decision = engine.evaluate(_spec(risk="medium"), _ctx())
        record = engine.audit(decision, success=False, error="handler blew up")
        assert record.success is False
        assert record.error == "handler blew up"

    def test_engine_does_not_execute_handler(self) -> None:
        call_count = 0

        def counting_handler() -> None:
            nonlocal call_count
            call_count += 1

        engine = PolicyEngine()
        spec = ToolSpec(
            name="a.b",
            version=ToolVersion(),
            risk=ToolRisk.READ,
            handler=counting_handler,
        )
        engine.evaluate(spec, _ctx())
        assert call_count == 0


# ===========================================================================
# Security regression tests
# ===========================================================================


@pytest.mark.unit
class TestSecurityRegression:
    def test_no_exec_in_governance(self) -> None:
        import lunar_gis.agent.governance as gov

        source = gov.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'"):
                continue
            for dangerous in ("exec(", "eval(", "compile(", "__import__("):
                assert dangerous not in stripped, f"Found {dangerous!r} in governance module: {stripped}"

    def test_no_network_in_governance(self) -> None:
        import lunar_gis.agent.governance as gov

        source = gov.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'"):
                continue
            for net in ("import requests", "import urllib", "import http", "import socket", "import aiohttp"):
                assert net not in stripped, f"Found {net!r} in governance module: {stripped}"

    def test_no_qgis_imports_in_governance(self) -> None:
        import lunar_gis.agent.governance as gov

        source = gov.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'"):
                continue
            for qgis in ("from qgis", "import qgis"):
                assert qgis not in stripped, f"Found {qgis!r} in governance module: {stripped}"

    def test_policy_engine_no_exec_method(self) -> None:
        engine = PolicyEngine()
        assert not hasattr(engine, "execute")
        assert not hasattr(engine, "run")
        assert not hasattr(engine, "invoke")
        assert not hasattr(engine, "call")

    def test_permission_policy_no_exec_method(self) -> None:
        policy = PermissionPolicy()
        assert not hasattr(policy, "execute")
        assert not hasattr(policy, "run")

    def test_confirmation_policy_no_exec_method(self) -> None:
        policy = ConfirmationPolicy()
        assert not hasattr(policy, "execute")
        assert not hasattr(policy, "run")

    def test_audit_record_no_secrets(self) -> None:
        r = AuditRecord(
            event_type="test",
            timestamp=0.0,
            tool_name="a.b",
            tool_version=ToolVersion(),
            risk=ToolRisk.READ,
            permission=PermissionDecision.ALLOW,
            confirmation=ConfirmationDecision.NOT_REQUIRED,
            reason="ok",
        )
        d = r.to_dict()
        for key in d:
            assert key not in ("api_key", "token", "secret", "password", "credential", "env")

    def test_policy_decision_no_handler(self) -> None:
        d = PolicyDecision(
            permission=PermissionDecision.ALLOW,
            confirmation=ConfirmationDecision.NOT_REQUIRED,
            reason="ok",
            tool_name="a.b",
            tool_version=ToolVersion(),
            risk=ToolRisk.READ,
        )
        result = d.to_dict()
        assert "handler" not in result

    def test_in_memory_sink_no_external_io(self) -> None:
        import lunar_gis.agent.governance as gov

        source = gov.__spec__.origin or ""
        with open(source, encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'"):
                continue
            # No file I/O, no network, no subprocess
            for io_call in ("open(", "subprocess", "os.popen"):
                assert io_call not in stripped, f"Found {io_call!r} in governance module: {stripped}"
