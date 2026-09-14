# tests/fixtures

Deterministic test fixtures for unit and integration tests.

* Unit fakes for QGIS duck-typing live in `tests/fixtures/qgis_fakes.py` (`FakeCrs`/`FakeLayer`/`FakeProject`) — import explicitly; `tests/conftest.py` only ensures repo root on `sys.path`.
* File fixtures (small GeoPackages, rasters, JSON) belong here when needed for M1+.

Keep fixtures tiny, versioned, and offline. No network access in tests.
