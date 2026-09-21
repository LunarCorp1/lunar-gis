"""M8 accessible HTML report renderer (QGIS-free, stdlib only).

Accessibility: semantic headings (h1/h2), tables with <th scope>,
sufficient-contrast palette (near-black on white), SVG charts always
paired with a text-alt table, lang attribute, skip link, no
color-only meaning (values printed alongside swatches).

All dynamic strings are HTML-escaped (T2 untrusted metadata).
No JavaScript, no external assets, no network — a report file is
self-contained and archivable.
"""

from __future__ import annotations

import html
from typing import Any

from lunar_gis.reports.models import ReportModel, content_identity

CSS = """
body{font-family:sans-serif;color:#1a1a1a;background:#fff;max-width:60em;margin:0 auto;padding:1em;line-height:1.5}
h1{font-size:1.6em;border-bottom:2px solid #1a1a1a}
h2{font-size:1.2em;margin-top:2em;border-bottom:1px solid #666}
table{border-collapse:collapse;margin:1em 0;max-width:100%}
th,td{border:1px solid #666;padding:.4em .6em;text-align:left}
th{background:#f0f0f0}
.warning{background:#fff8e1;border:1px solid #e69f00;padding:.5em}
code{font-size:.9em}
footer{margin-top:3em;font-size:.85em;color:#444;border-top:1px solid #999;padding-top:.5em}
.skip{position:absolute;left:-9999px}
"""


def _esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _table(headers: list[str], rows: list[list[Any]], caption: str = "") -> str:
    parts = ["<table>"]
    if caption:
        parts.append(f"<caption>{_esc(caption)}</caption>")
    parts.append("<thead><tr>" + "".join(f'<th scope="col">{_esc(h)}</th>' for h in headers) + "</tr></thead>")
    parts.append("<tbody>")
    for row in rows:
        parts.append("<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in row) + "</tr>")
    parts.append("</tbody></table>")
    return "\n".join(parts)


def _bars_svg(items: list[tuple[str, float]], title: str) -> str:
    """Simple bar chart with a text-alt table (never color-only)."""
    if not items:
        return "<p>No data.</p>"
    maximum = max((v for _, v in items), default=1.0) or 1.0
    width, bar_h, gap = 400, 18, 6
    height = len(items) * (bar_h + gap) + 10
    rects: list[str] = []
    y = 5
    for label, value in items:
        length = max(2.0, (value / maximum) * (width - 160))
        rects.append(
            f'<rect x="150" y="{y}" width="{length:.1f}" height="{bar_h}" fill="#0072B2">'
            f"<title>{_esc(label)}: {value}</title></rect>"
            f'<text x="0" y="{y + 13}" font-size="11">{_esc(label[:20])}</text>'
            f'<text x="{155 + length:.0f}" y="{y + 13}" font-size="11">{value:.3f}</text>'
        )
        y += bar_h + gap
    svg = (
        f'<svg role="img" aria-label="{_esc(title)}" width="{width}" height="{height}" '
        f'xmlns="http://www.w3.org/2000/svg">{"".join(rects)}</svg>'
    )
    alt = _table(
        ["Item", "Value"], [[label, f"{value:.4f}"] for label, value in items], caption=f"{title} (text alternative)"
    )
    return svg + "\n" + alt


def render_html(report: ReportModel) -> str:
    """Render a full accessible HTML document."""
    content = report.content
    envelope = report.envelope
    identity = content_identity(content)
    parts: list[str] = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{_esc(content.title)}</title>",
        f"<style>{CSS}</style>",
        "</head>",
        "<body>",
        '<a class="skip" href="#main">Skip to content</a>',
        f"<h1>{_esc(content.title)}</h1>",
        f"<p><strong>Request:</strong> {_esc(content.user_request)}</p>",
        '<main id="main">',
    ]
    if content.requirements:
        parts.append("<h2>Data requirements</h2>")
        rows = [
            [r.get("name", "?"), r.get("geometry", "?"), ", ".join(r.get("required_fields", []))]
            for r in content.requirements
            if isinstance(r, dict)
        ]
        parts.append(_table(["Name", "Geometry", "Required fields"], rows))
    if content.data_used:
        parts.append("<h2>Data used</h2>")
        rows = [
            [d.get("ref", "?"), d.get("kind", "?"), d.get("validation", "?")]
            for d in content.data_used
            if isinstance(d, dict)
        ]
        parts.append(_table(["Reference", "Kind", "Validation"], rows))
    if content.missing_data:
        parts.append("<h2>Missing data</h2>")
        rows = [[m.get("name", "?"), m.get("reason", "?")] for m in content.missing_data if isinstance(m, dict)]
        parts.append(_table(["Requirement", "Reason"], rows))
    if content.transformations:
        parts.append("<h2>Transformations</h2>")
        rows = [[t.get("op", "?"), t.get("output_ref", "?")] for t in content.transformations if isinstance(t, dict)]
        parts.append(_table(["Operation", "Output"], rows))
    if content.analysis:
        parts.append("<h2>Analysis</h2>")
        for entry in content.analysis:
            if not isinstance(entry, dict):
                continue
            parts.append(f"<h3>{_esc(entry.get('title', 'Analysis'))}</h3>")
            weights = entry.get("weights")
            if isinstance(weights, dict) and weights:
                items = [(str(k), float(v)) for k, v in weights.items() if isinstance(v, (int, float))]
                parts.append(_bars_svg(sorted(items, key=lambda kv: -kv[1]), "Criterion weights"))
            for key in ("lambda_max", "ci", "cr", "consistency_flag", "method"):
                if key in entry:
                    parts.append(f"<p><strong>{_esc(key)}:</strong> {_esc(entry[key])}</p>")
    if content.results:
        parts.append("<h2>Results</h2>")
        for result in content.results:
            parts.append(f"<p>{_esc(result.get('summary', result) if isinstance(result, dict) else result)}</p>")
    if content.assumptions:
        parts.append("<h2>Assumptions</h2><ul>")
        parts.extend(f"<li>{_esc(a)}</li>" for a in content.assumptions)
        parts.append("</ul>")
    if content.warnings:
        parts.append('<h2>Warnings</h2><div class="warning" role="note"><ul>')
        parts.extend(f"<li>{_esc(w)}</li>" for w in content.warnings)
        parts.append("</ul></div>")
    if content.provenance:
        parts.append("<h2>Provenance</h2>")
        rows = [
            [p.get("subject_ref", "?"), p.get("status", "?"), p.get("identity", "?")[:16] if p.get("identity") else "?"]
            for p in content.provenance
            if isinstance(p, dict)
        ]
        parts.append(_table(["Subject", "Status", "Identity (prefix)"], rows))
    if content.licenses:
        parts.append("<h2>Licenses and attribution</h2>")
        rows = [[lic.get("spdx", "?"), lic.get("attribution", "")] for lic in content.licenses if isinstance(lic, dict)]
        parts.append(_table(["SPDX", "Attribution"], rows))
    parts.append("<h2>Reproducibility</h2>")
    parts.append(f"<p>Analytical identity: <code>{identity}</code></p>")
    versions = {**content.engine_versions, **content.policy_versions}
    if versions:
        parts.append(
            _table(
                ["Component", "Version"],
                sorted([[k, v] for k, v in versions.items()]),
                caption="Engine and policy versions",
            )
        )
    parts.append("</main>")
    parts.append(
        f"<footer>Generated {_esc(envelope.generated_at)} by {_esc(envelope.generator)} "
        f"{_esc(envelope.generator_version)}. Analytical identity excludes this timestamp.</footer>"
    )
    parts.append("</body></html>")
    return "\n".join(parts)


__all__ = ["render_html"]
