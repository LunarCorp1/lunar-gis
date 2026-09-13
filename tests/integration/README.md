# tests/integration

Integration tests that require QGIS or heavier fixtures.

* Mark with `pytest.mark.qgis` or `pytest.mark.integration`.
* Keep `pytest -m "not qgis"` fast for offline deterministic runs (AGENTS.md:11).
* Use fixtures from `tests/fixtures/` — do not fetch remote data.
