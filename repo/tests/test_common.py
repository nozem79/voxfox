"""Tests for voxfox_core.common's _have(): the cached PATH lookup that
replaced a "which" subprocess spawn on every call.
"""

import voxfox_core.common as common


def test_have_finds_a_real_command():
    assert common._have("python3") is True


def test_have_rejects_a_nonexistent_command():
    assert common._have("this-command-does-not-exist-xyz") is False


def test_have_is_cached():
    common._have.cache_clear()
    before = common._have.cache_info()
    for _ in range(20):
        common._have("python3")
    after = common._have.cache_info()
    assert after.misses - before.misses == 1
    assert after.hits - before.hits == 19
