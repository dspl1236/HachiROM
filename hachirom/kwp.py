"""
hachirom/kwp.py — KWPBridge integration for HachiROM.

Design
------
KWPMonitor is ALWAYS a proper QObject with proper pyqtSignal declarations.
KWPBridge is entirely optional — if not installed or not running, the monitor
polls silently and no signals fire. HachiROM works standalone without any
connection to KWPBridge.

When KWPBridge IS running:
  - Monitor detects it automatically within ~1 second
  - Emits connected(ecu_pn) once ECU handshake completes
  - Streams live_data(LiveValues) at the poll rate (default 1 Hz)
  - Emits mismatch(ecu_pn, rom_pn) if connected ECU ≠ loaded ROM
  - Emits disconnected() if KWPBridge stops

The same pattern is used in UrROM, HachiROM, and MESevenTool.
All three tools are standalone — KWPBridge is an optional live-data link.
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)

DEFAULT_PORT = 50266

# ── Optional: kwpbridge package ──────────────────────────────────────────────

try:
    from kwpbridge.client import KWPClient
    try:
        from kwpbridge.client import is_running as _kwp_is_running
    except ImportError:
        def _kwp_is_running(port=DEFAULT_PORT):
            """Fallback: try a socket connect."""
            import socket
            try:
                s = socket.create_connection(("127.0.0.1", port), timeout=0.3)
                s.close()
                return True
            except OSError:
                return False
    _KWP_AVAILABLE = True
except ImportError:
    KWPClient      = None          # type: ignore
    _KWP_AVAILABLE = False

    def _kwp_is_running(port=DEFAULT_PORT):
        return False

# ── Qt — always required for this module ─────────────────────────────────────

from PyQt5.QtCore import QObject, QTimer, pyqtSignal   # noqa: E402


def kwpbridge_available() -> bool:
    """True if kwpbridge package is installed."""
    return _KWP_AVAILABLE


def kwpbridge_running() -> bool:
    """True if KWPBridge server is accepting connections on localhost."""
    try:
        return _kwp_is_running(port=DEFAULT_PORT)
    except Exception:
        return False


# ── LiveValues ────────────────────────────────────────────────────────────────

class LiveValues:
    """
    Decoded measuring-block values from a KWPBridge state dict.
    All fields are None if KWPBridge is not connected or the cell is absent.
    """

    def __init__(self, state: dict):
        self.rpm:      Optional[float] = None
        self.load:     Optional[float] = None
        self.load_pct: Optional[float] = None
        self.coolant:  Optional[float] = None
        self.lambda_:  Optional[float] = None
        self.timing:   Optional[float] = None
        self.battery:  Optional[float] = None
        self.ecu_pn:   str = ""

        if not state or not state.get("connected"):
            return

        self.ecu_pn = state.get("ecu_id", {}).get("part_number", "")
        groups = state.get("groups", {})
        group0 = groups.get("0", groups.get(0, {}))
        cells  = {c["index"]: c for c in group0.get("cells", [])}

        pn_upper = self.ecu_pn.upper()
        is_digifant = pn_upper.startswith("037906") or pn_upper.startswith("039906")

        if is_digifant:
            rpm_cell, load_cell, coolant_cell = 1, 2, 3
            lambda_cell = timing_cell = battery_cell = None
        else:
            # 7A / AAH / Motronic
            rpm_cell, load_cell, coolant_cell = 3, 2, 1
            lambda_cell, timing_cell, battery_cell = 8, 10, 4

        def _val(idx):
            if idx is None:
                return None
            c = cells.get(idx)
            return c["value"] if c else None

        self.coolant  = _val(coolant_cell)
        self.load     = _val(load_cell)
        self.rpm      = _val(rpm_cell)
        self.lambda_  = _val(lambda_cell)
        self.timing   = _val(timing_cell)
        self.battery  = _val(battery_cell)

        if self.load is not None:
            self.load_pct = (self.load / 255.0 * 100.0
                             if self.load > 100 else self.load)

    @property
    def valid(self) -> bool:
        return self.rpm is not None

    def lambda_colour(self) -> str:
        if self.lambda_ is None:
            return "#444444"
        if 0.95 <= self.lambda_ <= 1.05:
            return "#2dff6e"
        if 0.85 <= self.lambda_ < 0.95 or 1.05 < self.lambda_ <= 1.15:
            return "#ffaa00"
        return "#ff4444"


# ── MockEngine ────────────────────────────────────────────────────────────────

import math, random

class MockEngine:
    """
    Generates synthetic 7A engine data without any hardware.

    Cycles through realistic drive scenarios so the dashboard looks alive.
    Call tick() every second to advance state; read properties for values.

    Scenarios (automatic progression):
        cold_idle   → warm_idle → cruise → accel → cruise → decel → warm_idle
    """

    SCENARIOS = [
        # (name,          duration_s, rpm_target, load_target, lambda_target, timing_target)
        ("Cold idle",       20,        820,  12.0,  1.04,  10.0),
        ("Warming up",      30,        900,  14.0,  1.01,  12.0),
        ("Idle (warm)",     15,        870,  12.0,  0.99,  12.5),
        ("Light cruise",    20,       2400,  28.0,  1.00,  22.0),
        ("Acceleration",    12,       4200,  72.0,  0.94,  18.0),
        ("Full pull",        8,       5800,  90.0,  0.89,  16.0),
        ("Lift",             5,       3200,  20.0,  1.06,  24.0),
        ("Cruise",          25,       2600,  30.0,  1.00,  22.0),
        ("Decel",            8,       1400,   8.0,  1.08,  15.0),
        ("Idle (warm)",     20,        860,  12.0,  1.00,  12.0),
    ]

    def __init__(self, ecu_pn: str = "893 906 266 D"):
        self.ecu_pn       = ecu_pn
        self._scenario_idx = 0
        self._scenario_t   = 0          # seconds into current scenario
        self._coolant      = 18.0       # starts cold

        # smoothed output values
        self.rpm     = 820.0
        self.load    = 12.0
        self.lambda_ = 1.00
        self.timing  = 10.0
        self.battery = 14.2

    @property
    def scenario_name(self) -> str:
        return self.SCENARIOS[self._scenario_idx][0]

    def tick(self):
        """Advance one second.  Call from a 1 Hz QTimer."""
        s = self.SCENARIOS[self._scenario_idx]
        _, dur, rpm_t, load_t, lam_t, tim_t = s

        # Move to next scenario when duration expires
        self._scenario_t += 1
        if self._scenario_t >= dur:
            self._scenario_t = 0
            self._scenario_idx = (self._scenario_idx + 1) % len(self.SCENARIOS)
            s = self.SCENARIOS[self._scenario_idx]
            _, dur, rpm_t, load_t, lam_t, tim_t = s

        # Smooth tracking with noise
        alpha_fast = 0.25
        alpha_slow = 0.08

        def _track(current, target, alpha, noise=0.0):
            jitter = random.gauss(0, noise) if noise else 0
            return current + alpha * (target - current) + jitter

        self.rpm     = _track(self.rpm,     rpm_t,  alpha_fast, 15.0)
        self.load    = _track(self.load,    load_t, alpha_fast,  0.5)
        self.lambda_ = _track(self.lambda_, lam_t,  alpha_slow,  0.003)
        self.timing  = _track(self.timing,  tim_t,  alpha_slow,  0.2)

        # Coolant warms up slowly, never cools during a mock session
        coolant_t = 90.0 if self._scenario_idx > 1 else 45.0
        self.coolant = min(92.0, self._coolant + 0.4)
        self._coolant = self.coolant

        # Battery slight ripple
        self.battery = 14.2 + random.gauss(0, 0.05)

    def as_live_values(self) -> 'LiveValues':
        """Build a LiveValues object from current mock state."""
        state = {
            "connected": True,
            "ecu_id": {"part_number": self.ecu_pn},
            "groups": {
                "0": {
                    "cells": [
                        {"index": 1,  "value": round(self.coolant, 1)},
                        {"index": 2,  "value": round(self.load, 1)},
                        {"index": 3,  "value": round(self.rpm, 0)},
                        {"index": 4,  "value": round(self.battery, 2)},
                        {"index": 8,  "value": round(self.lambda_, 4)},
                        {"index": 10, "value": round(self.timing, 1)},
                    ]
                }
            }
        }
        lv = LiveValues(state)
        lv._mock_scenario = self.scenario_name   # tag for UI
        return lv


# ── KWPMonitor ────────────────────────────────────────────────────────────────

class KWPMonitor(QObject):
    """
    Qt object that polls KWPBridge and emits signals for HachiROM / UrROM.

    pyqtSignal declarations MUST be at class level — never inside a
    conditional block — so that PyQt's metaclass finds them regardless
    of whether kwpbridge is installed.

    Signals
    -------
    connected(str)        ecu part number when KWPBridge connects
    disconnected()        KWPBridge disconnected or stopped
    live_data(object)     LiveValues on each poll
    mismatch(str, str)    (ecu_pn, rom_pn) when PNs don't match
    """

    connected    = pyqtSignal(str)
    disconnected = pyqtSignal()
    live_data    = pyqtSignal(object)
    mismatch     = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client     = None          # KWPClient instance or None
        self._rom_pns:   list[str] = []
        self._matched    = False
        self._mock_engine: 'MockEngine | None' = None   # set via start_mock()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(1000)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_rom_part_number(self, pn: str):
        """Single-PN convenience wrapper."""
        self.set_rom_part_numbers([pn])

    def set_rom_part_numbers(self, pns: list):
        """Set acceptable ROM part numbers. Any match enables the overlay."""
        self._rom_pns = [p.upper().replace("-", "").strip() for p in pns]
        self._check_match()

    def start(self):
        self._timer.start(1000)

    def stop(self):
        self._timer.stop()
        self._drop_client()
        self._mock_engine = None

    def start_mock(self, ecu_pn: str = "893 906 266 D"):
        """
        Switch to mock mode — generates synthetic engine data internally.
        No KWPBridge connection, no USB, works standalone.
        Call stop_mock() to return to normal polling.
        """
        self._drop_client()
        self._mock_engine = MockEngine(ecu_pn=ecu_pn)
        self.connected.emit(ecu_pn)
        log.info(f"KWPMonitor: mock mode started ({ecu_pn})")

    def stop_mock(self):
        """Return to normal KWPBridge polling mode."""
        if self._mock_engine is not None:
            self._mock_engine = None
            self.disconnected.emit()
            log.info("KWPMonitor: mock mode stopped")

    def is_mock(self) -> bool:
        return self._mock_engine is not None

    def is_matched(self) -> bool:
        return self._matched

    def current_pn(self) -> str:
        if self._client is not None:
            try:
                state = self._client.state
                if state:
                    return state.get("ecu_id", {}).get("part_number", "")
            except Exception:
                pass
        return ""

    # ── Internal ──────────────────────────────────────────────────────────────

    def _poll(self):
        # Mock mode — no KWPBridge, no USB, pure synthetic data
        if self._mock_engine is not None:
            self._mock_engine.tick()
            lv = self._mock_engine.as_live_values()
            self.live_data.emit(lv)
            return

        # If KWPBridge not installed, do nothing
        if not _KWP_AVAILABLE:
            return

        # If we have an active client, poll it
        if self._client is not None:
            try:
                if self._client.connected:
                    state = self._client.state
                    if state:
                        lv = LiveValues(state)
                        if lv.valid:
                            self.live_data.emit(lv)
                        self._check_match()
                    return
            except Exception as e:
                log.debug(f"KWPMonitor poll error: {e}")
            # Client dropped
            self._drop_client()

        # Try connecting if KWPBridge is running
        if kwpbridge_running():
            self._connect()

    def _connect(self):
        if not _KWP_AVAILABLE or KWPClient is None:
            return
        try:
            self._client = KWPClient(port=DEFAULT_PORT)
            self._client.on_connect(self._on_connect)
            self._client.on_disconnect(self._on_disconnect)
            self._client.on_state(self._on_state)
            self._client.connect(auto_reconnect=False)
            log.info("KWPMonitor: connecting to KWPBridge")
        except Exception as e:
            log.debug(f"KWPMonitor: connect error: {e}")
            self._client = None

    def _drop_client(self):
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass
            self._client = None
        if self._matched:
            self._matched = False
            self.disconnected.emit()

    def _on_connect(self):
        pn = self.current_pn()
        log.info(f"KWPMonitor: connected, ECU={pn}")
        self.connected.emit(pn)
        self._check_match()

    def _on_disconnect(self):
        log.info("KWPMonitor: disconnected")
        self._matched = False
        self.disconnected.emit()

    def _on_state(self, state: dict):
        lv = LiveValues(state)
        if lv.valid:
            self.live_data.emit(lv)
        self._check_match()

    def _check_match(self):
        ecu_pn = self.current_pn().upper().replace("-", "").strip()
        if not ecu_pn or not self._rom_pns:
            self._matched = False
            return
        new_match = ecu_pn in self._rom_pns
        if not new_match and ecu_pn:
            self.mismatch.emit(ecu_pn,
                               self._rom_pns[0] if self._rom_pns else "")
        self._matched = new_match


# ── Status helpers ────────────────────────────────────────────────────────────

def status_label(monitor: KWPMonitor, rom_pn: str) -> tuple:
    """Return (text, colour_hex) for the KWP status indicator."""
    if not _KWP_AVAILABLE:
        return "KWPBridge not installed", "#555555"
    if not kwpbridge_running():
        return "KWPBridge not running", "#555555"
    ecu_pn = monitor.current_pn() if monitor else ""
    if not ecu_pn:
        return "KWPBridge running — awaiting ECU", "#ffaa00"
    if monitor and monitor.is_matched():
        return f"🟢  {ecu_pn}  ·  ECU matches ROM", "#2dff6e"
    return f"🟡  {ecu_pn}  ≠  {rom_pn}  ·  mismatch", "#ffaa00"


def live_summary(lv: LiveValues) -> str:
    """One-line summary for the status strip."""
    if lv is None or not lv.valid:
        return ""
    parts = []
    if lv.rpm     is not None: parts.append(f"{lv.rpm:.0f} RPM")
    if lv.coolant is not None: parts.append(f"{lv.coolant:.0f}°C")
    if lv.lambda_ is not None: parts.append(f"λ {lv.lambda_:.3f}")
    if lv.timing  is not None: parts.append(f"{lv.timing:.1f}° ign")
    return "  ·  ".join(parts)


# ── DashboardWindow ───────────────────────────────────────────────────────────

class DashboardWindow:
    """
    Floating live-data dashboard that subscribes to a KWPMonitor.

    Opens a standalone QWidget window showing RPM, coolant, load, lambda,
    timing, and battery. Works with both real ECU and mock server — whatever
    the KWPMonitor is receiving.

    Usage (from MainWindow):
        self._dash = DashboardWindow(self._monitor, parent=self)
        self._dash.show()
    """

    # Colour constants
    _C_BG     = "#1a1a1a"
    _C_PANEL  = "#252525"
    _C_BORDER = "#333333"
    _C_TEXT   = "#e8e8e8"
    _C_DIM    = "#888888"
    _C_GREEN  = "#2dff6e"
    _C_AMBER  = "#ffaa00"
    _C_RED    = "#ff4444"
    _C_BLUE   = "#4488ff"
    _C_PURPLE = "#aa66ff"

    def __init__(self, monitor: 'KWPMonitor', parent=None):
        from PyQt5.QtWidgets import (
            QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
            QLabel, QFrame, QPushButton,
        )
        from PyQt5.QtCore import Qt, QTimer
        from PyQt5.QtGui import QFont, QFontDatabase

        self._monitor = monitor
        self._win = QWidget(parent, Qt.Window)
        self._win.setWindowTitle("Live ECU — Dashboard")
        self._win.setMinimumSize(560, 340)
        self._win.setStyleSheet(
            f"background:{self._C_BG}; color:{self._C_TEXT};"
        )

        root = QVBoxLayout(self._win)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Status bar ────────────────────────────────────────────────────────
        status_row = QHBoxLayout()
        self._lbl_status = QLabel("● Waiting for data…")
        self._lbl_status.setStyleSheet(
            f"color:{self._C_DIM}; font-size:10px; letter-spacing:1px;"
        )
        self._lbl_scenario = QLabel("")
        self._lbl_scenario.setStyleSheet(
            f"color:{self._C_PURPLE}; font-size:10px; font-style:italic;"
        )
        status_row.addWidget(self._lbl_status)
        status_row.addStretch()
        status_row.addWidget(self._lbl_scenario)
        root.addLayout(status_row)

        # ── Separator ─────────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(f"color:{self._C_BORDER};")
        root.addWidget(sep)

        # ── Gauge grid  (2 rows × 3 cols) ─────────────────────────────────────
        grid = QGridLayout()
        grid.setSpacing(8)
        root.addLayout(grid)

        self._gauges = {}

        specs = [
            # (key,      label,    unit, min,  max,  warn_lo, warn_hi, crit_hi, row, col)
            ("rpm",      "RPM",    "",   400,  7000, None,    6000,    6500,    0,   0),
            ("coolant",  "COOLANT","°C", 20,   120,  60,      105,     115,     0,   1),
            ("load",     "LOAD",   "%",  0,    100,  None,    90,      98,      0,   2),
            ("lambda",   "LAMBDA", "λ",  0.70, 1.30, None,    None,    None,    1,   0),
            ("timing",   "TIMING", "°",  -5,   45,   None,    None,    None,    1,   1),
            ("battery",  "BATT",   "V",  10,   16,   11.5,    15.0,    None,    1,   2),
        ]

        for key, label, unit, vmin, vmax, warn_lo, warn_hi, crit_hi, row, col in specs:
            panel = self._make_gauge_panel(key, label, unit,
                                           vmin, vmax, warn_lo, warn_hi, crit_hi)
            grid.addWidget(panel, row, col)

        # ── Separator ─────────────────────────────────────────────────────────
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet(f"color:{self._C_BORDER};")
        root.addWidget(sep2)

        # ── Mini strip ────────────────────────────────────────────────────────
        self._lbl_strip = QLabel("")
        self._lbl_strip.setStyleSheet(
            f"color:{self._C_DIM}; font-size:10px; font-family:Consolas;"
        )
        root.addWidget(self._lbl_strip)

        # ── Wire to monitor ────────────────────────────────────────────────────
        monitor.live_data.connect(self._on_live)
        monitor.disconnected.connect(self._on_disconnect)
        monitor.connected.connect(self._on_connect)

    def _make_gauge_panel(self, key, label, unit,
                          vmin, vmax, warn_lo, warn_hi, crit_hi):
        from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar
        from PyQt5.QtCore import Qt

        panel = QWidget()
        panel.setStyleSheet(
            f"background:{self._C_PANEL}; border:1px solid {self._C_BORDER}; border-radius:4px;"
        )
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(2)

        lbl_name = QLabel(label)
        lbl_name.setStyleSheet(
            f"color:{self._C_DIM}; font-size:9px; letter-spacing:2px; border:none;"
        )

        lbl_val = QLabel("—")
        lbl_val.setAlignment(Qt.AlignCenter)
        lbl_val.setStyleSheet(
            f"color:{self._C_TEXT}; font-size:28px; font-weight:bold; border:none;"
        )

        lbl_unit = QLabel(unit)
        lbl_unit.setAlignment(Qt.AlignCenter)
        lbl_unit.setStyleSheet(
            f"color:{self._C_DIM}; font-size:10px; border:none;"
        )

        bar = QProgressBar()
        bar.setRange(int(vmin * 10), int(vmax * 10))
        bar.setValue(int(vmin * 10))
        bar.setTextVisible(False)
        bar.setFixedHeight(4)
        bar.setStyleSheet(
            f"QProgressBar{{background:{self._C_BG}; border-radius:2px; border:none;}}"
            f"QProgressBar::chunk{{background:{self._C_GREEN}; border-radius:2px;}}"
        )

        lay.addWidget(lbl_name)
        lay.addWidget(lbl_val)
        lay.addWidget(lbl_unit)
        lay.addWidget(bar)

        self._gauges[key] = {
            "lbl_val":  lbl_val,
            "bar":      bar,
            "unit":     unit,
            "vmin":     vmin,
            "vmax":     vmax,
            "warn_lo":  warn_lo,
            "warn_hi":  warn_hi,
            "crit_hi":  crit_hi,
        }
        return panel

    def _colour_for(self, key, val):
        g = self._gauges[key]
        if val is None:
            return self._C_DIM
        if g["crit_hi"] is not None and val >= g["crit_hi"]:
            return self._C_RED
        if g["warn_hi"] is not None and val >= g["warn_hi"]:
            return self._C_AMBER
        if g["warn_lo"] is not None and val <= g["warn_lo"]:
            return self._C_AMBER
        if key == "lambda":
            if 0.95 <= val <= 1.05:
                return self._C_GREEN
            if abs(val - 1.0) <= 0.15:
                return self._C_AMBER
            return self._C_RED
        return self._C_GREEN

    def _update_gauge(self, key, val):
        if key not in self._gauges:
            return
        g   = self._gauges[key]
        col = self._colour_for(key, val)

        if val is None:
            g["lbl_val"].setText("—")
            g["lbl_val"].setStyleSheet(
                f"color:{self._C_DIM}; font-size:28px; font-weight:bold; border:none;"
            )
            return

        # Format value
        unit = g["unit"]
        if unit == "λ":
            txt = f"{val:.3f}"
        elif unit == "°" or unit == "V":
            txt = f"{val:.1f}"
        elif unit == "%":
            txt = f"{val:.0f}"
        else:
            txt = f"{val:.0f}"

        g["lbl_val"].setText(txt)
        g["lbl_val"].setStyleSheet(
            f"color:{col}; font-size:28px; font-weight:bold; border:none;"
        )

        # Bar
        clamped = max(g["vmin"], min(g["vmax"], val))
        g["bar"].setValue(int(clamped * 10))
        chunk_col = col
        g["bar"].setStyleSheet(
            f"QProgressBar{{background:{self._C_BG}; border-radius:2px; border:none;}}"
            f"QProgressBar::chunk{{background:{chunk_col}; border-radius:2px;}}"
        )

    def _on_live(self, lv: 'LiveValues'):
        self._update_gauge("rpm",     lv.rpm)
        self._update_gauge("coolant", lv.coolant)
        self._update_gauge("load",    lv.load_pct)
        self._update_gauge("lambda",  lv.lambda_)
        self._update_gauge("timing",  lv.timing)
        self._update_gauge("battery", lv.battery)

        # Status strip
        parts = []
        if lv.rpm      is not None: parts.append(f"{lv.rpm:.0f} RPM")
        if lv.coolant  is not None: parts.append(f"{lv.coolant:.0f}°C")
        if lv.lambda_  is not None: parts.append(f"λ {lv.lambda_:.3f}")
        if lv.timing   is not None: parts.append(f"{lv.timing:.1f}° ign")
        if lv.load_pct is not None: parts.append(f"{lv.load_pct:.0f}% load")
        if lv.battery  is not None: parts.append(f"{lv.battery:.1f}V")
        self._lbl_strip.setText("  ·  ".join(parts))

        # Mock scenario tag
        scenario = getattr(lv, '_mock_scenario', None)
        if scenario:
            self._lbl_scenario.setText(f"⚙  MOCK  ·  {scenario}")
        else:
            self._lbl_scenario.setText("")

        col = self._C_GREEN
        src = f"MOCK  ·  {lv.ecu_pn}" if scenario else (lv.ecu_pn or "—")
        self._lbl_status.setText(f"● Live  ·  {src}")
        self._lbl_status.setStyleSheet(
            f"color:{col}; font-size:10px; letter-spacing:1px;"
        )

    def _on_connect(self, ecu_pn: str):
        self._lbl_status.setText(f"● Connected  ·  {ecu_pn}")
        self._lbl_status.setStyleSheet(
            f"color:{self._C_GREEN}; font-size:10px; letter-spacing:1px;"
        )

    def _on_disconnect(self):
        self._lbl_status.setText("● Disconnected")
        self._lbl_status.setStyleSheet(
            f"color:{self._C_RED}; font-size:10px; letter-spacing:1px;"
        )
        self._lbl_strip.setText("")
        for key in self._gauges:
            self._update_gauge(key, None)

    def show(self):
        self._win.show()
        self._win.raise_()
        self._win.activateWindow()

    def hide(self):
        self._win.hide()

    def is_visible(self):
        return self._win.isVisible()

    def close(self):
        try:
            self._monitor.live_data.disconnect(self._on_live)
            self._monitor.disconnected.disconnect(self._on_disconnect)
            self._monitor.connected.disconnect(self._on_connect)
        except Exception:
            pass
        self._win.close()
