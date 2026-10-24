"""Tests for voxfox_core.common's have_command(): the cached PATH lookup that
replaced a "which" subprocess spawn on every call.
"""

import voxfox_core.common as common


def test_have_finds_a_real_command():
    assert common.have_command("python3") is True


def test_have_rejects_a_nonexistent_command():
    assert common.have_command("this-command-does-not-exist-xyz") is False


def test_have_is_cached():
    common.have_command.cache_clear()
    before = common.have_command.cache_info()
    for _ in range(20):
        common.have_command("python3")
    after = common.have_command.cache_info()
    assert after.misses - before.misses == 1
    assert after.hits - before.hits == 19
