"""M9 confirmation + settings dialogs (Qt/QGIS-only).

- ``ConfirmationDialog``: presents what/data/source/output/risks for one
  governed invocation and returns an explicit decision. Confirm binds a
  ``ConfirmationArtifact`` scoped to tool+input+context fingerprints.
- ``ApiKeyDialog``: set/clear the OpenRouter key (QSettings-backed,
  never displayed back, never logged).

Accessible: labeled inputs, default/cancel buttons, text (not color)
for risk emphasis.
"""

from __future__ import annotations

from typing import Any

from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QTextBrowser,
    QVBoxLayout,
)

from lunar_gis.agent.execution import ConfirmationArtifact
from lunar_gis.agent.registry import ToolExecutionContext, ToolRegistry


class ConfirmationDialog(QDialog):
    """Explicit confirmation for one tool invocation."""

    def __init__(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: ToolExecutionContext,
        registry: ToolRegistry,
        body: str,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._tool_name = tool_name
        self._input_data = input_data
        self._context = context
        self._registry = registry
        self.setWindowTitle(f"Confirm: {tool_name}")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        info = QTextBrowser(self)
        info.setAccessibleName("Confirmation details")
        info.setPlainText(body)
        layout.addWidget(info)
        note = QLabel("Confirm only if you understand what will happen. Provenance is audit-recorded.")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Confirm and run")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def artifact(self) -> ConfirmationArtifact | None:
        """Scoped artifact — call only after exec() returns Accepted."""
        from lunar_gis.ui.controller import make_confirmation

        return make_confirmation(self._tool_name, self._input_data, self._context, self._registry)


class ApiKeyDialog(QDialog):
    """Set or clear the OpenRouter API key (never echoed)."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("OpenRouter API key")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.key_edit = QLineEdit(self)
        self.key_edit.setAccessibleName("OpenRouter API key")
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("sk-or-… (stored locally, never logged)")
        form.addRow("API key:", self.key_edit)
        layout.addLayout(form)
        hint = QLabel("Stored in QSettings on this machine. Leave empty and confirm to clear.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def key_value(self) -> str:
        return str(self.key_edit.text()).strip()


class AssetConfirmDialog(QDialog):
    """Pick one asset and confirm its download (single dialog, full info).

    Shows dataset identity, license, and per-asset id/size. Confirm binds
    a scoped ConfirmationArtifact for data.download_dataset with the
    chosen asset — the executor rejects anything else for this artifact.
    """

    def __init__(
        self,
        provider_id: str,
        dataset_id: str,
        title: str,
        license_spdx: str,
        assets: list[dict[str, Any]],
        input_base: dict[str, Any],
        context: ToolExecutionContext,
        registry: ToolRegistry,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        from qgis.PyQt.QtWidgets import QComboBox

        self._input_base = dict(input_base)
        self._context = context
        self._registry = registry
        self.setWindowTitle("Confirm download")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        info = QTextBrowser(self)
        info.setAccessibleName("Dataset details")
        info.setPlainText(
            f"Provider: {provider_id}\nDataset: {dataset_id}\nTitle: {title}\nLicense: {license_spdx}\n\n"
            "The file downloads into a fresh sandbox, is checksum-verified, and never executes."
        )
        layout.addWidget(info)
        form = QFormLayout()
        self.asset_combo = QComboBox(self)
        self.asset_combo.setAccessibleName("Asset to download")
        for asset in assets:
            label = f"{asset.get('asset_id', '?')} ({asset.get('size_bytes', '?')} bytes)"
            self.asset_combo.addItem(label, asset.get("asset_id", ""))
        form.addRow("Asset:", self.asset_combo)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Confirm and download")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def artifact(self) -> ConfirmationArtifact | None:
        """Scoped artifact for the chosen asset — call only after Accepted."""
        from lunar_gis.ui.controller import make_confirmation

        payload = dict(self._input_base)
        payload["asset_id"] = self.asset_combo.currentData()
        return make_confirmation("data.download_dataset", payload, self._context, self._registry)

    def chosen_asset(self) -> str:
        return str(self.asset_combo.currentData() or "")


__all__ = ["ConfirmationDialog", "ApiKeyDialog", "AssetConfirmDialog"]
