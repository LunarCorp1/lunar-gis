"""Tool governance layer: permission, confirmation, and audit contracts.

This module establishes deterministic permission, confirmation, and audit
policies that sit between the Tool Contract/Registry and the
ControlledExecutor.

Permission and confirmation are separate concerns:
  - permission = ALLOW does not imply confirmation has occurred
  - confirmation = REQUIRED does not imply permission was granted
  - DENY cannot be overridden by confirmation

Audit records capture security-relevant decisions for governance and
reproducibility. Audit is not telemetry.

This module is pure metadata/policy infrastructure. It does NOT execute
handlers, call Python code, make network requests, or access QGIS GUI.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from lunar_gis.agent.registry import (
    ToolExecutionContext,
    ToolRisk,
    ToolSpec,
    ToolVersion,
)


# ---------------------------------------------------------------------------
# Permission decision
# ---------------------------------------------------------------------------


class PermissionDecision(Enum):
    """Whether a tool invocation is allowed under the current policy."""

    ALLOW = "allow"
    DENY = "deny"


# ---------------------------------------------------------------------------
# Confirmation decision
# ---------------------------------------------------------------------------


class ConfirmationDecision(Enum):
    """Whether explicit user confirmation is required before execution.

    confirmation_required = True does NOT imply confirmation has occurred.
    This distinction is critical: a caller must never interpret REQUIRED
    as "already confirmed."
    """

    NOT_REQUIRED = "not_required"
    REQUIRED = "required"


# ---------------------------------------------------------------------------
# Policy decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyDecision:
    """Combined policy decision for a tool invocation.

    Immutable and JSON-serializable for audit purposes.
    Does NOT contain handler callables, secrets, or arbitrary Python objects.
    """

    permission: PermissionDecision
    confirmation: ConfirmationDecision
    reason: str
    tool_name: str
    tool_version: ToolVersion
    risk: ToolRisk

    def to_dict(self) -> dict[str, Any]:
        return {
            "permission": self.permission.value,
            "confirmation": self.confirmation.value,
            "reason": self.reason,
            "tool_name": self.tool_name,
            "tool_version": self.tool_version.to_dict(),
            "risk": self.risk.value,
        }


# ---------------------------------------------------------------------------
# Audit record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditRecord:
    """Structured audit record for a security-relevant policy decision.

    Captures metadata-oriented decision information. Does NOT log API keys,
    passwords, credentials, raw tool inputs, complete datasets, or sensitive
    project contents. Audit is not telemetry.
    """

    event_type: str
    timestamp: float
    tool_name: str
    tool_version: ToolVersion
    risk: ToolRisk
    permission: PermissionDecision
    confirmation: ConfirmationDecision
    reason: str
    session_id: str | None = None
    success: bool | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "tool_name": self.tool_name,
            "tool_version": self.tool_version.to_dict(),
            "risk": self.risk.value,
            "permission": self.permission.value,
            "confirmation": self.confirmation.value,
            "reason": self.reason,
        }
        if self.session_id is not None:
            result["session_id"] = self.session_id
        if self.success is not None:
            result["success"] = self.success
        if self.error is not None:
            result["error"] = self.error
        return result


# ---------------------------------------------------------------------------
# Audit sink protocol and in-memory implementation
# ---------------------------------------------------------------------------


@runtime_checkable
class AuditSink(Protocol):
    """Protocol for audit record storage.

    Future persistence layers (database, file, remote) implement this protocol.
    The in-memory implementation is sufficient for testing and M1 scope.
    """

    def append(self, record: AuditRecord) -> None:
        """Append an audit record to the sink."""
        ...

    def records(self) -> tuple[AuditRecord, ...]:
        """Return all stored records in order."""
        ...

    def clear(self) -> None:
        """Remove all stored records."""
        ...


class InMemoryAuditSink:
    """In-memory audit sink for testing and M1 scope.

    Not persistent. Not thread-safe. Intentionally minimal.
    """

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    def append(self, record: AuditRecord) -> None:
        if not isinstance(record, AuditRecord):
            raise TypeError(f"Expected AuditRecord, got {type(record).__name__}")
        self._records.append(record)

    def records(self) -> tuple[AuditRecord, ...]:
        return tuple(self._records)

    def clear(self) -> None:
        self._records.clear()


# ---------------------------------------------------------------------------
# Permission policy
# ---------------------------------------------------------------------------


class PermissionPolicy:
    """Evaluates whether a tool invocation is permitted.

    Pure/deterministic: no side effects, no network, no QGIS GUI access.
    The policy inspects the ToolSpec and context to produce a decision.
    """

    def __init__(self, *, allowed_risks: frozenset[ToolRisk] | None = None) -> None:
        self._allowed_risks = (
            allowed_risks
            if allowed_risks is not None
            else frozenset({ToolRisk.READ, ToolRisk.LOW, ToolRisk.MEDIUM, ToolRisk.HIGH})
        )

    def evaluate(self, spec: ToolSpec, context: ToolExecutionContext) -> PolicyDecision:
        """Evaluate permission for a tool invocation.

        Returns a PolicyDecision with permission=ALLOW or DENY plus a reason.
        """
        if not isinstance(spec, ToolSpec):
            return PolicyDecision(
                permission=PermissionDecision.DENY,
                confirmation=ConfirmationDecision.NOT_REQUIRED,
                reason=f"Invalid tool specification: expected ToolSpec, got {type(spec).__name__}",
                tool_name="unknown",
                tool_version=ToolVersion(),
                risk=ToolRisk.READ,
            )

        if spec.risk not in self._allowed_risks:
            return PolicyDecision(
                permission=PermissionDecision.DENY,
                confirmation=ConfirmationDecision.NOT_REQUIRED,
                reason=f"Risk level {spec.risk.value!r} is not permitted by policy",
                tool_name=spec.name,
                tool_version=spec.version,
                risk=spec.risk,
            )

        return PolicyDecision(
            permission=PermissionDecision.ALLOW,
            confirmation=ConfirmationDecision.NOT_REQUIRED,
            reason=f"Risk level {spec.risk.value!r} is permitted by policy",
            tool_name=spec.name,
            tool_version=spec.version,
            risk=spec.risk,
        )


# ---------------------------------------------------------------------------
# Confirmation policy
# ---------------------------------------------------------------------------


class ConfirmationPolicy:
    """Evaluates whether explicit user confirmation is required.

    Pure/deterministic: no side effects, no network, no QGIS GUI access.
    Confirmation is a separate concern from permission.

    The default policy:
      - READ: NOT_REQUIRED
      - LOW: NOT_REQUIRED
      - MEDIUM: REQUIRED
      - HIGH: REQUIRED
    """

    def __init__(
        self,
        *,
        require_confirmation_risks: frozenset[ToolRisk] | None = None,
    ) -> None:
        self._require_confirmation = (
            require_confirmation_risks
            if require_confirmation_risks is not None
            else frozenset({ToolRisk.MEDIUM, ToolRisk.HIGH})
        )

    def evaluate(self, spec: ToolSpec, context: ToolExecutionContext) -> ConfirmationDecision:
        """Evaluate whether confirmation is required for a tool invocation."""
        if not isinstance(spec, ToolSpec):
            return ConfirmationDecision.REQUIRED

        if spec.risk in self._require_confirmation:
            return ConfirmationDecision.REQUIRED

        return ConfirmationDecision.NOT_REQUIRED


# ---------------------------------------------------------------------------
# Policy engine (combined)
# ---------------------------------------------------------------------------


class PolicyEngine:
    """Orchestrates permission and confirmation policies into a combined decision.

    Pure/deterministic: no side effects, no execution, no network, no QGIS GUI.
    The ControlledExecutor consumes the PolicyDecision.
    """

    def __init__(
        self,
        *,
        permission_policy: PermissionPolicy | None = None,
        confirmation_policy: ConfirmationPolicy | None = None,
    ) -> None:
        self._permission = permission_policy or PermissionPolicy()
        self._confirmation = confirmation_policy or ConfirmationPolicy()

    def evaluate(self, spec: ToolSpec, context: ToolExecutionContext) -> PolicyDecision:
        """Evaluate the combined permission and confirmation policy.

        Permission is evaluated first. If denied, confirmation is NOT_REQUIRED
        (DENY cannot be overridden by confirmation).
        """
        perm = self._permission.evaluate(spec, context)

        if perm.permission == PermissionDecision.DENY:
            return perm

        confirm = self._confirmation.evaluate(spec, context)

        return PolicyDecision(
            permission=PermissionDecision.ALLOW,
            confirmation=confirm,
            reason=f"Risk level {spec.risk.value!r}: allowed"
            + (", confirmation required" if confirm == ConfirmationDecision.REQUIRED else ""),
            tool_name=spec.name,
            tool_version=spec.version,
            risk=spec.risk,
        )

    def audit(
        self,
        decision: PolicyDecision,
        *,
        event_type: str = "policy_evaluation",
        session_id: str | None = None,
        success: bool | None = None,
        error: str | None = None,
    ) -> AuditRecord:
        """Create an audit record from a policy decision."""
        return AuditRecord(
            event_type=event_type,
            timestamp=time.time(),
            tool_name=decision.tool_name,
            tool_version=decision.tool_version,
            risk=decision.risk,
            permission=decision.permission,
            confirmation=decision.confirmation,
            reason=decision.reason,
            session_id=session_id,
            success=success,
            error=error,
        )
