"""QGIS Processing algorithm for deterministic AHP pairwise analysis.

Thin orchestration layer over lunar_gis.analysis.ahp. Does NOT implement
any AHP mathematics — the deterministic engine remains the source of truth.

Public API:
  - AHPAlgorithm: QgsProcessingAlgorithm subclass
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
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsProcessingParameterString,
)

from lunar_gis.analysis.ahp import AHPError, DISPLAY_PRECISION, ahp


class AHPAlgorithm(QgsProcessingAlgorithm):
    """Deterministic AHP pairwise comparison analysis.

    Accepts a list of criteria names and a reciprocal pairwise comparison
    matrix as JSON strings. Produces priority weights, lambda-max, CI, RI,
    CR, and consistency classification.

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
    OUTPUT_WEIGHTS = "OUTPUT_WEIGHTS"
    OUTPUT_LAMBDA_MAX = "OUTPUT_LAMBDA_MAX"
    OUTPUT_CI = "OUTPUT_CI"
    OUTPUT_RI = "OUTPUT_RI"
    OUTPUT_CR = "OUTPUT_CR"
    OUTPUT_FLAG = "OUTPUT_FLAG"
    OUTPUT_RESULT_HTML = "OUTPUT_RESULT_HTML"

    def createInstance(self) -> AHPAlgorithm:
        return AHPAlgorithm()

    def name(self) -> str:
        return "ahp_pairwise"

    def displayName(self) -> str:
        return "AHP Pairwise Analysis"

    def group(self) -> str:
        return "Analysis"

    def groupId(self) -> str:
        return "analysis"

    def shortHelpString(self) -> str:
        return (
            "Deterministic Analytic Hierarchy Process (AHP) pairwise comparison analysis.\n\n"
            "Computes priority weights from a reciprocal pairwise comparison matrix "
            "using the principal right eigenvector method (Saaty 1980).\n\n"
            "Inputs:\n"
            "  Criteria: JSON array of criterion names, e.g. [\"Cost\", \"Quality\", \"Risk\"]\n"
            "  Matrix: JSON square array of arrays, e.g.\n"
            "    [[1, 3, 5],\n"
            "     [0.333333, 1, 3],\n"
            "     [0.2, 0.333333, 1]]\n\n"
            "Matrix values must be from the Saaty 1–9 scale (including reciprocals). "
            "The matrix must be square, reciprocal (a[i][j] * a[j][i] ≈ 1), "
            "with diagonal = 1.\n\n"
            "Outputs:\n"
            "  Criterion weights, lambda-max, CI, RI, CR, consistency flag, "
            "and an HTML result summary.\n\n"
            "Consistency interpretation:\n"
            "  CR ≤ 0.10: ACCEPTABLE\n"
            "  0.10 < CR ≤ 0.20: ACCEPTABLE_WITH_WARNING\n"
            "  CR > 0.20: REVISE_REQUIRED\n\n"
            "Methodology: Principal right eigenvector via power iteration. "
            "RI source: Saaty 1980. Pure deterministic calculation — "
            "no network, no AI, no QGIS layer dependency."
        )

    def tags(self) -> list[str]:
        return ["ahp", "pairwise", "analysis", "multicriteria", "weights", "deterministic"]

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
                defaultValue='[[1, 3, 5], [0.333333333333, 1, 3], [0.2, 0.333333333333, 1]]',
                optional=False,
            )
        )

        self.addOutput(QgsProcessingOutputString(self.OUTPUT_WEIGHTS, "Criterion Weights (JSON)"))
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_LAMBDA_MAX, "Lambda Max"))
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_CI, "Consistency Index (CI)"))
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_RI, "Random Index (RI)"))
        self.addOutput(QgsProcessingOutputNumber(self.OUTPUT_CR, "Consistency Ratio (CR)"))
        self.addOutput(QgsProcessingOutputString(self.OUTPUT_FLAG, "Consistency Flag"))
        self.addOutput(QgsProcessingOutputString(self.OUTPUT_RESULT_HTML, "Result Summary (HTML)"))

    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> dict[str, Any]:
        criteria_str = self.parameterAsString(parameters, self.CRITERIA, context)
        matrix_str = self.parameterAsString(parameters, self.MATRIX, context)

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
                    raise QgsProcessingException(
                        f"Matrix[{i}][{j}] must be a number, got {type(val).__name__}"
                    )

        # --- Dimension mismatch ---
        n = len(criteria)
        if len(matrix) != n:
            raise QgsProcessingException(
                f"Criteria count ({n}) does not match matrix rows ({len(matrix)})"
            )

        for i, row in enumerate(matrix):
            if len(row) != n:
                raise QgsProcessingException(
                    f"Matrix row {i} has {len(row)} columns, expected {n}"
                )

        # --- Run AHP engine ---
        try:
            result = ahp(criteria, matrix)
        except AHPError as e:
            raise QgsProcessingException(str(e)) from e

        # --- Build outputs ---
        weights_json = json.dumps(
            {c: round(w, DISPLAY_PRECISION) for c, w in zip(result.criteria, result.weights, strict=True)}
        )

        flag = result.consistency.flag.value

        # Build HTML summary
        html_parts = [
            "<h3>AHP Pairwise Analysis Result</h3>",
            "<table border='1' cellpadding='4' cellspacing='0'>",
            "<tr><th>Criterion</th><th>Weight</th></tr>",
        ]
        for c, w in zip(result.criteria, result.weights, strict=True):
            html_parts.append(
                f"<tr><td>{html.escape(c)}</td>"
                f"<td>{w:.{DISPLAY_PRECISION}f}</td></tr>"
            )
        html_parts.append("</table>")

        flag_color = {
            "ACCEPTABLE": "green",
            "ACCEPTABLE_WITH_WARNING": "orange",
            "REVISE_REQUIRED": "red",
        }.get(flag, "black")

        html_parts.extend([
            "<br><b>Consistency:</b>",
            "<table border='1' cellpadding='4' cellspacing='0'>",
            f"<tr><td>Lambda Max</td><td>{result.consistency.lambda_max:.{DISPLAY_PRECISION}f}</td></tr>",
            f"<tr><td>CI</td><td>{result.consistency.ci:.{DISPLAY_PRECISION}f}</td></tr>",
            f"<tr><td>RI ({result.consistency.ri_source})</td>"
            f"<td>{result.consistency.ri_value:.{DISPLAY_PRECISION}f}</td></tr>",
            f"<tr><td>CR</td><td>{result.consistency.cr:.{DISPLAY_PRECISION}f}</td></tr>",
            f"<tr><td>Flag</td><td style='color:{flag_color};font-weight:bold'>{flag}</td></tr>",
            f"<tr><td>Trivial Consistency</td>"
            f"<td>{'Yes' if result.consistency.trivial_consistency else 'No'}</td></tr>",
            "</table>",
            "<br><b>Provenance:</b>",
            "<table border='1' cellpadding='4' cellspacing='0'>",
            f"<tr><td>Method</td><td>{result.method}</td></tr>",
            f"<tr><td>Engine Version</td><td>{result.engine_version}</td></tr>",
            f"<tr><td>Numerical Policy</td><td>{result.numerical_policy_version}</td></tr>",
            f"<tr><td>Iterations</td><td>{result.iteration_count}</td></tr>",
            f"<tr><td>Input Hash</td><td><code>{result.input_hash[:16]}...</code></td></tr>",
            "</table>",
        ])

        result_html = "\n".join(html_parts)

        return {
            self.OUTPUT_WEIGHTS: weights_json,
            self.OUTPUT_LAMBDA_MAX: result.consistency.lambda_max,
            self.OUTPUT_CI: result.consistency.ci,
            self.OUTPUT_RI: result.consistency.ri_value,
            self.OUTPUT_CR: result.consistency.cr,
            self.OUTPUT_FLAG: flag,
            self.OUTPUT_RESULT_HTML: result_html,
        }
