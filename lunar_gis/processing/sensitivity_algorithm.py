"""QGIS Processing algorithm for deterministic AHP sensitivity analysis.

Thin orchestration layer over lunar_gis.analysis.sensitivity. Does NOT
implement any sensitivity mathematics — the deterministic engine remains
the source of truth.

Public API:
  - AHPSensitivityAlgorithm: QgsProcessingAlgorithm subclass
"""

from __future__ import annotations

import json
import html
from typing import Any

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingOutputString,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
)

from lunar_gis.analysis.sensitivity import SensitivityError, sensitivity_ahp


class AHPSensitivityAlgorithm(QgsProcessingAlgorithm):
    """Deterministic AHP sensitivity analysis.

    Accepts a list of criteria names and a reciprocal pairwise comparison
    matrix as JSON strings, plus optional sensitivity configuration.
    Produces per-criterion stability intervals, crossover points, and
    perturbed ranking scenarios via OAT weight perturbation.

    Matrix format (JSON): square array of arrays of numbers.
    Criteria format (JSON): array of strings.

    The matrix must be reciprocal with diagonal 1. Values must be from the
    Saaty 1–9 scale (including reciprocals like 1/3, 1/7, etc.).

    Example criteria: ["Cost", "Quality", "Risk"]
    Example matrix:
    [[1, 3, 5],
     [0.3333333333333333, 1, 3],
     [0.2, 0.3333333333333333, 1]]
    """

    CRITERIA = "CRITERIA"
    MATRIX = "MATRIX"
    METHOD = "METHOD"
    PERTURBATION_RANGE = "PERTURBATION_RANGE"
    NUM_STEPS = "NUM_STEPS"
    TARGET_CRITERIA = "TARGET_CRITERIA"
    OUTPUT_RESULT = "OUTPUT_RESULT"
    OUTPUT_RESULT_HTML = "OUTPUT_RESULT_HTML"

    def createInstance(self) -> AHPSensitivityAlgorithm:
        return AHPSensitivityAlgorithm()

    def name(self) -> str:
        return "ahp_sensitivity"

    def displayName(self) -> str:
        return "AHP Sensitivity Analysis"

    def group(self) -> str:
        return "Analysis"

    def groupId(self) -> str:
        return "analysis"

    def shortHelpString(self) -> str:
        return (
            "Deterministic Analytic Hierarchy Process (AHP) sensitivity analysis.\n\n"
            "Performs one-at-a-time (OAT) weight perturbation to compute "
            "stability intervals, crossover points, and perturbed ranking "
            "scenarios for each criterion.\n\n"
            "Inputs:\n"
            '  Criteria: JSON array of criterion names, e.g. ["Cost", "Quality", "Risk"]\n'
            "  Matrix: JSON square array of arrays, e.g.\n"
            "    [[1, 3, 5],\n"
            "     [0.333333, 1, 3],\n"
            "     [0.2, 0.333333, 1]]\n"
            '  Method: "OAT_WEIGHT" (default)\n'
            "  Perturbation Range: JSON array [min, max], e.g. [-0.3, 0.3]\n"
            "  Num Steps: number of sweep steps (5–100, default 20)\n"
            '  Target Criteria: JSON array of criterion names to analyze, or "" for all\n\n'
            "Matrix values must be from the Saaty 1–9 scale (including reciprocals). "
            "The matrix must be square, reciprocal (a[i][j] * a[j][i] ≈ 1), "
            "with diagonal = 1.\n\n"
            "Outputs:\n"
            "  Full sensitivity result as JSON, plus an HTML summary.\n"
            "  The JSON contains baseline weights, ranking, per-criterion "
            "stability intervals, crossover points, perturbed scenarios, "
            "consistency information, and provenance metadata.\n\n"
            "Methodology: OAT weight perturbation with deterministic ranking. "
            "Pure deterministic calculation — no network, no AI, no QGIS "
            "layer dependency."
        )

    def tags(self) -> list[str]:
        return [
            "ahp",
            "sensitivity",
            "analysis",
            "multicriteria",
            "stability",
            "crossover",
            "deterministic",
        ]

    def initAlgorithm(self, config: dict[str, Any] | None = None) -> None:
        self.addParameter(
            QgsProcessingParameterString(
                self.CRITERIA,
                "Criteria (JSON array)",
                defaultValue='["Criterion A", "Criterion B", "Criterion C"]',
                optional=False,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.MATRIX,
                "Pairwise Matrix (JSON array of arrays)",
                defaultValue="[[1, 3, 5], [0.333333333333, 1, 3], [0.2, 0.333333333333, 1]]",
                optional=False,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.METHOD,
                "Sensitivity Method",
                defaultValue="OAT_WEIGHT",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.PERTURBATION_RANGE,
                "Perturbation Range (JSON [min, max])",
                defaultValue="[-0.3, 0.3]",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.NUM_STEPS,
                "Number of Steps",
                type=QgsProcessingParameterNumber.Integer,
                defaultValue=20,
                minValue=5,
                maxValue=100,
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.TARGET_CRITERIA,
                "Target Criteria (JSON array, or empty for all)",
                defaultValue="",
                optional=True,
            )
        )

        self.addOutput(QgsProcessingOutputString(self.OUTPUT_RESULT, "Sensitivity Result (JSON)"))
        self.addOutput(QgsProcessingOutputString(self.OUTPUT_RESULT_HTML, "Result Summary (HTML)"))

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:
        criteria_str = self.parameterAsString(parameters, self.CRITERIA, context)
        matrix_str = self.parameterAsString(parameters, self.MATRIX, context)
        method_str = self.parameterAsString(parameters, self.METHOD, context)
        perturbation_range_str = self.parameterAsString(parameters, self.PERTURBATION_RANGE, context)
        num_steps = self.parameterAsInt(parameters, self.NUM_STEPS, context)
        target_criteria_str = self.parameterAsString(parameters, self.TARGET_CRITERIA, context)

        feedback.pushInfo("Parsing input parameters...")

        # --- Parse criteria ---
        try:
            criteria = json.loads(criteria_str)
        except json.JSONDecodeError as e:
            raise QgsProcessingException(f"Criteria is not valid JSON: {e}") from e

        if not isinstance(criteria, list):
            raise QgsProcessingException("Criteria must be a JSON array of strings")

        for i, c in enumerate(criteria):
            if not isinstance(c, str) or not c.strip():
                raise QgsProcessingException(f"Criteria[{i}] must be a non-empty string")

        # --- Parse matrix ---
        try:
            matrix = json.loads(matrix_str)
        except json.JSONDecodeError as e:
            raise QgsProcessingException(f"Matrix is not valid JSON: {e}") from e

        if not isinstance(matrix, list):
            raise QgsProcessingException("Matrix must be a JSON array of arrays")

        for i, row in enumerate(matrix):
            if not isinstance(row, list):
                raise QgsProcessingException(f"Matrix row {i} must be an array")
            for j, val in enumerate(row):
                if not isinstance(val, (int, float)):
                    raise QgsProcessingException(f"Matrix[{i}][{j}] must be a number, got {type(val).__name__}")

        # --- Dimension mismatch ---
        n = len(criteria)
        if len(matrix) != n:
            raise QgsProcessingException(f"Criteria count ({n}) does not match matrix rows ({len(matrix)})")

        for i, row in enumerate(matrix):
            if len(row) != n:
                raise QgsProcessingException(f"Matrix row {i} has {len(row)} columns, expected {n}")

        # --- Parse optional parameters ---
        method = method_str.strip() if method_str.strip() else "OAT_WEIGHT"

        perturbation_range: tuple[float, float] = (-0.3, 0.3)
        if perturbation_range_str.strip():
            try:
                pr = json.loads(perturbation_range_str)
            except json.JSONDecodeError as e:
                raise QgsProcessingException(f"Perturbation Range is not valid JSON: {e}") from e
            if not isinstance(pr, list) or len(pr) != 2:
                raise QgsProcessingException("Perturbation Range must be a JSON array of two numbers [min, max]")
            if not all(isinstance(v, (int, float)) for v in pr):
                raise QgsProcessingException("Perturbation Range values must be numbers")
            perturbation_range = (float(pr[0]), float(pr[1]))

        target_criteria: list[str] | None = None
        if target_criteria_str.strip():
            try:
                tc = json.loads(target_criteria_str)
            except json.JSONDecodeError as e:
                raise QgsProcessingException(f"Target Criteria is not valid JSON: {e}") from e
            if not isinstance(tc, list):
                raise QgsProcessingException("Target Criteria must be a JSON array of strings")
            for i, c in enumerate(tc):
                if not isinstance(c, str) or not c.strip():
                    raise QgsProcessingException(f"Target Criteria[{i}] must be a non-empty string")
            target_criteria = [str(c) for c in tc]

        # --- Run sensitivity engine ---
        feedback.pushInfo("Running sensitivity analysis...")

        try:
            result = sensitivity_ahp(
                criteria,
                matrix,
                method=method,
                perturbation_range=perturbation_range,
                num_steps=num_steps,
                target_criteria=target_criteria,
            )
        except SensitivityError as e:
            raise QgsProcessingException(f"Sensitivity analysis failed: {e}") from e

        feedback.pushInfo("Building output...")

        # --- Build JSON output ---
        result_json = _serialize_result(result)

        # --- Build HTML summary ---
        result_html = _build_html(result)

        return {
            self.OUTPUT_RESULT: json.dumps(result_json, indent=2),
            self.OUTPUT_RESULT_HTML: result_html,
        }


def _serialize_result(result: Any) -> dict[str, Any]:
    """Serialize SensitivityResult into a JSON-compatible dict."""
    criterion_results = []
    for cr in result.criterion_results:
        criterion_results.append(
            {
                "criterion": cr.criterion,
                "baseline_weight": cr.baseline_weight,
                "stability_lower": cr.stability_lower,
                "stability_upper": cr.stability_upper,
                "crossover_points": list(cr.crossover_points),
                "perturbation_values": list(cr.perturbation_values),
                "perturbed_weights": [list(w) for w in cr.perturbed_weights],
                "perturbed_rankings": [list(r) for r in cr.perturbed_rankings],
                "consistency_flags": list(cr.consistency_flags),
                "consistency_ratios": list(cr.consistency_ratios),
            }
        )

    output: dict[str, Any] = {
        "criteria": list(result.criteria),
        "baseline_weights": list(result.baseline_weights),
        "baseline_ranking": list(result.baseline_ranking),
        "criterion_results": criterion_results,
        "method": result.method.value,
        "sensitivity_policy_version": result.sensitivity_policy_version,
        "numerical_policy_version": result.numerical_policy_version,
        "engine_version": result.engine_version,
        "input_hash": result.input_hash,
        "perturbation_range": list(result.perturbation_range),
        "num_steps": result.num_steps,
        "ranking_policy_version": result.ranking_policy_version,
        "consistency_policy_version": result.consistency_policy_version,
        "near_ties": [list(pair) for pair in result.near_ties],
    }

    if result.target_criteria is not None:
        output["target_criteria"] = list(result.target_criteria)

    return output


def _build_html(result: Any) -> str:
    """Build an HTML summary of the sensitivity result."""
    parts = [
        "<h3>AHP Sensitivity Analysis Result</h3>",
        "<table border='1' cellpadding='4' cellspacing='0'>",
        "<tr><th>Criterion</th><th>Baseline Weight</th>"
        "<th>Stability Lower</th><th>Stability Upper</th>"
        "<th>Crossovers</th></tr>",
    ]
    for cr in result.criterion_results:
        crossovers_str = ", ".join(f"{c:.4f}" for c in cr.crossover_points) if cr.crossover_points else "none"
        parts.append(
            f"<tr><td>{html.escape(cr.criterion)}</td>"
            f"<td>{cr.baseline_weight:.6f}</td>"
            f"<td>{cr.stability_lower:.6f}</td>"
            f"<td>{cr.stability_upper:.6f}</td>"
            f"<td>{crossovers_str}</td></tr>"
        )
    parts.append("</table>")

    # Near-ties
    if result.near_ties:
        pairs = ", ".join(f"{a}≈{b}" for a, b in result.near_ties)
        parts.append(f"<br><b>Near-ties:</b> {html.escape(pairs)}")

    # Provenance
    parts.extend(
        [
            "<br><b>Provenance:</b>",
            "<table border='1' cellpadding='4' cellspacing='0'>",
            f"<tr><td>Method</td><td>{result.method.value}</td></tr>",
            f"<tr><td>Sensitivity Policy</td><td>{result.sensitivity_policy_version}</td></tr>",
            f"<tr><td>Numerical Policy</td><td>{result.numerical_policy_version}</td></tr>",
            f"<tr><td>Engine Version</td><td>{result.engine_version}</td></tr>",
            f"<tr><td>Input Hash</td><td><code>{result.input_hash[:16]}...</code></td></tr>",
            f"<tr><td>Perturbation Range</td><td>{list(result.perturbation_range)}</td></tr>",
            f"<tr><td>Num Steps</td><td>{result.num_steps}</td></tr>",
            f"<tr><td>Target Criteria</td><td>{result.target_criteria if result.target_criteria else 'all'}</td></tr>",
            "</table>",
        ]
    )

    return "\n".join(parts)
