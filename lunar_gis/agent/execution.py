"""Controlled tool execution boundary.

This module establishes the deterministic, non-LLM execution path
between the Tool Registry / Policy Engine and registered handlers.

Execution lifecycle:
  1. Resolve registered tool from registry
  2. Validate tool metadata
  3. Evaluate permission via PolicyEngine
  4. Validate input against ToolSpec input schema
  5. Evaluate confirmation requirement
  6. Verify confirmation artifact (if required)
  7. Write intent audit record BEFORE invoking the handler (fail-closed)
  8. Invoke registered handler
  9. Normalize output into ToolOutput
  10. Validate output against ToolSpec output schema
  11. Produce ToolResult
  12. Write terminal audit record (success or failure)

Audit is fail-closed: if the pre-execution intent record cannot be written,
the handler is never invoked and execution is blocked.

The executor does NOT:
  - discover tools from natural language
  - call an LLM or interpret prompts
  - make network requests
  - perform arbitrary Python execution
  - bypass the ToolRegistry or PolicyEngine
  - directly manipulate QGIS GUI state

This module is pure Python stdlib. No QGIS, no network, no AI.

Public API:
  - ConfirmationStatus: validity classification for a confirmation artifact
  - ConfirmationArtifact: explicit, scoped confirmation for one invocation
  - ControlledExecutor: the single governed execution entry point
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from lunar_gis.agent.governance import (
    AuditSink,
    ConfirmationDecision,
    InMemoryAuditSink,
    PermissionDecision,
    PolicyDecision,
    PolicyEngine,
)
from lunar_gis.agent.registry import (
    ToolExecutionContext,
    ToolInput,
    ToolOutput,
    ToolResult,
    ToolRisk,
    ToolSpec,
    ToolVersion,
    ToolRegistry,
)


# ---------------------------------------------------------------------------
# Confirmation artifact
# ---------------------------------------------------------------------------


class ConfirmationStatus(Enum):
    """Whether a confirmation artifact is valid for the intended invocation."""

    VALID = "valid"
    MISSING = "missing"
    WRONG_TOOL = "wrong_tool"
    WRONG_INPUT = "wrong_input"
    WRONG_CONTEXT = "wrong_context"


@dataclass(frozen=True)
class ConfirmationArtifact:
    """Explicit, scoped confirmation for a specific tool invocation.

    The artifact is bound to:
    * the specific tool name and version
    * a canonical fingerprint of the relevant structured input
    * a canonical fingerprint of the execution context

    It is NOT reusable for a different tool or input.
    Contains no secrets.
    """

    tool_name: str
    tool_version: ToolVersion
    input_fingerprint: str
    context_fingerprint: str

    @classmethod
    def create(
        cls,
        tool_name: str,
        tool_version: ToolVersion,
        input_data: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ConfirmationArtifact:
        """Create a confirmation artifact from structured data.

        Fingerprints are computed deterministically using SHA-256
        over canonical JSON serialization. No secrets are included.
        """
        input_json = cls._canonical_json(input_data)
        context_dict = context.to_dict()
        context_json = cls._canonical_json(context_dict)
        return cls(
            tool_name=tool_name,
            tool_version=tool_version,
            input_fingerprint=cls._fingerprint(input_json),
            context_fingerprint=cls._fingerprint(context_json),
        )

    def matches(
        self,
        tool_name: str,
        tool_version: ToolVersion,
        input_data: dict[str, Any],
        context: ToolExecutionContext,
    ) -> bool:
        """Check if this artifact matches the given invocation.

        All four binding components (tool name, tool version, canonical
        input, canonical context) must match.
        """
        if tool_name != self.tool_name:
            return False
        if tool_version != self.tool_version:
            return False
        input_json = self._canonical_json(input_data)
        context_dict = context.to_dict()
        context_json = self._canonical_json(context_dict)
        return self.input_fingerprint == self._fingerprint(
            input_json
        ) and self.context_fingerprint == self._fingerprint(context_json)

    def status_for(
        self,
        tool_name: str,
        tool_version: ToolVersion,
        input_data: dict[str, Any],
        context: ToolExecutionContext,
    ) -> ConfirmationStatus:
        """Return the confirmation status for a given invocation."""
        if not self.matches(tool_name, tool_version, input_data, context):
            if tool_name != self.tool_name or tool_version != self.tool_version:
                return ConfirmationStatus.WRONG_TOOL
            input_json = self._canonical_json(input_data)
            if self.input_fingerprint != self._fingerprint(input_json):
                return ConfirmationStatus.WRONG_INPUT
            return ConfirmationStatus.WRONG_CONTEXT
        return ConfirmationStatus.VALID

    @staticmethod
    def _canonical_json(obj: Any) -> str:
        """Produce a deterministic JSON string for fingerprinting."""
        return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def _fingerprint(s: str) -> str:
        """Compute a SHA-256 fingerprint of a canonical JSON string."""
        return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# ControlledExecutor
# ---------------------------------------------------------------------------


class ControlledExecutor:
    """Controlled tool execution boundary.

    Stateless: invocation-specific state lives in the method scope,
    not on the executor instance.

    The executor only executes handlers belonging to registered ToolSpec
    objects, only after the complete governance path passes, and only
    after all validation, permission, and confirmation checks succeed.

    Audit is fail-closed: the handler is invoked only after an intent
    audit record has been written. A sink failure before execution
    blocks execution and returns a failed ToolResult.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        policy_engine: PolicyEngine | None = None,
        audit_sink: AuditSink | None = None,
    ) -> None:
        self._registry = registry
        self._engine = policy_engine or PolicyEngine()
        self._audit_sink = audit_sink or InMemoryAuditSink()

    def execute(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: ToolExecutionContext,
        confirmation: ConfirmationArtifact | None = None,
    ) -> ToolResult:
        """Execute a registered tool through the complete governance path.

        This method is the single entry point for controlled execution.
        It enforces: resolve → validate → policy → confirm → audit-intent →
        execute → normalize → validate → result → audit-terminal.

        If any governance check fails, no handler is invoked and a
        failed ToolResult is returned. Audit sink failures never raise
        out of this method.
        """
        tool: ToolSpec | None = None
        tool_version: ToolVersion = ToolVersion()
        decision: PolicyDecision | None = None

        try:
            # Step 1: Resolve registered tool
            tool = self._registry.get(tool_name)
            tool_version = tool.version

            # Step 2: Validate tool metadata
            if not isinstance(tool, ToolSpec):
                return self._unknown_tool(tool_name, context)

            # Step 3: Evaluate permission (decision is available before the
            # value-validating steps so downstream failures can be audited)
            decision = self._engine.evaluate(tool, context)
            if decision.permission.value == "deny":
                return self._deny(tool, decision, context)

            # Step 4: Handler presence is static metadata checked before any
            # intent audit is written (a handler-less tool never started)
            if tool.handler is None:
                self._audit(
                    decision,
                    False,
                    "no registered handler",
                    context,
                    event_type="tool_execution_failed",
                )
                return ToolResult(
                    success=False,
                    error="Tool has no registered handler",
                    tool_name=tool_name,
                    tool_version=tool_version,
                )

            # Step 5: Validate input against ToolSpec input schema
            ToolInput(data=input_data, schema=tool.input_schema if tool.input_schema else {})

            # Step 6: Evaluate confirmation requirement
            if decision.confirmation.value == "required":
                # Step 7: Verify confirmation artifact
                if confirmation is None:
                    return self._confirmation_missing(tool, decision, context)
                status = confirmation.status_for(tool_name, tool_version, input_data, context)
                if status != ConfirmationStatus.VALID:
                    return self._confirmation_missing(tool, decision, context)

            # Step 8: Fail-closed intent audit BEFORE invoking the handler.
            # If the intent record cannot be written, execution is blocked.
            if not self._audit(
                decision,
                None,
                None,
                context,
                event_type="tool_execution_started",
            ):
                return ToolResult(
                    success=False,
                    error="Audit record could not be written before execution; execution blocked",
                    tool_name=tool_name,
                    tool_version=tool_version,
                )

            # Step 9: Invoke registered handler
            handler_output = tool.handler(input_data)

            # Step 10: Normalize output into ToolOutput
            output = ToolOutput(data=handler_output if isinstance(handler_output, dict) else {"result": handler_output})

            # Step 11: Validate output against ToolSpec output schema
            if tool.output_schema:
                output = ToolOutput(data=output.data, schema=tool.output_schema)

            # Step 12: Produce ToolResult
            result = ToolResult(
                success=True,
                output=output,
                tool_name=tool_name,
                tool_version=tool_version,
            )

            # Step 13: Write terminal audit record (non-blocking if it fails;
            # the intent record already guarantees fail-closed behavior)
            if not self._audit(
                decision,
                True,
                None,
                context,
                event_type="tool_execution_succeeded",
            ):
                return ToolResult(
                    success=False,
                    error="Handler succeeded but the terminal audit record could not be written",
                    tool_name=tool_name,
                    tool_version=tool_version,
                )
            return result

        except KeyError:
            # Unknown tool — no handler execution
            return self._unknown_tool(tool_name, context)
        except Exception as exc:
            # Handler or unexpected error — convert to failed ToolResult.
            # A governance-internal failure before a decision was formed
            # (e.g. a custom policy raised) is audited with a synthesized
            # DENY decision so no governance failure goes unrecorded.
            safe_reason = str(exc) if isinstance(exc, (ValueError, TypeError)) else "handler execution failed"
            if decision is not None:
                self._audit(
                    decision,
                    False,
                    safe_reason,
                    context,
                    event_type="tool_execution_failed",
                )
            elif isinstance(tool, ToolSpec):
                synth = PolicyDecision(
                    permission=PermissionDecision.DENY,
                    confirmation=ConfirmationDecision.NOT_REQUIRED,
                    reason=f"Governance evaluation failed before a decision could be formed: {safe_reason}",
                    tool_name=tool.name,
                    tool_version=tool.version,
                    risk=tool.risk,
                )
                self._audit(
                    synth,
                    False,
                    safe_reason,
                    context,
                    event_type="tool_execution_failed",
                )
            return ToolResult(
                success=False,
                error=safe_reason,
                tool_name=tool_name,
                tool_version=tool_version,
            )

    def _deny(
        self,
        tool: ToolSpec,
        decision: PolicyDecision,
        context: ToolExecutionContext,
    ) -> ToolResult:
        """Handle permission denial: no handler execution, audit the denial."""
        self._audit(
            decision,
            False,
            "permission denied",
            context,
            event_type="tool_execution_denied",
        )
        return ToolResult(
            success=False,
            error=f"Permission denied: {decision.reason}",
            tool_name=tool.name,
            tool_version=tool.version,
        )

    def _confirmation_missing(
        self,
        tool: ToolSpec,
        decision: PolicyDecision,
        context: ToolExecutionContext,
    ) -> ToolResult:
        """Handle missing confirmation: no handler execution, audit."""
        self._audit(
            decision,
            False,
            "confirmation required but absent or invalid",
            context,
            event_type="tool_execution_confirmation_required",
        )
        return ToolResult(
            success=False,
            error=f"Confirmation required: {decision.reason}",
            tool_name=tool.name,
            tool_version=tool.version,
        )

    def _unknown_tool(self, tool_name: str, context: ToolExecutionContext) -> ToolResult:
        """Handle unknown tool: no handler execution, audit."""
        decision = PolicyDecision(
            permission=PermissionDecision.DENY,
            confirmation=ConfirmationDecision.NOT_REQUIRED,
            reason=f"Unknown tool: {tool_name}",
            tool_name=tool_name,
            tool_version=ToolVersion(),
            risk=ToolRisk.READ,
        )
        self._audit(
            decision,
            False,
            f"unknown tool: {tool_name}",
            context,
            event_type="tool_execution_unknown_tool",
        )
        return ToolResult(
            success=False,
            error=f"Unknown tool: {tool_name}",
            tool_name=tool_name,
            tool_version=ToolVersion(),
        )

    def _audit(
        self,
        decision: PolicyDecision,
        success: bool | None,
        error: str | None,
        context: ToolExecutionContext,
        event_type: str = "policy_evaluation",
    ) -> bool:
        """Write an audit record for the execution outcome.

        Returns True if the record was written, False if the sink failed.
        Never raises: a sink failure must not escape execute().
        """
        if decision is None:
            return True
        try:
            record = self._engine.audit(
                decision,
                event_type=event_type,
                session_id=context.session_id,
                success=success,
                error=error,
            )
            self._audit_sink.append(record)
            return True
        except Exception:
            return False
