# tests/fixtures

Deterministic test fixtures for unit and integration tests.

* Unit fixtures are in-memory fakes (e.g., `FakeLayer`, `FakeProject` in `tests/conftest.py`).
* File fixtures (small GeoPackages, rasters, JSON) belong here when needed for M1+.

Keep fixtures tiny, versioned, and offline. No network access in tests.
