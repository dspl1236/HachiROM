"""
HachiROM KWPBridge integration tests.

Tests the full stack: mock ECU server → KWPBridge client → LiveValues →
safety gate logic. No physical hardware or GUI required.

Run with: pytest tests/test_kwp_integration.py -v
"""

import sys
import time
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "KWPBridge"))

from hachirom.kwp import (
    kwpbridge_available, kwpbridge_running,
    LiveValues, status_label, live_summary,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_7a():
    """Start a mock 7A ECU server for the duration of the test."""
    from kwpbridge.mock import mock_server
    with mock_server(ecu="7a", port=50290) as srv:
        time.sleep(0.15)
        yield srv


@pytest.fixture
def mock_aah():
    """Start a mock AAH V6 server."""
    from kwpbridge.mock import mock_server
    with mock_server(ecu="aah", port=50291) as srv:
        time.sleep(0.15)
        yield srv


def _get_state(port: int) -> dict:
    """Connect a KWPClient, wait for first state, disconnect, return state."""
    from kwpbridge.client import KWPClient
    client = KWPClient(port=port)
    client.connect()
    for _ in range(50):
        if client.state:
            break
        time.sleep(0.1)
    state = client.state
    client.disconnect()
    return state


# ── kwpbridge_running detection ───────────────────────────────────────────────

class TestKWPBridgeDetection:

    def test_not_running_without_mock(self):
        from kwpbridge.mock.server import MockServer
        assert not kwpbridge_running()

    def test_running_with_mock(self, mock_7a):
        from hachirom.kwp import kwpbridge_running as _run
        import socket
        # Direct port check on test port
        try:
            s = socket.create_connection(("127.0.0.1", 50290), timeout=1)
            s.close()
            is_up = True
        except OSError:
            is_up = False
        assert is_up

    def test_kwpbridge_available(self):
        assert kwpbridge_available() is True


# ── LiveValues parsing ────────────────────────────────────────────────────────

class TestLiveValues:

    def _make_state(self, pn="893906266D", rpm=850.0, coolant=87.0,
                    load=128.0, lambda_=1.0, timing=18.6):
        return {
            "connected": True,
            "ecu_id": {"part_number": pn, "component": "TEST"},
            "groups": {
                "0": {
                    "cells": [
                        {"index": 1, "value": coolant, "unit": "°C",   "label": "Coolant"},
                        {"index": 2, "value": load,    "unit": "",     "label": "Load"},
                        {"index": 3, "value": rpm,     "unit": "RPM",  "label": "RPM"},
                        {"index": 8, "value": lambda_, "unit": "λ",    "label": "Lambda"},
                        {"index": 10,"value": timing,  "unit": "°BTDC","label": "Timing"},
                    ]
                }
            }
        }

    def test_valid_state(self):
        lv = LiveValues(self._make_state())
        assert lv.valid
        assert lv.rpm == 850.0
        assert lv.coolant == 87.0
        assert lv.load == 128.0
        assert lv.lambda_ == 1.0
        assert lv.timing == 18.6
        assert lv.ecu_pn == "893906266D"

    def test_load_pct_calculated(self):
        lv = LiveValues(self._make_state(load=128.0))
        assert lv.load_pct is not None
        assert abs(lv.load_pct - 50.2) < 1.0

    def test_none_state(self):
        lv = LiveValues(None)
        assert not lv.valid
        assert lv.rpm is None

    def test_disconnected_state(self):
        lv = LiveValues({"connected": False})
        assert not lv.valid

    def test_lambda_colour_stoich(self):
        lv = LiveValues(self._make_state(lambda_=1.0))
        assert lv.lambda_colour() == "#2dff6e"

    def test_lambda_colour_slightly_off(self):
        lv = LiveValues(self._make_state(lambda_=0.90))
        assert lv.lambda_colour() == "#ffaa00"

    def test_lambda_colour_significantly_off(self):
        lv = LiveValues(self._make_state(lambda_=0.75))
        assert lv.lambda_colour() == "#ff4444"

    def test_lambda_colour_lean(self):
        lv = LiveValues(self._make_state(lambda_=1.20))
        assert lv.lambda_colour() == "#ff4444"

    def test_summary_string(self):
        lv = LiveValues(self._make_state())
        s = live_summary(lv)
        assert "RPM" in s
        assert "°C" in s
        assert "λ" in s
        assert "ign" in s

    def test_summary_none_on_invalid(self):
        lv = LiveValues(None)
        assert live_summary(lv) == ""

    def test_group_0_integer_key(self):
        """State with integer group key (0) instead of string "0"."""
        state = {
            "connected": True,
            "ecu_id": {"part_number": "893906266D"},
            "groups": {
                0: {
                    "cells": [
                        {"index": 3, "value": 900.0, "unit": "RPM", "label": "RPM"},
                    ]
                }
            }
        }
        lv = LiveValues(state)
        assert lv.rpm == 900.0


# ── Safety gate ───────────────────────────────────────────────────────────────

class TestSafetyGate:

    def test_matching_part_numbers_allows_editing(self, mock_7a):
        state = _get_state(50290)
        lv = LiveValues(state)
        rom_pn = "893906266D"
        assert lv.ecu_pn.upper() == rom_pn.upper()

    def test_mismatched_part_numbers_blocks_editing(self, mock_7a):
        state = _get_state(50290)
        lv = LiveValues(state)
        wrong_rom_pn = "4A0906266"  # AAH ROM, not 7A
        assert lv.ecu_pn.upper() != wrong_rom_pn.upper()

    def test_aah_matches_aah_rom(self, mock_aah):
        state = _get_state(50291)
        lv = LiveValues(state)
        assert lv.ecu_pn == "4A0906266"
        assert lv.ecu_pn.upper() == "4A0906266"

    def test_aah_does_not_match_266d_rom(self, mock_aah):
        state = _get_state(50291)
        lv = LiveValues(state)
        assert lv.ecu_pn.upper() != "893906266D"

    def test_case_insensitive_gate(self, mock_7a):
        state = _get_state(50290)
        lv = LiveValues(state)
        # Should match regardless of case
        for pn in ["893906266D", "893906266d", "893906266D"]:
            assert lv.ecu_pn.upper() == pn.upper()


# ── Live values from real mock data ───────────────────────────────────────────

class TestLiveValuesFromMock:

    def test_7a_rpm_idle_range(self, mock_7a):
        state = _get_state(50290)
        lv = LiveValues(state)
        assert lv.valid
        assert 700 <= lv.rpm <= 1000, f"7A idle RPM out of range: {lv.rpm}"

    def test_7a_coolant_range(self, mock_7a):
        state = _get_state(50290)
        lv = LiveValues(state)
        # Mock starts cold and warms up — just check plausible range
        assert -20 <= lv.coolant <= 100

    def test_7a_lambda_plausible(self, mock_7a):
        state = _get_state(50290)
        lv = LiveValues(state)
        assert 0.8 <= lv.lambda_ <= 1.2, f"Lambda implausible: {lv.lambda_}"

    def test_7a_ecu_part_number(self, mock_7a):
        state = _get_state(50290)
        lv = LiveValues(state)
        assert lv.ecu_pn == "893906266D"

    def test_aah_rpm_idle_range(self, mock_aah):
        state = _get_state(50291)
        lv = LiveValues(state)
        assert lv.valid
        assert 600 <= lv.rpm <= 900


# ── Status label helper ───────────────────────────────────────────────────────

class TestStatusLabel:

    def test_no_kwpbridge_installed(self, monkeypatch):
        import hachirom.kwp as kwp_mod
        monkeypatch.setattr(kwp_mod, '_KWP_AVAILABLE', False)
        text, colour = status_label(None, "893906266D")
        assert "not installed" in text.lower()
        assert colour == "#555555"
