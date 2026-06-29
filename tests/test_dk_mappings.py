"""Tests for the pinned DK->Kalshi mapping store (src/dk_mappings.py)."""

import os
import sys
import time
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import dk_mappings


def _use_temp_path():
    dk_mappings._PATH = os.path.join(tempfile.gettempdir(), "dk_mappings_test.json")
    if os.path.exists(dk_mappings._PATH):
        os.remove(dk_mappings._PATH)


def test_roundtrip():
    _use_temp_path()
    assert dk_mappings.load() == {}
    m = {}
    dk_mappings.put(m, "DKP3-ECEFORUSREC26", "KXRECSSNBER-26", "Recession this year?",
                    {"Yes": "Starts"}, 0.92, "both ask about a 2026 recession")
    dk_mappings.save(m)
    loaded = dk_mappings.load()
    assert loaded["DKP3-ECEFORUSREC26"]["kalshi"] == "KXRECSSNBER-26"
    assert loaded["DKP3-ECEFORUSREC26"]["outcome_map"] == {"Yes": "Starts"}
    os.remove(dk_mappings._PATH)
    print("  mappings roundtrip: put -> save -> load preserves the pin")


def test_freshness_ttl():
    pin = {"kalshi": "K", "ts": time.time()}
    assert dk_mappings.fresh(pin)                      # just written -> fresh
    pin["ts"] = time.time() - dk_mappings.TTL_SECS - 1
    assert not dk_mappings.fresh(pin)                  # past the window -> re-confirm
    assert not dk_mappings.fresh(None)                 # no pin -> not fresh
    assert not dk_mappings.fresh({})                   # empty -> not fresh
    print("  mappings freshness: TTL window + missing pins handled")


if __name__ == "__main__":
    test_roundtrip()
    test_freshness_ttl()
    print("\nAll dk_mappings tests passed.")
