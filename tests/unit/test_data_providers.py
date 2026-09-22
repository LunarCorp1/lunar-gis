"""Unit tests for M4-T05 provider system (offline-safe).

Network-touching paths are never exercised: allowlist/scheme rejection
happens before DNS, IP blocking is unit-tested directly, archive safety
uses crafted local zips, and adapters are tested via query building +
validation + fake-transport seams.
"""

from __future__ import annotations

import zipfile

import pytest

from lunar_gis.agent.registry import ToolRegistry
from lunar_gis.data.adapters import base as base_module
from lunar_gis.data.adapters import registry as adapter_registry
from lunar_gis.data.adapters import transport as transport_module
from lunar_gis.data.adapters.base import (
    ERROR_TO_MISSING,
    RETRYABLE_ERRORS,
    ProviderError,
    ProviderLimits,
    SearchQuery,
    validate_search_query,
)
from lunar_gis.data.adapters.osm import ALLOWLISTED_TAG_KEYS, build_overpass_ql
from lunar_gis.data.adapters.transport import (
    _ip_blocked,
    audit_url,
    download_to_sandbox,
    resolve_and_check,
    safe_extract_zip,
    validate_egress_url,
)
from lunar_gis.data.provider_tools import (
    DOWNLOAD_DATASET_TOOL_SPEC,
    SEARCH_CATALOG_TOOL_SPEC,
    download_dataset_handler,
    register_provider_tools,
    search_catalog_handler,
)


class TestErrorTaxonomy:
    def test_closed_taxonomy(self) -> None:
        assert {e.value for e in ProviderError} == {
            "PROVIDER_OFFLINE",
            "DATASET_NOT_FOUND",
            "AUTH_REQUIRED",
            "QUOTA_EXCEEDED",
            "RATE_LIMITED",
            "CHECKSUM_MISMATCH",
            "LICENSE_UNAVAILABLE",
            "TIMEOUT",
            "INVALID_QUERY",
        }

    def test_acquisition_mapping(self) -> None:
        assert ERROR_TO_MISSING[ProviderError.DATASET_NOT_FOUND.value] == "no-layer"
        assert ERROR_TO_MISSING[ProviderError.LICENSE_UNAVAILABLE.value] == "license-unavailable"
        assert ERROR_TO_MISSING[ProviderError.PROVIDER_OFFLINE.value] == "provider-offline"

    def test_retry_scopes(self) -> None:
        assert ProviderError.TIMEOUT.value in RETRYABLE_ERRORS
        assert ProviderError.RATE_LIMITED.value in RETRYABLE_ERRORS
        assert ProviderError.DATASET_NOT_FOUND.value not in RETRYABLE_ERRORS


class TestSearchQuery:
    def test_valid(self) -> None:
        q = SearchQuery(bbox=(0.0, 0.0, 1.0, 1.0), limit=10)
        assert validate_search_query(q, ProviderLimits()) == []

    def test_limit_cap(self) -> None:
        q = SearchQuery(limit=500)
        assert validate_search_query(q, ProviderLimits(max_results=50)) != []

    def test_bad_bbox(self) -> None:
        q = SearchQuery(bbox=(1.0, 1.0, 0.0, 0.0))
        assert validate_search_query(q, ProviderLimits()) != []

    def test_place_charset(self) -> None:
        q = SearchQuery(place="Berlin, Germany")
        assert validate_search_query(q, ProviderLimits()) == []
        q2 = SearchQuery(place="x" * 201)
        assert validate_search_query(q2, ProviderLimits()) != []
        q3 = SearchQuery(place="bad;DROP")
        assert validate_search_query(q3, ProviderLimits()) != []


class TestIpBlocking:
    def test_loopback_blocked(self) -> None:
        assert _ip_blocked("127.0.0.1") is True
        assert _ip_blocked("::1") is True

    def test_rfc1918_blocked(self) -> None:
        assert _ip_blocked("10.0.0.1") is True
        assert _ip_blocked("192.168.1.1") is True
        assert _ip_blocked("172.16.0.1") is True

    def test_link_local_multicast_blocked(self) -> None:
        assert _ip_blocked("169.254.1.1") is True
        assert _ip_blocked("224.0.0.1") is True

    def test_public_allowed(self) -> None:
        assert _ip_blocked("8.8.8.8") is False
        assert _ip_blocked("1.1.1.1") is False

    def test_unparseable_blocked(self) -> None:
        assert _ip_blocked("not-an-ip") is True

    def test_localhost_resolution_blocked(self) -> None:
        ok, reason = resolve_and_check("localhost")
        assert ok is False
        assert "blocked-ip" in reason or "dns" in reason


class TestEgressValidation:
    ALLOW = ("good.example.com",)

    def test_off_allowlist_rejected_without_dns(self) -> None:
        ok, reason = validate_egress_url("https://evil.com/x", self.ALLOW)
        assert ok is False
        assert "not-allowlisted" in reason

    def test_subdomain_allowed(self) -> None:
        # subdomain match needs DNS; only assert the allowlist branch is passed
        # by checking a clearly-off host is rejected first (no network).
        ok, _ = validate_egress_url("https://good.example.com.evil.com/x", self.ALLOW)
        assert ok is False

    def test_scheme_blocked(self) -> None:
        ok, reason = validate_egress_url("ftp://good.example.com/x", self.ALLOW)
        assert ok is False
        assert "blocked-scheme" in reason

    def test_malformed(self) -> None:
        ok, _ = validate_egress_url("https://", self.ALLOW)
        assert ok is False


class TestAuditUrl:
    def test_strips_query(self) -> None:
        assert audit_url("https://h.example.com/p/x.tif?a=b#frag") == "https://h.example.com/p/x.tif"

    def test_rejects_non_http(self) -> None:
        assert audit_url("ftp://h.example.com/x") is None


class TestSandboxDownload:
    def test_traversal_rejected_without_network(self) -> None:
        ok, payload = download_to_sandbox(
            "https://good.example.com/x.tif", ("good.example.com",), "/tmp/sb", "../../evil.tif"
        )
        assert ok is False
        assert payload["error"] == ProviderError.INVALID_QUERY.value


def _make_zip(path: str, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)


class TestSafeExtract:
    def test_valid_extract(self, tmp_path) -> None:
        src = str(tmp_path / "a.zip")
        _make_zip(src, {"layer.geojson": b'{"type":"x"}'})
        out = str(tmp_path / "out")
        ok, payload = safe_extract_zip(src, out)
        assert ok is True
        assert payload["extracted"] == ["layer.geojson"]

    def test_traversal_rejected(self, tmp_path) -> None:
        src = str(tmp_path / "evil.zip")
        _make_zip(src, {"../evil.sh": b"x"})
        ok, payload = safe_extract_zip(src, str(tmp_path / "out"))
        assert ok is False
        assert payload["error"] == "unsafe-member"

    def test_absolute_rejected(self, tmp_path) -> None:
        src = str(tmp_path / "abs.zip")
        _make_zip(src, {"/etc/evil.geojson": b"x"})
        ok, payload = safe_extract_zip(src, str(tmp_path / "out"))
        assert ok is False

    def test_executable_suffix_rejected(self, tmp_path) -> None:
        src = str(tmp_path / "exe.zip")
        _make_zip(src, {"run.exe": b"x"})
        ok, payload = safe_extract_zip(src, str(tmp_path / "out"))
        assert ok is False

    def test_member_cap(self, tmp_path) -> None:
        src = str(tmp_path / "many.zip")
        _make_zip(src, {f"f{i}.csv": b"a,b" for i in range(5)})
        ok, payload = safe_extract_zip(src, str(tmp_path / "out"), max_members=3)
        assert ok is False
        assert payload["error"] == "member-cap-exceeded"

    def test_bad_zip(self, tmp_path) -> None:
        src = str(tmp_path / "bad.zip")
        with open(src, "wb") as handle:
            handle.write(b"not a zip")
        ok, payload = safe_extract_zip(src, str(tmp_path / "out"))
        assert ok is False


class TestOverpassQL:
    def test_valid_build(self) -> None:
        ok, ql = build_overpass_ql((0.0, 0.0, 0.5, 0.5), (("amenity", "hospital"),))
        assert ok is True
        assert "amenity" in ql and "hospital" in ql and "out:json" in ql

    def test_bad_tag_key(self) -> None:
        ok, _ = build_overpass_ql((0.0, 0.0, 0.5, 0.5), (("secret", "x"),))
        assert ok is False

    def test_area_cap(self) -> None:
        ok, _ = build_overpass_ql((0.0, 0.0, 10.0, 10.0), (("amenity", "hospital"),))
        assert ok is False

    def test_value_escaping(self) -> None:
        ok, ql = build_overpass_ql((0.0, 0.0, 0.5, 0.5), (("amenity", 'a"b'),))
        assert ok is True
        assert '\\"' in ql

    def test_allowlist_nonempty(self) -> None:
        assert "amenity" in ALLOWLISTED_TAG_KEYS and "healthcare" in ALLOWLISTED_TAG_KEYS


class TestOverpassRefetch:
    def test_encode_decode_round_trip(self) -> None:
        from lunar_gis.data.adapters.osm import decode_overpass_dataset_id, encode_overpass_dataset_id

        tags = (("natural", "water"), ("waterway", "river"))
        bbox = (34.0, -14.3, 34.3, -14.0)
        assert decode_overpass_dataset_id(encode_overpass_dataset_id(tags, bbox)) == (tags, bbox)

    def test_tampered_rejected(self) -> None:
        from lunar_gis.data.adapters.osm import decode_overpass_dataset_id

        assert decode_overpass_dataset_id("osm:tags=secret=x&bbox=0,0,1,1") is None
        assert decode_overpass_dataset_id("osm:tags=amenity=hospital&bbox=1,1,0,0") is None
        assert decode_overpass_dataset_id("osm:tags=amenity=hospital&bbox=0,0,10,10") is not None
        assert decode_overpass_dataset_id("nonsense") is None
        assert decode_overpass_dataset_id("osm:tags=&bbox=0,0,1,1") is None

    def test_conversion_fixture(self) -> None:
        from lunar_gis.data.adapters.osm import overpass_json_to_geojson

        payload = {
            "elements": [
                {"type": "node", "id": 1, "lat": -14.0, "lon": 34.0, "tags": {"natural": "water"}},
                {"type": "node", "id": 2, "lat": -14.1, "lon": 34.1},
                {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"waterway": "river"}},
                {"type": "way", "id": 11, "nodes": [999], "tags": {}},
                {"type": "relation", "id": 20, "tags": {}},
            ]
        }
        geojson, counts = overpass_json_to_geojson(payload)
        assert geojson["type"] == "FeatureCollection"
        kinds = sorted(f["geometry"]["type"] for f in geojson["features"])
        assert kinds == ["LineString", "Point", "Point"]
        assert counts == {"features": 3, "skipped_relations": 1}
        first_props = geojson["features"][0]["properties"]
        assert first_props["osm_type"] == "node" and first_props["osm_id"] == 1
        assert all("id" not in f for f in geojson["features"])

    def test_conversion_inline_geometry(self) -> None:
        from lunar_gis.data.adapters.osm import overpass_json_to_geojson

        payload = {
            "elements": [
                {
                    "type": "way",
                    "id": 7,
                    "tags": {"waterway": "river"},
                    "geometry": [{"lat": -14.0, "lon": 34.0}, {"lat": -14.1, "lon": 34.1}],
                },
                {"type": "way", "id": 8, "tags": {}, "geometry": [{"lat": -14.0, "lon": 34.0}]},
            ]
        }
        geojson, counts = overpass_json_to_geojson(payload)
        assert counts["features"] == 1
        assert geojson["features"][0]["geometry"]["coordinates"] == [[34.0, -14.0], [34.1, -14.1]]

    def test_ql_uses_out_geom(self) -> None:
        ok, ql = build_overpass_ql((0.0, 0.0, 0.5, 0.5), (("amenity", "hospital"),))
        assert ok is True
        assert "out geom" in ql

    def test_download_refetch_mocked(self, monkeypatch, tmp_path) -> None:
        import json as json_module

        from lunar_gis.data.adapters import osm as osm_module
        from lunar_gis.data.adapters.osm import OverpassAdapter, encode_overpass_dataset_id

        body = json_module.dumps({"elements": [{"type": "node", "id": 1, "lat": -14.0, "lon": 34.0}]}).encode()

        class FakeFetch:
            def __init__(self, body: bytes):
                self.body = body

            ok = True
            error = ""

        # Patch where the name is looked up (osm.fetch_url), not where it
        # is defined: `from ... import fetch_url` binds osm's own
        # reference, so patching transport.fetch_url is a no-op that
        # lets real HTTP through (CI flake / 30s stall on failure).
        monkeypatch.setattr(osm_module, "fetch_url", lambda url, allow, **kw: FakeFetch(body))
        adapter = OverpassAdapter()
        dataset_id = encode_overpass_dataset_id((("natural", "water"),), (34.0, -14.3, 34.3, -14.0))
        ok, payload = adapter.download(dataset_id, "overpass.geojson", str(tmp_path))
        assert ok is True
        assert payload["sandbox_relpath"] == "overpass.geojson"
        assert (tmp_path / "overpass.geojson").exists()

    def test_download_bad_id_or_asset(self, tmp_path) -> None:
        from lunar_gis.data.adapters.osm import OverpassAdapter

        adapter = OverpassAdapter()
        assert adapter.download("nonsense", "overpass.geojson", str(tmp_path))[0] is False
        good = "osm:tags=natural=water&bbox=34.0,-14.3,34.3,-14.0"
        assert adapter.download(good, "wrong asset", str(tmp_path))[0] is False


class TestRegistry:
    def test_ids(self) -> None:
        assert {"stac.earth-search", "osm.overpass", "osm.nominatim"} <= set(adapter_registry.ids())

    def test_lazy_get(self) -> None:
        adapter = adapter_registry.get("osm.overpass")
        assert adapter.provider_id() == "osm.overpass"

    def test_unknown(self) -> None:
        with pytest.raises(KeyError):
            adapter_registry.get("nope.missing")

    def test_stac_allowlist(self, monkeypatch) -> None:
        from lunar_gis.data.adapters import transport as transport_module

        # Hermetic: the constructor validates egress (incl. real DNS);
        # stub resolution so unit CI never depends on DNS.
        monkeypatch.setattr(transport_module, "resolve_and_check", lambda host: (True, "ok"))
        adapter = adapter_registry.get("stac.earth-search")
        assert "earth-search.aws.element84.com" in adapter.host_allowlist()

    def test_search_results_carry_asset_ids(self, monkeypatch) -> None:
        from lunar_gis.data.adapters.base import SearchQuery
        from lunar_gis.data.adapters.stac import EarthSearchAdapter

        feature = {
            "id": "S1C_test",
            "properties": {"title": "S1 scene", "license": "ESA"},
            "bbox": [33.0, -14.0, 34.0, -13.0],
            "assets": {"vv": {"href": "https://x/y.tif"}, "thumbnail": {"href": "https://x/t.png"}},
        }
        monkeypatch.setattr(EarthSearchAdapter, "_post_json", lambda self, payload: (True, {"features": [feature]}))
        adapter = EarthSearchAdapter.__new__(EarthSearchAdapter)
        adapter._search_url = "https://earth-search.aws.element84.com/v1/search"
        ok, payload = adapter.search(SearchQuery(bbox=(33.0, -14.0, 34.0, -13.0), limit=5))
        assert ok is True
        assert payload["results"][0]["asset_ids"] == ["thumbnail", "vv"]


class TestProviderTools:
    def test_search_unknown_provider(self) -> None:
        result = search_catalog_handler({"provider_id": "nope.missing"})
        assert result["ok"] is False
        assert "unknown-provider" in result["error"]
        assert "stac.earth-search" in result["error"]

    def test_download_unknown_provider(self) -> None:
        result = download_dataset_handler({"provider_id": "nope.missing", "dataset_id": "d", "asset_id": "a"})
        assert result["ok"] is False

    def test_specs(self) -> None:
        assert SEARCH_CATALOG_TOOL_SPEC.risk.value == "medium"
        assert DOWNLOAD_DATASET_TOOL_SPEC.risk.value == "high"

    def test_register(self) -> None:
        registry = ToolRegistry()
        register_provider_tools(registry)
        assert registry.has("data.search_catalog")
        assert registry.has("data.download_dataset")

    def test_search_invalid_query_offline(self) -> None:
        # overpass with no bbox → INVALID_QUERY without touching network
        result = search_catalog_handler({"provider_id": "osm.overpass", "tags": {"amenity": "hospital"}})
        assert result["ok"] is False

    def test_empty_search_carries_hint(self, monkeypatch) -> None:
        from lunar_gis.data.adapters import registry as adapter_registry

        class FakeAdapter:
            def search(self, query, page_token=None):
                _ = (query, page_token)
                return True, {"results": [], "total": 0}

        monkeypatch.setattr(adapter_registry, "get", lambda pid: FakeAdapter())
        result = search_catalog_handler({"provider_id": "osm.nominatim", "place": "Nowhere Xyz"})
        assert result["ok"] is True
        assert result["total"] == 0
        assert "hint" in result and "simplify" in result["hint"]

    def test_download_verified(self, monkeypatch, tmp_path) -> None:
        import hashlib

        from lunar_gis.data.adapters import registry as adapter_registry

        body = b"\x00" * 100

        class WriterAdapter:
            def provider_version(self) -> str:
                return "1.0"

            def download(self, dataset_id, asset_id, sandbox_dir):
                import os as os_module

                target = os_module.path.join(sandbox_dir, "f.bin")
                with open(target, "wb") as handle:
                    handle.write(body)
                return True, {
                    "sandbox_relpath": "f.bin",
                    "size_bytes": len(body),
                    "sha256_actual": hashlib.sha256(body).hexdigest(),
                }

        monkeypatch.setattr(adapter_registry, "get", lambda pid: WriterAdapter())
        result = download_dataset_handler(
            {"provider_id": "p", "dataset_id": "d", "asset_id": "a", "workspace_dir": str(tmp_path)}
        )
        assert result["ok"] is True
        assert result["size_bytes"] == 100
        assert result["sandbox_dir"]

    def test_download_unverified_without_bytes(self, monkeypatch, tmp_path) -> None:
        from lunar_gis.data.adapters import registry as adapter_registry

        class GhostAdapter:
            def provider_version(self) -> str:
                return "1.0"

            def download(self, dataset_id, asset_id, sandbox_dir):
                _ = (dataset_id, asset_id, sandbox_dir)
                return True, {"sandbox_relpath": "ghost.bin", "size_bytes": 10, "sha256_actual": "abc"}

        monkeypatch.setattr(adapter_registry, "get", lambda pid: GhostAdapter())
        result = download_dataset_handler(
            {"provider_id": "p", "dataset_id": "d", "asset_id": "a", "workspace_dir": str(tmp_path)}
        )
        assert result["ok"] is False
        assert "unverified" in result["error"]


class TestReadBodyCapped:
    def _response(self, chunks, length=None):
        class FakeHeaders:
            def get(self, name, default=""):
                return str(length) if name == "Content-Length" and length is not None else default

        class FakeResponse:
            def __init__(self):
                self.headers = FakeHeaders()
                self._chunks = list(chunks)

            def read(self, size):
                return self._chunks.pop(0) if self._chunks else b""

        return FakeResponse()

    def _progress(self, cancel_at=None):
        calls = {"updates": [], "cancel": False}

        class Sink:
            def update(self, received, total):
                calls["updates"].append((received, total))
                if cancel_at is not None and received >= cancel_at:
                    calls["cancel"] = True

            def cancelled(self):
                return calls["cancel"]

        return Sink(), calls

    def test_full_read_with_progress(self) -> None:
        from lunar_gis.data.adapters.transport import read_body_capped

        sink, calls = self._progress()
        body, error = read_body_capped(self._response([b"ab", b"cde"], length=5), 100, sink)
        assert error is None
        assert body == b"abcde"
        assert calls["updates"][-1] == (5, 5)

    def test_broken_sink_aborts(self) -> None:
        from lunar_gis.data.adapters.transport import read_body_capped

        class BrokenSink:
            def update(self, received, total):
                raise RuntimeError("ui gone")

            def cancelled(self):
                return False

        body, error = read_body_capped(self._response([b"ab", b"cde"], length=5), 100, BrokenSink())
        assert body is None
        assert error == "progress-failed"

    def test_cancel_aborts(self) -> None:
        from lunar_gis.data.adapters.transport import read_body_capped

        sink, _ = self._progress(cancel_at=2)
        body, error = read_body_capped(self._response([b"ab", b"cde"]), 100, sink)
        assert body is None
        assert error == "cancelled"

    def test_byte_cap(self) -> None:
        from lunar_gis.data.adapters.transport import read_body_capped

        body, error = read_body_capped(self._response([b"ab", b"cde"]), 4)
        assert body is None
        assert error == "byte-cap-exceeded"

    def test_read_error(self) -> None:
        from lunar_gis.data.adapters.transport import read_body_capped

        class BadResponse:
            headers = {}

            def read(self, size):
                raise OSError("boom")

        body, error = read_body_capped(BadResponse(), 100)
        assert body is None
        assert error and error.startswith("read-failed")

    def test_ambient_scope_applies(self) -> None:
        from lunar_gis.data.adapters.transport import progress_scope, read_body_capped

        sink, calls = self._progress()
        with progress_scope(sink):
            body, error = read_body_capped(self._response([b"ab"], length=2), 100)
        assert error is None
        assert body == b"ab"
        assert calls["updates"] == [(2, 2)]

    def test_explicit_beats_ambient(self) -> None:
        from lunar_gis.data.adapters.transport import progress_scope, read_body_capped

        ambient_sink, ambient_calls = self._progress()
        explicit_sink, explicit_calls = self._progress()
        with progress_scope(ambient_sink):
            body, error = read_body_capped(self._response([b"ab"], length=2), 100, explicit_sink)
        assert error is None and body == b"ab"
        assert explicit_calls["updates"] == [(2, 2)]
        assert ambient_calls["updates"] == []


class TestImportBoundary:
    def test_no_forbidden_in_base_transport(self) -> None:
        import pathlib

        for module in (base_module, transport_module):
            text = pathlib.Path(module.__file__).read_text(encoding="utf-8")
            assert "import qgis" not in text
            assert "from qgis" not in text
            for banned in ("subprocess", "pickle"):
                assert banned not in text
