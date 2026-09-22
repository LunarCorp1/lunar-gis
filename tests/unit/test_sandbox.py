"""Unit tests for sandbox lifecycle (usage + orphan sweep)."""

from __future__ import annotations

import os
import time

from lunar_gis.data import sandbox as sandbox_module
from lunar_gis.data.sandbox import format_bytes, sandbox_usage, sweep_sandboxes


def _aged_dir(root: str, name: str, age_s: float, size: int = 10) -> str:
    path = os.path.join(root, name)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "f.bin"), "wb") as handle:
        handle.write(b"\x00" * size)
    moment = time.time() - age_s
    os.utime(path, (moment, moment))
    return path


class TestUsage:
    def test_counts_only_prefix(self, tmp_path) -> None:
        _aged_dir(str(tmp_path), "lunar-acquire-a", age_s=0)
        _aged_dir(str(tmp_path), "other-dir", age_s=0)
        usage = sandbox_usage(str(tmp_path))
        assert usage["sandbox_count"] == 1
        assert usage["bytes"] == 10

    def test_missing_root(self, tmp_path) -> None:
        usage = sandbox_usage(str(tmp_path / "ghost"))
        assert usage == {"sandbox_count": 0, "bytes": 0, "root": str(tmp_path / "ghost")}


class TestSweep:
    def test_removes_old_keeps_fresh(self, tmp_path) -> None:
        root = str(tmp_path)
        _aged_dir(root, "lunar-acquire-old", age_s=3600)
        _aged_dir(root, "lunar-acquire-new", age_s=0)
        record = sweep_sandboxes(root, retention_s=60)
        assert record["ok"] is True
        assert record["removed"] == ["lunar-acquire-old"]
        assert record["kept"] == 1
        assert not os.path.exists(os.path.join(root, "lunar-acquire-old"))
        assert os.path.isdir(os.path.join(root, "lunar-acquire-new"))

    def test_active_floor_protects(self, tmp_path) -> None:
        root = str(tmp_path)
        _aged_dir(root, "lunar-acquire-hot", age_s=10)
        record = sweep_sandboxes(root, retention_s=0)
        assert record["removed"] == []
        assert record["kept"] == 1

    def test_ignores_non_matching_and_files(self, tmp_path) -> None:
        root = str(tmp_path)
        _aged_dir(root, "other-old", age_s=9999)
        with open(os.path.join(root, "lunar-acquire-file"), "w") as handle:
            handle.write("x")
        record = sweep_sandboxes(root, retention_s=0)
        assert record["removed"] == []
        assert os.path.isdir(os.path.join(root, "other-old"))

    def test_unreadable_root(self, tmp_path) -> None:
        record = sweep_sandboxes(str(tmp_path / "ghost"))
        assert record["ok"] is False


class TestFormat:
    def test_units(self) -> None:
        assert format_bytes(0) == "0 bytes"
        assert format_bytes(2048) == "2.0 KB"
        assert format_bytes(5 * 1024 * 1024) == "5.0 MB"


class TestImportBoundary:
    def test_qgis_free(self) -> None:
        import pathlib

        text = pathlib.Path(sandbox_module.__file__).read_text(encoding="utf-8")
        assert "import qgis" not in text
        for banned in ("subprocess", "socket"):
            assert banned not in text
