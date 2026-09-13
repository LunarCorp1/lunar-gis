# Testing

Use when writing `tests/` for deterministic behavior.

## When to use

* Adding `tests/unit/` or `tests/integration/` for `project/context.py`, `agent/registry.py`, or future deterministic GIS

## Must do

* Follow `AGENTS.md:21-33` workflow — implement → targeted tests → full gate → review.
* Keep tests offline deterministic (`pytest -q` without QGIS) with fakes (`tests/conftest.py` `ROOT` insertion, `FakeLayer`/`FakeProject`).
* Cover `lunar_gis/project/context.py` branches (`geometryType`, `featureCount`, `crs().authid`) and `lunar_gis/agent/registry.py` validation (duplicate, invalid risk, unknown tool).
* Mark QGIS-only integration as `pytest.mark.qgis` / `pytest.mark.integration`; document `tests/fixtures/README.md`.

## References

* `AGENTS.md`, `docs/architecture/MILESTONES.md`, `tests/unit/test_packaging.py` (packaging gate), `tests/conftest.py`

## Checklist

* [ ] `python -m pytest -q` passes without QGIS
* [ ] No network, no secrets in tests
