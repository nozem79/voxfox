"""Tests for voxfox_core.ipc's _ensure_runtime_dir: it used to only log a
warning on a symlink or wrong-owner runtime directory and let the caller
bind a socket there anyway (bug 5). Now it returns False and both callers
(IPCServer.start, acquire_singleton_lock) check that.
"""

import os
import stat

import voxfox_core.ipc as ipc


def test_ensure_runtime_dir_accepts_a_normal_directory(tmp_path, monkeypatch):
    target = tmp_path / "voxfox-runtime"
    monkeypatch.setattr(ipc, "RUNTIME_DIR", str(target))
    assert ipc._ensure_runtime_dir() is True
    assert stat.S_IMODE(os.stat(str(target)).st_mode) == 0o700


def test_ensure_runtime_dir_rejects_a_symlink(tmp_path, monkeypatch):
    real = tmp_path / "echte-map"
    real.mkdir()
    link = tmp_path / "voxfox-runtime-link"
    link.symlink_to(real)
    monkeypatch.setattr(ipc, "RUNTIME_DIR", str(link))
    assert ipc._ensure_runtime_dir() is False


def test_ensure_runtime_dir_rejects_wrong_owner(tmp_path, monkeypatch):
    target = tmp_path / "voxfox-runtime"
    target.mkdir()
    real_lstat = os.lstat

    class _FakeStat:
        st_mode = stat.S_IFDIR
        st_uid = 999999  # not us

    def fake_lstat(p):
        return _FakeStat() if str(p) == str(target) else real_lstat(p)

    monkeypatch.setattr(os, "lstat", fake_lstat)
    monkeypatch.setattr(ipc, "RUNTIME_DIR", str(target))
    assert ipc._ensure_runtime_dir() is False


def test_ipc_server_start_aborts_when_runtime_dir_is_unsafe(monkeypatch):
    monkeypatch.setattr(ipc, "_ensure_runtime_dir", lambda: False)
    server = ipc.IPCServer(app=None)
    assert server.start() is False


def test_acquire_singleton_lock_aborts_when_runtime_dir_is_unsafe(monkeypatch):
    monkeypatch.setattr(ipc, "_ensure_runtime_dir", lambda: False)
    assert ipc.acquire_singleton_lock() is False
