"""
hachirom/kwp.py — KWPBridge integration for HachiROM.

Thin wrapper around kwpbridge.client that:
  - polls KWPBridge on localhost:50266
  - emits Qt signals for state changes
  - provides the safety gate (part number match check)
  - extracts 7A-specific values from state dicts

Designed to degrade gracefully — if kwpbridge is not installed or
not running, HachiROM works exactly as before.
"""

import logging
from typing import Optional

log = logging.getLogger(__name__)

# ── Optional import — KWPBridge may not be installed ────────────────────────

try:
    from kwpbridge.client import KWPClient, is_running as _kwp_is_running
    from kwpbridge.constants import DEFAULT_PORT
    _KWP_AVAILABLE = True
except ImportError:
    _KWP_AVAILABLE = False
    DEFAULT_PORT   = 50266

try:
    from PyQt5.QtCore import QObject, QTimer, pyqtSignal
    _QT_AVAILABLE = True
except ImportError:
    _QT_AVAILABLE = False


def kwpbridge_available() -> bool:
    """True if kwpbridge package is installed."""
    return _KWP_AVAILABLE


def kwpbridge_running() -> bool:
    """True if KWPBridge is running on localhost:50266."""
    if not _KWP_AVAILABLE:
        return False
    try:
        return _kwp_is_running(port=DEFAULT_PORT)
    except Exception:
        return False


# ── Live values extracted from a state dict ──────────────────────────────────

class LiveValues:
    """
    Decoded 7A measuring block values from a KWPBridge state dict.

    All values are None if not available (KWPBridge not connected,
    or cell not present in state).
    """

    def __init__(self, state: dict):
        self.rpm:     Optional[float] = None
        self.load:    Optional[float] = None   # raw 1-255
        self.load_pct: Optional[float] = None  # 0-100%
        self.coolant: Optional[float] = None   # °C
        self.lambda_:  Optional[float] = None  # λ (1.0 = stoich)
        self.timing:  Optional[float] = None   # °BTDC
        self.battery: Optional[float] = None   # V
        self.ecu_pn:  str = ""

        if not state or not state.get("connected"):
            return

        self.ecu_pn = state.get("ecu_id", {}).get("part_number", "")

        groups = state.get("groups", {})
        group0 = groups.get("0", groups.get(0, {}))
        cells  = {c["index"]: c for c in group0.get("cells", [])}

        def _val(idx):
            c = cells.get(idx)
            return c["value"] if c else None

        self.coolant  = _val(1)   # °C decoded
        self.load     = _val(2)   # raw
        self.rpm      = _val(3)   # RPM decoded
        self.lambda_  = _val(8)   # λ decoded (128 raw = 1.0)
        self.timing   = _val(10)  # °BTDC decoded
        self.battery  = _val(4)   # V if present

        if self.load is not None:
            self.load_pct = (self.load / 255.0) * 100.0

    @property
    def valid(self) -> bool:
        return self.rpm is not None

    def lambda_colour(self) -> str:
        """Return hex colour string based on lambda value."""
        if self.lambda_ is None:
            return "#444444"
        if 0.95 <= self.lambda_ <= 1.05:
            return "#2dff6e"   # green — at target
        if 0.85 <= self.lambda_ < 0.95 or 1.05 < self.lambda_ <= 1.15:
            return "#ffaa00"   # amber — off target
        return "#ff4444"       # red — significantly off


# ── Qt signal emitter (only built when Qt is available) ─────────────────────

if _QT_AVAILABLE and _KWP_AVAILABLE:

    class KWPMonitor(QObject):
        """
        Qt object that wraps KWPClient and emits signals for HachiROM.

        Signals
        -------
        connected(str)        — ecu part number when KWPBridge connects
        disconnected()        — KWPBridge disconnected or stopped
        live_data(LiveValues) — new state received (fires at poll rate)
        mismatch(str, str)    — (ecu_pn, rom_pn) when part numbers don't match
        """

        connected    = pyqtSignal(str)        # ecu part number
        disconnected = pyqtSignal()
        live_data    = pyqtSignal(object)     # LiveValues
        mismatch     = pyqtSignal(str, str)   # (ecu_pn, rom_pn)

        def __init__(self, parent=None):
            super().__init__(parent)
            self._client:   KWPClient | None = None
            self._rom_pn:   str = ""
            self._matched   = False
            self._was_connected = False

            # Poll timer — checks KWPBridge every second when not connected,
            # faster when connected (state comes from broadcast anyway)
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._poll)
            self._timer.start(1000)

        def set_rom_part_number(self, pn: str):
            """Tell the monitor what ROM is loaded — used for safety gate."""
            self._rom_pn = pn.upper().replace("-", "").strip()
            self._check_match()

        def start(self):
            self._timer.start(1000)

        def stop(self):
            self._timer.stop()
            self._disconnect_client()

        def is_matched(self) -> bool:
            """True when KWPBridge is connected AND ECU matches loaded ROM."""
            return self._matched

        def current_pn(self) -> str:
            if self._client and self._client.state:
                return self._client.state.get(
                    "ecu_id", {}).get("part_number", "")
            return ""

        # ── Internal ──────────────────────────────────────────────────────────

        def _poll(self):
            if self._client and self._client.connected:
                # Already connected — process state
                state = self._client.state
                if state:
                    lv = LiveValues(state)
                    if lv.valid:
                        self.live_data.emit(lv)
                    self._check_match()
                return

            # Not connected — check if KWPBridge is now running
            if kwpbridge_running():
                self._connect_client()

        def _connect_client(self):
            try:
                self._client = KWPClient(port=DEFAULT_PORT)
                self._client.on_connect(self._on_kwp_connect)
                self._client.on_disconnect(self._on_kwp_disconnect)
                self._client.on_state(self._on_kwp_state)
                self._client.connect(auto_reconnect=False)
                log.info("KWPMonitor: connecting to KWPBridge")
            except Exception as e:
                log.debug(f"KWPMonitor: connect error: {e}")
                self._client = None

        def _disconnect_client(self):
            if self._client:
                try:
                    self._client.disconnect()
                except Exception:
                    pass
                self._client = None
            self._matched = False

        def _on_kwp_connect(self):
            pn = self.current_pn()
            log.info(f"KWPMonitor: KWPBridge connected, ECU={pn}")
            self.connected.emit(pn)
            self._check_match()

        def _on_kwp_disconnect(self):
            log.info("KWPMonitor: KWPBridge disconnected")
            self._matched = False
            self.disconnected.emit()

        def _on_kwp_state(self, state: dict):
            lv = LiveValues(state)
            if lv.valid:
                self.live_data.emit(lv)
            self._check_match()

        def _check_match(self):
            if not self._client or not self._client.state:
                if self._matched:
                    self._matched = False
                return

            ecu_pn = self.current_pn().upper().replace("-", "").strip()
            if not ecu_pn or not self._rom_pn:
                self._matched = False
                return

            new_match = (ecu_pn == self._rom_pn)
            if not new_match and ecu_pn:
                self.mismatch.emit(ecu_pn, self._rom_pn)
            self._matched = new_match

else:
    # Stub when Qt or kwpbridge not available
    class KWPMonitor:  # type: ignore
        def __init__(self, parent=None):
            pass
        def set_rom_part_number(self, pn): pass
        def start(self): pass
        def stop(self):  pass
        def is_matched(self) -> bool: return False
        def current_pn(self) -> str:  return ""


# ── Status string helpers ─────────────────────────────────────────────────────

def status_label(monitor: "KWPMonitor", rom_pn: str) -> tuple[str, str]:
    """
    Return (text, colour) for the KWP status indicator.

    States:
      🔴  KWPBridge not available / not running
      🟡  Connected but ECU ≠ ROM part number
      🟢  Connected and ECU matches ROM
    """
    if not _KWP_AVAILABLE:
        return "KWPBridge not installed", "#555555"

    if not kwpbridge_running():
        return "KWPBridge not running", "#555555"

    ecu_pn = monitor.current_pn() if monitor else ""
    if not ecu_pn:
        return "KWPBridge running — no ECU", "#ffaa00"

    if monitor and monitor.is_matched():
        return f"🟢  {ecu_pn}  ·  ECU matches ROM", "#2dff6e"

    return f"🟡  {ecu_pn}  ≠  {rom_pn}  ·  mismatch", "#ffaa00"


def live_summary(lv: "LiveValues") -> str:
    """One-line summary string for the status strip."""
    if lv is None or not lv.valid:
        return ""
    parts = []
    if lv.rpm     is not None: parts.append(f"{lv.rpm:.0f} RPM")
    if lv.coolant is not None: parts.append(f"{lv.coolant:.0f}°C")
    if lv.lambda_ is not None: parts.append(f"λ {lv.lambda_:.3f}")
    if lv.timing  is not None: parts.append(f"{lv.timing:.1f}° ign")
    return "  ·  ".join(parts)
