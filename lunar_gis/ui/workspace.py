"""M9 Lunar GIS workspace: dockable multi-tab panel (Qt/QGIS-only).

Tabs: Assistant, Project, Data, Analysis, Results, Provenance,
Reports, Settings. Every action routes through the UI controller
(governed execution); HIGH-risk tools open a ConfirmationDialog first.
The workspace stays usable with AI disabled (offline-deterministic).

Accessibility: accessible names on inputs, text browsers for results,
keyboard-focusable controls in layout order, system palette only.
"""

from __future__ import annotations

import html
import json
from typing import Any

from qgis.PyQt.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from lunar_gis.agent.execution import ConfirmationArtifact
from lunar_gis.agent.registry import ToolExecutionContext, ToolRegistry
from lunar_gis.ui import controller as ctrl


class LunarGISWorkspace(QWidget):
    """Dockable Lunar GIS workspace."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.registry: ToolRegistry = ctrl.build_registry()
        # Assistant executor: HIGH-only confirmation per M4 §12 (search,
        # validation, analysis run with intent audit; downloads and
        # transformations always open a dialog first).
        self.executor = ctrl.create_assistant_executor(self.registry)
        self.context: ToolExecutionContext = ctrl.default_context()
        self.results_log: list[str] = []
        self.conversation: list[dict[str, str]] = []
        self.pending_high: list[dict[str, Any]] = []
        self.last_request: str = ""
        self.tabs = QTabWidget(self)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        self._build_assistant_tab()
        self._build_project_tab()
        self._build_data_tab()
        self._build_analysis_tab()
        self._build_results_tab()
        self._build_provenance_tab()
        self._build_reports_tab()
        self._build_settings_tab()
        self._refresh_ai_status()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _run(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        confirmation: ConfirmationArtifact | None = None,
    ) -> dict[str, Any]:
        needs_confirm = False
        try:
            needs_confirm = self.registry.get(tool_name).risk.value in ("high",)
        except KeyError:
            pass
        if needs_confirm and confirmation is None:
            from lunar_gis.ui.dialogs import ConfirmationDialog

            info = ctrl.confirmation_text(tool_name, input_data, self.registry)
            dialog = ConfirmationDialog(tool_name, input_data, self.context, self.registry, info.get("body", ""), self)
            if dialog.exec() != dialog.DialogCode.Accepted:
                return {"ok": False, "tool_name": tool_name, "error": "confirmation-declined"}
            confirmation = dialog.artifact()
        return ctrl.run_tool(self.executor, tool_name, input_data, self.context, confirmation)

    def _log(self, text: str) -> None:
        self.results_log.append(text)
        self.results_browser.append(text)

    def _parse_json_or(self, raw: str, what: str) -> tuple[Any | None, str]:
        try:
            return json.loads(raw), ""
        except ValueError as exc:
            return None, f"{what} is not valid JSON: {exc}"

    # ------------------------------------------------------------------
    # Assistant
    # ------------------------------------------------------------------

    def _build_assistant_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.ai_status_label = QLabel()
        self.ai_status_label.setAccessibleName("AI status")
        layout.addWidget(self.ai_status_label)
        self.chat_log = QTextBrowser()
        self.chat_log.setAccessibleName("Conversation")
        self.chat_log.setOpenExternalLinks(False)
        layout.addWidget(self.chat_log)
        row = QHBoxLayout()
        self.chat_input = QLineEdit()
        self.chat_input.setAccessibleName("Request input")
        self.chat_input.setPlaceholderText("Ask a GIS question, e.g. find suitable clinic locations…")
        self.chat_input.returnPressed.connect(self._on_send)
        send = QPushButton("Send")
        send.setAccessibleName("Send request")
        send.clicked.connect(self._on_send)
        row.addWidget(self.chat_input)
        row.addWidget(send)
        layout.addLayout(row)
        self.tabs.addTab(tab, "Assistant")

    def _refresh_ai_status(self) -> None:
        status = ctrl.ai_status()
        self.ai_status_label.setText(f"Mode: {status['mode']} (AI configured: {status['configured']})")

    def _on_send(self) -> None:
        request = self.chat_input.text().strip()
        if not request:
            return
        self.chat_log.append("<b>You:</b> " + html.escape(request))
        self.chat_input.clear()
        self.conversation.append({"role": "user", "text": request})
        if ctrl.is_affirmation(request) and self.pending_high:
            self._confirm_pending()
            return
        self.last_request = request
        plan = ctrl.plan_request(request, self.registry, history=self.conversation)
        self._render_plan(plan)

    def _render_plan(self, plan: dict[str, Any]) -> None:
        if not plan["ok"]:
            # Hard provider/config error: surface it, never mislabel as offline.
            self.chat_log.append(
                "<b>AI request failed:</b> " + ctrl.clean_display(str(plan.get("error", "unknown error")))
            )
            self.chat_log.append(
                "<i>Check Settings (API key, model) and connectivity. Offline tools remain available in their tabs.</i>"
            )
            return
        self.chat_log.append(ctrl.clean_display(plan["explanation"]))
        self.conversation.append({"role": "assistant", "text": plan["explanation"]})
        for warning in plan.get("warnings", ()):
            self.chat_log.append("<i>Note: " + ctrl.clean_display(str(warning)) + "</i>")
        for entry in plan.get("executed", ()):
            status = "ok" if entry.get("ok") else "failed"
            self.chat_log.append("<code>" + html.escape(str(entry.get("tool_name", "?"))) + ": " + status + "</code>")
            self._log(f"{entry.get('tool_name')} → {entry.get('summary', '')[:2000]}")
        for call in plan.get("tool_calls", ()):
            name = call.get("tool_name", "?")
            self.chat_log.append(
                "Proposed action (needs confirmation): <code>"
                + html.escape(name)
                + "</code> — say “yes” to confirm here, or run it from its tab."
            )
        self.pending_high = list(plan.get("tool_calls", ()))

    def _confirm_pending(self) -> None:
        """Execute pending HIGH-risk proposals via dialog confirmations,
        then run one follow-up planning round so the workflow continues."""
        remaining: list[dict[str, Any]] = []
        any_ok = False
        for call in self.pending_high:
            name = call.get("tool_name", "?")
            result = self._run(name, call.get("arguments", {}))
            status = "ok" if result.get("ok") else "failed"
            detail = self._confirm_detail(name, result)
            self.chat_log.append(
                "Confirmed action <code>" + html.escape(name) + ": " + status + "</code> — " + html.escape(detail)
            )
            self._log(f"{name} → {json.dumps(result.get('output', result), default=str)[:2000]}")
            self.conversation.append({"role": "assistant", "text": f"Confirmed action {name}: {status}. {detail}"})
            any_ok = any_ok or bool(result.get("ok"))
            if (result.get("error") or "") == "confirmation-declined":
                remaining.append(call)
                break
        self.pending_high = remaining
        if any_ok and self.last_request:
            follow = ctrl.plan_request(self.last_request, self.registry, history=self.conversation, max_rounds=1)
            self._render_plan(follow)

    @staticmethod
    def _confirm_detail(tool_name: str, result: dict[str, Any]) -> str:
        data = (result.get("output") or {}).get("data", {})
        if not result.get("ok"):
            return str(result.get("error", "failed"))
        if tool_name == "data.download_dataset":
            return (
                f"{data.get('size_bytes', '?')} bytes, sha {str(data.get('sha256', ''))[:12]}, "
                f"{data.get('sandbox_relpath', '?')}"
            )
        if tool_name == "data.load_into_project":
            return f"layer '{data.get('layer_name', '?')}' ({data.get('layer_id', '?')})"
        if tool_name == "data.run_transformation":
            outputs = data.get("outputs", [])
            return f"{len(outputs)} output(s)"
        return "done"

    # ------------------------------------------------------------------
    # Project
    # ------------------------------------------------------------------

    def _build_project_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        refresh = QPushButton("Refresh project snapshot")
        refresh.setAccessibleName("Refresh project snapshot")
        refresh.clicked.connect(self._on_refresh_project)
        layout.addWidget(refresh)
        self.project_browser = QTextBrowser()
        self.project_browser.setAccessibleName("Project inventory")
        layout.addWidget(self.project_browser)
        self.tabs.addTab(tab, "Project")

    def _on_refresh_project(self) -> None:
        result = self._run("data.describe_project", {"include_fields": True})
        output = (result.get("output") or {}).get("data", result)
        if not result["ok"]:
            self.project_browser.setPlainText(f"Snapshot failed: {result.get('error')}")
            return
        lines = [
            f"Snapshot {output.get('snapshot_id')} at {output.get('taken_at')} "
            f"({output.get('total_count')} layers, truncated={output.get('truncated')})",
            "",
        ]
        for record in output.get("records", []):
            lines.append(
                f"• {record.get('name')} [{record.get('geometry_type')}] "
                f"{record.get('crs_authid')} features={record.get('feature_count')} "
                f"storage={record.get('storage')} valid={record.get('valid')}"
            )
        self.project_browser.setPlainText("\n".join(lines))
        self._log(f"describe_project → {len(output.get('records', []))} layers")

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _build_data_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()
        self.req_edit = QTextEdit()
        self.req_edit.setAccessibleName("Data requirement JSON")
        self.req_edit.setPlainText('{"name": "req", "geometry": "Point", "required_fields": []}')
        form.addRow("Requirement (JSON):", self.req_edit)
        layout.addLayout(form)
        row = QHBoxLayout()
        check = QPushButton("Check requirement")
        check.clicked.connect(self._on_check_requirement)
        row.addWidget(check)
        layout.addLayout(row)
        prov_row = QHBoxLayout()
        self.provider_combo = QComboBox()
        self.provider_combo.setAccessibleName("Provider")
        self.provider_combo.addItems(["stac.earth-search", "osm.overpass", "osm.nominatim"])
        self.search_edit = QLineEdit()
        self.search_edit.setAccessibleName("Search query")
        self.search_edit.setPlaceholderText("place name (Nominatim) or collection (STAC)")
        search = QPushButton("Search catalog")
        search.clicked.connect(self._on_search)
        prov_row.addWidget(self.provider_combo)
        prov_row.addWidget(self.search_edit)
        prov_row.addWidget(search)
        layout.addLayout(prov_row)
        self.data_browser = QTextBrowser()
        self.data_browser.setAccessibleName("Data results")
        layout.addWidget(self.data_browser)
        self.tabs.addTab(tab, "Data")

    def _on_check_requirement(self) -> None:
        requirement, error = self._parse_json_or(self.req_edit.toPlainText(), "Requirement")
        if error:
            self.data_browser.setPlainText(error)
            return
        result = self._run("data.check_requirement", {"requirement": requirement})
        self.data_browser.setPlainText(json.dumps(result, indent=2, default=str)[:6000])
        self._log(f"check_requirement → {json.dumps(result, default=str)[:1000]}")

    def _on_search(self) -> None:
        provider_id = self.provider_combo.currentText()
        query = self.search_edit.text().strip()
        payload: dict[str, Any] = {"provider_id": provider_id}
        if provider_id == "osm.nominatim":
            payload["place"] = query or "Berlin"
        elif provider_id == "stac.earth-search":
            if query:
                payload["collection"] = query
        result = self._run("data.search_catalog", payload)
        output = (result.get("output") or {}).get("data", result)
        lines = [f"Search ok={result['ok']} total={(output.get('total') if isinstance(output, dict) else '?')}"]
        results = output.get("results", []) if isinstance(output, dict) else []
        for item in results[:20]:
            lines.append(f"• {item.get('title')} [{item.get('dataset_id')}] license={item.get('license_spdx')}")
        self.data_browser.setPlainText("\n".join(lines))

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def _build_analysis_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()
        self.ahp_criteria = QLineEdit("Cost,Quality,Risk")
        self.ahp_criteria.setAccessibleName("AHP criteria")
        self.ahp_matrix = QLineEdit("[[1,3,5],[0.333,1,3],[0.2,0.333,1]]")
        self.ahp_matrix.setAccessibleName("AHP pairwise matrix JSON")
        form.addRow("Criteria (comma-separated):", self.ahp_criteria)
        form.addRow("Matrix (JSON):", self.ahp_matrix)
        layout.addLayout(form)
        row = QHBoxLayout()
        run_ahp = QPushButton("Run AHP")
        run_ahp.clicked.connect(self._on_run_ahp)
        run_sens = QPushButton("Run sensitivity")
        run_sens.clicked.connect(self._on_run_sensitivity)
        row.addWidget(run_ahp)
        row.addWidget(run_sens)
        layout.addLayout(row)
        gis_form = QFormLayout()
        self.gis_layer = QLineEdit()
        self.gis_layer.setAccessibleName("GIS layer id")
        self.gis_layer.setPlaceholderText("layer id from Project tab")
        self.gis_param = QLineEdit("100.0")
        self.gis_param.setAccessibleName("GIS parameter")
        self.gis_op = QComboBox()
        self.gis_op.setAccessibleName("GIS operation")
        self.gis_op.addItems(["analysis.buffer", "analysis.intersection", "analysis.dissolve"])
        gis_form.addRow("Layer id:", self.gis_layer)
        gis_form.addRow("Distance / overlay id:", self.gis_param)
        gis_form.addRow("Operation:", self.gis_op)
        layout.addLayout(gis_form)
        run_gis = QPushButton("Run GIS tool")
        run_gis.clicked.connect(self._on_run_gis)
        layout.addWidget(run_gis)
        self.analysis_browser = QTextBrowser()
        self.analysis_browser.setAccessibleName("Analysis results")
        layout.addWidget(self.analysis_browser)
        self.tabs.addTab(tab, "Analysis")

    def _ahp_inputs(self) -> tuple[Any | None, str]:
        criteria = [c.strip() for c in self.ahp_criteria.text().split(",") if c.strip()]
        matrix, error = self._parse_json_or(self.ahp_matrix.text(), "Matrix")
        if error:
            return None, error
        return {"criteria": criteria, "matrix": matrix}, ""

    def _on_run_ahp(self) -> None:
        inputs, error = self._ahp_inputs()
        if error or inputs is None:
            self.analysis_browser.setPlainText(error)
            return
        result = self._run("analysis.ahp", inputs)
        self.analysis_browser.setPlainText(json.dumps(result, indent=2, default=str)[:6000])
        self._log(f"analysis.ahp → {json.dumps(result, default=str)[:1000]}")

    def _on_run_sensitivity(self) -> None:
        inputs, error = self._ahp_inputs()
        if error or inputs is None:
            self.analysis_browser.setPlainText(error)
            return
        result = self._run("analysis.ahp_sensitivity", inputs)
        self.analysis_browser.setPlainText(json.dumps(result, indent=2, default=str)[:6000])
        self._log(f"sensitivity → {json.dumps(result, default=str)[:1000]}")

    def _on_run_gis(self) -> None:
        op = self.gis_op.currentText()
        layer_id = self.gis_layer.text().strip()
        param = self.gis_param.text().strip()
        if op == "analysis.buffer":
            payload: dict[str, Any] = {"layer_id": layer_id, "distance": float(param or 0)}
        elif op == "analysis.intersection":
            payload = {"layer_id": layer_id, "overlay_layer_id": param}
        else:
            payload = {"layer_id": layer_id}
        try:
            result = self._run(op, payload)
        except ValueError as exc:
            self.analysis_browser.setPlainText(str(exc))
            return
        self.analysis_browser.setPlainText(json.dumps(result, indent=2, default=str)[:4000])
        self._log(f"{op} → {json.dumps(result, default=str)[:1000]}")

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------

    def _build_results_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.results_browser = QTextBrowser()
        self.results_browser.setAccessibleName("Results log")
        layout.addWidget(self.results_browser)
        clear = QPushButton("Clear log")
        clear.clicked.connect(self.results_browser.clear)
        layout.addWidget(clear)
        self.tabs.addTab(tab, "Results")

    # ------------------------------------------------------------------
    # Provenance
    # ------------------------------------------------------------------

    def _build_provenance_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        row = QHBoxLayout()
        self.prov_subject = QLineEdit()
        self.prov_subject.setAccessibleName("Subject reference")
        self.prov_subject.setPlaceholderText("subject ref (layer id or sandbox path)")
        lookup = QPushButton("Look up lineage")
        lookup.clicked.connect(self._on_lineage)
        row.addWidget(self.prov_subject)
        row.addWidget(lookup)
        layout.addLayout(row)
        self.prov_browser = QTextBrowser()
        self.prov_browser.setAccessibleName("Provenance lineage")
        layout.addWidget(self.prov_browser)
        self.tabs.addTab(tab, "Provenance")

    def _on_lineage(self) -> None:
        ref = self.prov_subject.text().strip()
        self.prov_browser.setPlainText(
            "Lineage is recorded per acquisition/transformation in the audit store.\n"
            f"Subject query: {ref}\n"
            "Full chain inspection (store-backed browser) resolves identities emitted by "
            "data.download_dataset / data.run_transformation / data.register_local_file."
        )

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    def _build_reports_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        form = QFormLayout()
        self.report_title = QLineEdit("Lunar GIS analysis report")
        self.report_title.setAccessibleName("Report title")
        self.report_request = QLineEdit()
        self.report_request.setAccessibleName("Report request")
        self.report_request.setPlaceholderText("original user request")
        form.addRow("Title:", self.report_title)
        form.addRow("Request:", self.report_request)
        layout.addLayout(form)
        row = QHBoxLayout()
        generate = QPushButton("Generate report")
        generate.clicked.connect(self._on_generate_report)
        row.addWidget(generate)
        layout.addLayout(row)
        self.report_browser = QTextBrowser()
        self.report_browser.setAccessibleName("Report preview")
        layout.addWidget(self.report_browser)
        self.tabs.addTab(tab, "Reports")

    def _on_generate_report(self) -> None:
        result = self._run(
            "reports.generate",
            {
                "title": self.report_title.text().strip() or "Report",
                "user_request": self.report_request.text().strip() or "—",
                "sections": {"results": [{"summary": entry[:500]} for entry in self.results_log[-10:]]},
            },
        )
        output = (result.get("output") or {}).get("data", {})
        if result["ok"]:
            self.report_browser.setHtml(output.get("html", ""))
            self._log(f"report identity: {output.get('identity')}")
        else:
            self.report_browser.setPlainText(f"Report failed: {result.get('error')}")

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _build_settings_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.settings_browser = QTextBrowser()
        self.settings_browser.setAccessibleName("Settings status")
        layout.addWidget(self.settings_browser)
        row = QHBoxLayout()
        set_key = QPushButton("Set OpenRouter API key")
        set_key.clicked.connect(self._on_set_key)
        clear_key = QPushButton("Clear API key")
        clear_key.clicked.connect(self._on_clear_key)
        refresh = QPushButton("Refresh status")
        refresh.clicked.connect(self._on_refresh_settings)
        row.addWidget(set_key)
        row.addWidget(clear_key)
        row.addWidget(refresh)
        layout.addLayout(row)
        self.tabs.addTab(tab, "Settings")
        self._on_refresh_settings()

    def _on_refresh_settings(self) -> None:
        from lunar_gis.ai import openrouter as openrouter_module

        status = ctrl.ai_status()
        lines = [
            f"AI mode: {status['mode']}",
            f"API key configured: {status['configured']}",
            "Privacy: summaries and schemas only leave this machine; raw attributes and geometry never do.",
            "Confirmations: HIGH-risk tools always require explicit confirmation.",
            "Offline: project/data/analysis/provenance/reports/cartography work without AI or network.",
        ]
        _ = openrouter_module
        self.settings_browser.setPlainText("\n".join(lines))

    def _on_set_key(self) -> None:
        from lunar_gis.ai import openrouter as openrouter_module
        from lunar_gis.ui.dialogs import ApiKeyDialog

        dialog = ApiKeyDialog(self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            value = dialog.key_value()
            if value:
                openrouter_module.store_api_key(value)
            else:
                openrouter_module.clear_api_key()
            self._on_refresh_settings()
            self._refresh_ai_status()

    def _on_clear_key(self) -> None:
        from lunar_gis.ai import openrouter as openrouter_module

        openrouter_module.clear_api_key()
        self._on_refresh_settings()
        self._refresh_ai_status()


__all__ = ["LunarGISWorkspace"]
