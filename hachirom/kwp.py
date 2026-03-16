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
        self._client  = None          # KWPClient instance or None
        self._rom_pns: list[str] = []
        self._matched  = False

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
