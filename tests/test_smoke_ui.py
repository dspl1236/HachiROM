"""
tests/test_smoke_ui.py — End-to-end headless UI smoke tests.

Tests the full signal path from MockServer → KWPMonitor → DashboardWindow
for HachiROM, UrROM, DigiTool, and the KWPBridge mock fix.

Requires sibling repos on PYTHONPATH:
  ../UrROM, ../DigiTool, ../KWPBridge

Skips gracefully if sibling repos aren't present (CI runs from HachiROM only).

Run:
    QT_QPA_PLATFORM=offscreen pytest tests/test_smoke_ui.py -v
"""
import os, sys, time, threading, pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# ── Sibling repo imports ──────────────────────────────────────────────────────
_ROOT   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PARENT = os.path.dirname(_ROOT)

for repo in ("UrROM", "DigiTool", "KWPBridge"):
    p = os.path.join(_PARENT, repo)
    if p not in sys.path and os.path.isdir(p):
        sys.path.insert(0, p)

_HAS_URROM    = os.path.isdir(os.path.join(_PARENT, "UrROM"))
_HAS_DIGITOOL = os.path.isdir(os.path.join(_PARENT, "DigiTool"))
_HAS_KWPB     = os.path.isdir(os.path.join(_PARENT, "KWPBridge"))

# ── Qt fixture ────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def qt_app():
    from PyQt5.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture(scope="module")
def mock_server():
    """Start a 7A mock server for the duration of the module."""
    if not _HAS_KWPB:
        pytest.skip("KWPBridge not available")
    from kwpbridge.mock.server import MockServer
    srv = MockServer(ecu="7a", port=50277, poll_hz=5)   # non-default port to avoid clashes
    srv.start()
    time.sleep(0.15)
    yield srv
    srv.stop()


# ─────────────────────────────────────────────────────────────────────────────
# 1. MockServer + TCP client
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_KWPB, reason="KWPBridge not available")
class TestMockServer:
    def test_server_starts(self, mock_server):
        assert mock_server.is_running()

    def test_tcp_client_receives_state(self, mock_server):
        from kwpbridge.client import KWPClient
        states = []
        ev = threading.Event()

        def _on_state(s):
            states.append(s)
            ev.set()

        cli = KWPClient(port=50277)
        cli.on_state(_on_state)
        cli.connect(auto_reconnect=False)
        ev.wait(timeout=2.0)
        cli.disconnect()

        assert states, "No state received from mock server"
        s = states[0]
        assert s.get("connected") is True
        assert s.get("ecu_id", {}).get("part_number") == "893906266D"
        assert "0" in s.get("groups", {})
        assert len(s["groups"]["0"]["cells"]) == 10

    def test_7a_livevalues_from_mock(self, mock_server):
        from kwpbridge.client import KWPClient
        from hachirom.kwp import LiveValues
        states = []
        ev = threading.Event()
        cli = KWPClient(port=50277)
        cli.on_state(lambda s: (states.append(s), ev.set()))
        cli.connect(auto_reconnect=False)
        ev.wait(timeout=2.0)
        cli.disconnect()
        assert states
        lv = LiveValues(states[0])
        assert lv.valid
        assert lv.rpm is not None and lv.rpm > 0
        assert lv.coolant is not None
        assert lv.lambda_ is not None
        assert lv.load_pct is not None


# ─────────────────────────────────────────────────────────────────────────────
# 2. HachiROM DashboardWindow
# ─────────────────────────────────────────────────────────────────────────────

class TestHachiROMDashboard:
    """DashboardWindow constructs, shows, receives signals, clears on disconnect."""

    _state = {
        "connected": True,
        "ecu_id": {"part_number": "893906266D", "component": "7A"},
        "groups": {"0": {"cells": [
            {"index":1,"value":87.0,  "label":"Kuehlmitteltemperatur"},
            {"index":2,"value":80.0,  "label":"Motorlast"},
            {"index":3,"value":34.0,  "label":"Motordrehzahl"},
            {"index":4,"value":128.0, "label":"ll_stab"},
            {"index":5,"value":128.0, "label":"ll_stab_auto"},
            {"index":6,"value":128.0, "label":"stab_pos"},
            {"index":7,"value":24.0,  "label":"switch"},
            {"index":8,"value":1.02,  "label":"Lambdaregelung"},
            {"index":9,"value":0.0,   "label":"dist_pos"},
            {"index":10,"value":18.0, "label":"Zuendwinkel"},
        ]}}
    }

    def test_constructs(self, qt_app):
        from hachirom.kwp import KWPMonitor, DashboardWindow
        mon = KWPMonitor()
        dash = DashboardWindow(mon)
        assert dash is not None
        mon.stop()

    def test_shows_and_hides(self, qt_app):
        from hachirom.kwp import KWPMonitor, DashboardWindow
        mon = KWPMonitor()
        dash = DashboardWindow(mon)
        assert not dash.is_visible()
        dash.show(); qt_app.processEvents()
        assert dash.is_visible()
        dash.hide(); qt_app.processEvents()
        assert not dash.is_visible()
        mon.stop()

    def test_live_data_updates_gauges(self, qt_app):
        from hachirom.kwp import KWPMonitor, DashboardWindow, LiveValues
        mon = KWPMonitor()
        dash = DashboardWindow(mon)
        dash.show(); qt_app.processEvents()

        lv = LiveValues(self._state)
        assert lv.valid
        mon.live_data.emit(lv); qt_app.processEvents()

        assert dash._gauges["rpm"]["lbl_val"].text()     != "—"
        assert dash._gauges["coolant"]["lbl_val"].text() != "—"
        assert dash._gauges["lambda"]["lbl_val"].text()  != "—"
        assert dash._gauges["timing"]["lbl_val"].text()  != "—"
        # Strip should have content
        assert dash._lbl_strip.text() != ""
        mon.stop()

    def test_disconnect_clears_gauges(self, qt_app):
        from hachirom.kwp import KWPMonitor, DashboardWindow, LiveValues
        mon = KWPMonitor()
        dash = DashboardWindow(mon)
        dash.show(); qt_app.processEvents()
        mon.live_data.emit(LiveValues(self._state)); qt_app.processEvents()
        # Confirm it had data, then disconnect
        assert dash._gauges["rpm"]["lbl_val"].text() != "—"
        mon.disconnected.emit(); qt_app.processEvents()
        assert dash._gauges["rpm"]["lbl_val"].text() == "—"
        mon.stop()

    def test_lambda_colour_stoich(self, qt_app):
        from hachirom.kwp import LiveValues
        lv = LiveValues(self._state)
        assert lv.lambda_colour() == "#2dff6e"   # stoich → green

    def test_status_strip_updates(self, qt_app):
        from hachirom.kwp import KWPMonitor, DashboardWindow, LiveValues
        mon = KWPMonitor()
        dash = DashboardWindow(mon)
        dash.show(); qt_app.processEvents()
        mon.live_data.emit(LiveValues(self._state)); qt_app.processEvents()
        assert "● Live" in dash._lbl_status.text()
        mon.stop()


# ─────────────────────────────────────────────────────────────────────────────
# 3. UrROM DashboardWindow (M2.3.2)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_URROM, reason="UrROM not available")
class TestUrROMDashboard:

    _state = {
        "connected": True,
        "ecu_id": {"part_number": "4A0907551AA", "component": "M2.3.2"},
        "groups": {
            "1": {"cells": [
                {"index":1,"value":2800.0,"label":"RPM"},
                {"index":2,"value":87.0,  "label":"ECT"},
                {"index":3,"value":1.02,  "label":"Lambda"},
                {"index":4,"value":24.0,  "label":"Timing"},
            ]},
            "3": {"cells": [
                {"index":1,"value":2800.0,"label":"RPM"},
                {"index":2,"value":140.0, "label":"Load"},
                {"index":3,"value":18.5,  "label":"TPS"},
                {"index":4,"value":22.0,  "label":"IAT"},
            ]},
            "6": {"cells": [
                {"index":1,"value":65.0,  "label":"N75 DC"},
                {"index":2,"value":60.0,  "label":"N75 req"},
                {"index":3,"value":195.0, "label":"MAP kPa"},
                {"index":4,"value":190.0, "label":"MAP req"},
            ]},
        }
    }

    def test_livevalues_decodes_all_groups(self, qt_app):
        from urrom.kwp import LiveValues
        lv = LiveValues(self._state)
        assert lv.valid
        assert lv.rpm == 2800.0
        assert lv.ect == 87.0
        assert lv.lambda_ == 1.02
        assert lv.timing == 24.0
        assert lv.map_kpa == 195.0
        assert lv.n75_dc == 65.0
        assert lv.iat == 22.0

    def test_constructs_and_shows(self, qt_app):
        from urrom.kwp import KWPMonitor, DashboardWindow
        mon = KWPMonitor()
        dash = DashboardWindow(mon)
        dash.show(); qt_app.processEvents()
        assert dash.is_visible()
        mon.stop()

    def test_all_gauges_update(self, qt_app):
        from urrom.kwp import KWPMonitor, DashboardWindow, LiveValues
        mon = KWPMonitor()
        dash = DashboardWindow(mon)
        dash.show(); qt_app.processEvents()
        lv = LiveValues(self._state)
        mon.live_data.emit(lv); qt_app.processEvents()
        for key in ("rpm", "ect", "lambda", "timing", "map_kpa", "n75_dc", "iat"):
            assert dash._gauges[key]["lv"].text() != "—", f"{key} gauge not updated"
        assert dash._gauges["map_kpa"]["lv"].text() == "195"
        mon.stop()

    def test_stock_firmware_map_gauge_stays_blank(self, qt_app):
        """Without group 6 data, MAP/N75 gauges show '—'."""
        from urrom.kwp import KWPMonitor, DashboardWindow, LiveValues
        state_no_g6 = {k: v for k, v in self._state.items()}
        state_no_g6["groups"] = {k: v for k, v in self._state["groups"].items()
                                  if k != "6"}
        mon = KWPMonitor()
        dash = DashboardWindow(mon)
        dash.show(); qt_app.processEvents()
        lv = LiveValues(state_no_g6)
        assert lv.map_kpa is None
        mon.live_data.emit(lv); qt_app.processEvents()
        assert dash._gauges["map_kpa"]["lv"].text() == "—"
        mon.stop()


# ─────────────────────────────────────────────────────────────────────────────
# 4. DigiTool DashboardWindow (Digifant 1)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_DIGITOOL, reason="DigiTool not available")
class TestDigiToolDashboard:

    _state_rich = {
        "connected": True,
        "ecu_id": {"part_number": "037906023", "component": "Digifant 1"},
        "groups": {"0": {"cells": [
            {"index":1,"value":1850.0,"label":"Engine Speed","unit":"RPM"},
            {"index":2,"value":120.0, "label":"Engine Load","unit":""},
            {"index":3,"value":88.0,  "label":"Coolant Temp","unit":"°C"},
            {"index":4,"value":5.2,   "label":"Injection Time","unit":"ms"},
            {"index":5,"value":0.72,  "label":"O2S Voltage","unit":"V"},
        ]}}
    }
    _state_lean = {
        "connected": True,
        "ecu_id": {"part_number": "037906023", "component": "Digifant 1"},
        "groups": {"0": {"cells": [
            {"index":1,"value":1850.0,"label":"Engine Speed","unit":"RPM"},
            {"index":2,"value":120.0, "label":"Engine Load","unit":""},
            {"index":3,"value":88.0,  "label":"Coolant Temp","unit":"°C"},
            {"index":4,"value":5.2,   "label":"Injection Time","unit":"ms"},
            {"index":5,"value":0.30,  "label":"O2S Voltage","unit":"V"},
        ]}}
    }

    def test_livevalues_rich(self, qt_app):
        from digitool.kwp import LiveValues
        lv = LiveValues(self._state_rich)
        assert lv.valid
        assert lv.rpm == 1850.0
        assert lv.coolant == 88.0
        assert lv.inj_time == 5.2
        assert lv.o2s_voltage == 0.72
        assert lv.o2s_rich is True

    def test_livevalues_lean(self, qt_app):
        from digitool.kwp import LiveValues
        lv = LiveValues(self._state_lean)
        assert lv.o2s_voltage == 0.30
        assert lv.o2s_rich is False

    def test_rich_lean_badge(self, qt_app):
        from digitool.kwp import KWPMonitor, DashboardWindow, LiveValues
        mon = KWPMonitor()
        dash = DashboardWindow(mon)
        dash.show(); qt_app.processEvents()

        mon.live_data.emit(LiveValues(self._state_rich)); qt_app.processEvents()
        assert dash._o2s_badge.text() == "RICH"

        mon.live_data.emit(LiveValues(self._state_lean)); qt_app.processEvents()
        assert dash._o2s_badge.text() == "LEAN"

        mon.disconnected.emit(); qt_app.processEvents()
        assert dash._o2s_badge.text() == "—"
        mon.stop()

    def test_all_gauges_update(self, qt_app):
        from digitool.kwp import KWPMonitor, DashboardWindow, LiveValues
        mon = KWPMonitor()
        dash = DashboardWindow(mon)
        dash.show(); qt_app.processEvents()
        mon.live_data.emit(LiveValues(self._state_rich)); qt_app.processEvents()
        for key in ("rpm", "coolant", "load", "inj_time", "o2s"):
            assert dash._gauges[key]["lv"].text() != "—", f"{key} not updated"
        mon.stop()


# ─────────────────────────────────────────────────────────────────────────────
# 5. KWPBridge mock fix verification
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_KWPB, reason="KWPBridge not available")
class TestKWPBridgeMockFix:
    def test_on_connect_mock_exists(self):
        from kwpbridge.gui.main import KWPBridgeWindow
        assert hasattr(KWPBridgeWindow, '_on_connect_mock')
        assert callable(KWPBridgeWindow._on_connect_mock)

    def test_start_mock_uses_tcp_not_serial(self):
        import inspect
        from kwpbridge.gui.main import KWPBridgeWindow
        src = inspect.getsource(KWPBridgeWindow._start_mock)
        assert "_on_connect_mock" in src, "_start_mock should call _on_connect_mock"
        # Verify the serial _on_connect is not called directly
        # (replace _on_connect_mock first to avoid false positive)
        src_masked = src.replace("_on_connect_mock", "MOCK")
        assert "_on_connect)" not in src_masked, \
            "_start_mock must not call _on_connect() (opens COM port)"


# ─────────────────────────────────────────────────────────────────────────────
# 6. End-to-end: MockServer → KWPMonitor → Dashboard (HachiROM)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not _HAS_KWPB, reason="KWPBridge not available")
class TestEndToEnd:
    def test_mock_state_through_livevalues_to_dashboard(self, qt_app, mock_server):
        """
        Full path: MockServer TCP → KWPClient → LiveValues → DashboardWindow gauge.

        Uses KWPClient directly (no KWPMonitor timer) so the test controls timing.
        The dashboard receives a LiveValues constructed from real mock data.
        """
        from kwpbridge.client import KWPClient
        from hachirom.kwp import KWPMonitor, DashboardWindow, LiveValues

        # Receive one real state packet from mock server
        states = []
        ev = threading.Event()
        cli = KWPClient(port=50277)
        cli.on_state(lambda s: (states.append(s), ev.set()))
        cli.connect(auto_reconnect=False)
        ev.wait(timeout=2.0)
        cli.disconnect()
        assert states, "Mock server sent no state"

        # Decode through LiveValues
        lv = LiveValues(states[0])
        assert lv.valid, "LiveValues invalid from mock state"

        # Feed into dashboard via monitor signal
        mon = KWPMonitor()
        dash = DashboardWindow(mon)
        dash.show(); qt_app.processEvents()

        mon.live_data.emit(lv); qt_app.processEvents()

        assert dash._gauges["rpm"]["lbl_val"].text() != "—", "RPM gauge not updated from mock data"
        assert dash._gauges["coolant"]["lbl_val"].text() != "—", "Coolant gauge not updated"
        assert "● Live" in dash._lbl_status.text(), "Status not updated"

        mon.stop()
