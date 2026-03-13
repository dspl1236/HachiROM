"""
HachiROM — Map I/O, checksum, and compare tools.
Checksum algorithm confirmed from 034 Motorsport decompiled Checksum.applyOldStyle.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from .roms import ROMVariant, MapDef


# ---------------------------------------------------------------------------
# Map read / write
# ---------------------------------------------------------------------------

def read_map(data: bytes, map_def: MapDef) -> list[list[int]]:
    """Extract a 2D map from ROM bytes. Returns rows×cols list of raw bytes."""
    rows, cols, addr = map_def.rows, map_def.cols, map_def.address
    result = []
    for r in range(rows):
        row = []
        for c in range(cols):
            offset = addr + r * cols + c
            row.append(data[offset] if offset < len(data) else 0)
        result.append(row)
    return result


def read_map_decoded(data: bytes, map_def: MapDef) -> list[list]:
    """Like read_map but applies the decode function if one exists."""
    raw = read_map(data, map_def)
    if map_def.decode is None:
        return raw
    return [[map_def.decode(v) for v in row] for row in raw]


def write_map(data: bytearray, map_def: MapDef, values: list[list[int]]) -> bytearray:
    """Write raw byte values back into the ROM bytearray."""
    addr, rows, cols = map_def.address, map_def.rows, map_def.cols
    for r in range(rows):
        for c in range(cols):
            offset = addr + r * cols + c
            if r < len(values) and c < len(values[r]) and offset < len(data):
                data[offset] = max(0, min(255, int(values[r][c])))
    return data


def write_map_encoded(data: bytearray, map_def: MapDef, values: list[list]) -> bytearray:
    """Write decoded (human) values back after applying encode function."""
    if map_def.encode is None:
        return write_map(data, map_def, values)
    raw = [[map_def.encode(v) for v in row] for row in values]
    return write_map(data, map_def, raw)


def read_scalar(data: bytes, address: int, factor: float = 1.0) -> float:
    """Read a single byte scalar and apply factor."""
    return data[address] * factor if address < len(data) else 0.0


def write_scalar(data: bytearray, address: int, value: float, factor: float = 1.0) -> bytearray:
    """Write a scalar byte (value / factor, clamped 0-255)."""
    data[address] = max(0, min(255, round(value / factor))) if factor else 0
    return data


def read_axis(data: bytes, address: int, count: int, factor: float) -> list:
    """Read count axis breakpoints from ROM and decode with factor."""
    return [round(data[address + i] * factor, 1) for i in range(count)
            if address + i < len(data)]


# ---------------------------------------------------------------------------
# Checksum (confirmed from 034 decompiled Checksum.applyOldStyle)
# ---------------------------------------------------------------------------

def compute_sum(data: bytes) -> int:
    """Sum all bytes of the (up to) 32KB native ROM."""
    return sum(data[:32768])


def verify_checksum(data: bytes, variant: ROMVariant) -> bool:
    """Return True if this ROM passes the checksum for its variant."""
    cs = variant.checksum
    return compute_sum(data) == cs.get("target", -1)


def apply_checksum(data: bytes, variant: ROMVariant) -> bytearray:
    """
    Fix checksum: redistribute bytes in correction region so
    sum(32KB ROM) == target. Uses same distribute-one-at-a-time algorithm
    as 034 Motorsport tool. Returns corrected 32KB bytearray.
    """
    cs     = variant.checksum
    target = cs["target"]
    cf     = cs["cs_from"]
    ct     = cs["cs_to"]
    n      = ct - cf + 1

    rom   = bytearray(data[:32768])
    delta = sum(rom) - target
    if delta == 0:
        return rom

    sign = 1 if delta > 0 else -1
    remaining = abs(delta)
    passes = 0
    while remaining > 0:
        passes += 1
        if passes > 256:
            break
        absorbed = 0
        for i in range(n):
            if remaining == 0:
                break
            b = rom[cf + i]
            if sign == 1 and b > 0:
                rom[cf + i] -= 1
                absorbed += 1
                remaining -= 1
            elif sign == -1 and b < 255:
                rom[cf + i] += 1
                absorbed += 1
                remaining -= 1
        if absorbed == 0:
            break
    return rom


# ---------------------------------------------------------------------------
# ROM compare / diff
# ---------------------------------------------------------------------------

@dataclass
class DiffByte:
    address:  int
    a:        int
    b:        int
    map_name: Optional[str] = None


def compare_roms(data_a: bytes, data_b: bytes,
                 variant: Optional[ROMVariant] = None) -> list[DiffByte]:
    """
    Byte-by-byte diff. Tags each changed byte with its map region name
    if a variant is provided.
    """
    length = min(len(data_a), len(data_b))
    diffs: list[DiffByte] = []

    addr_map: dict[int, str] = {}
    if variant:
        for m in variant.maps:
            for r in range(m.rows):
                for c in range(m.cols):
                    addr_map[m.address + r * m.cols + c] = m.name

    for addr in range(length):
        if data_a[addr] != data_b[addr]:
            diffs.append(DiffByte(addr, data_a[addr], data_b[addr],
                                  addr_map.get(addr)))
    return diffs


def diff_summary(diffs: list[DiffByte]) -> dict[str, int]:
    """Summarise diff count by map region."""
    from collections import Counter
    c: Counter = Counter(d.map_name or "unmapped" for d in diffs)
    return dict(c)


# ---------------------------------------------------------------------------
# MAF hardware patch — 266D only
# ---------------------------------------------------------------------------

from .roms import (MAF_AXIS_ADDR_FUEL, MAF_AXIS_ADDR_TIMING,
                   MAF_AXIS_LEN, MAF_PROFILES)


def detect_maf_patch(data: bytes) -> str:
    """
    Inspect the two MAF axis tables in a 266D/266B ROM and return the profile
    key that matches, or ``"unknown"`` if no known profile matches.

    Returns one of:
        ``"stock_7a"``        — 7A Hitachi sensor, 50mm stock housing (unmodified)
        ``"aah_v6_housing"``  — 7A Hitachi sensor transplanted into 74mm AAH V6 housing
        ``"sensor_1_8t_60"``  — Bosch 1.8T sensor, 60mm 1.8T housing  [EXPERIMENTAL]
        ``"sensor_1_8t_vr6"`` — Bosch 1.8T sensor, 69.85mm VR6/TT225 housing  [EXPERIMENTAL]
        ``"inconsistent"``    — fuel and timing axis copies disagree (ROM may be corrupt)
        ``"unknown"``         — axis bytes don't match any known profile

    Detection strategy
    ------------------
    Both axis copies (fuel @ 0x05D0, timing @ 0x05E0) are checked.  The fuel
    axis is the primary match target; the timing copy is used as a cross-check.
    If the two copies disagree the ROM is flagged ``"inconsistent"`` so the UI
    can warn the user.  ``"stock_7a"`` is a valid detection result — it means
    the ROM has never been patched (or has been restored to stock).
    """
    if len(data) < MAF_AXIS_ADDR_TIMING + MAF_AXIS_LEN:
        return "unknown"

    fuel_axis   = list(data[MAF_AXIS_ADDR_FUEL  : MAF_AXIS_ADDR_FUEL   + MAF_AXIS_LEN])
    timing_axis = list(data[MAF_AXIS_ADDR_TIMING : MAF_AXIS_ADDR_TIMING + MAF_AXIS_LEN])

    matched = "unknown"
    for key, profile in MAF_PROFILES.items():
        if fuel_axis == profile["axis"]:
            matched = key
            break

    # Cross-check: timing axis should match too.  If not, flag as inconsistent.
    if matched != "unknown":
        if timing_axis != MAF_PROFILES[matched]["axis"]:
            return "inconsistent"

    return matched


def apply_maf_patch(data: bytes, profile_key: str) -> bytes:
    """
    Return a new bytes object with the MAF axis tables rewritten to match
    *profile_key*.  Both copies (fuel and timing) are updated together.

    Raises ``KeyError`` if *profile_key* is not in ``MAF_PROFILES``.
    Raises ``ValueError`` if *data* is too short.
    """
    if profile_key not in MAF_PROFILES:
        raise KeyError(f"Unknown MAF profile: {profile_key!r}")
    if len(data) < MAF_AXIS_ADDR_TIMING + MAF_AXIS_LEN:
        raise ValueError("ROM data too short for MAF axis patch")

    axis = MAF_PROFILES[profile_key]["axis"]
    rom  = bytearray(data)
    for i, v in enumerate(axis):
        rom[MAF_AXIS_ADDR_FUEL   + i] = v
        rom[MAF_AXIS_ADDR_TIMING + i] = v
    return bytes(rom)


# ---------------------------------------------------------------------------
# CO pot (pin 4) disable patch — 266D only
# ---------------------------------------------------------------------------
#
# Background
# ----------
# The 7A ECU reads an idle lambda trim voltage on MAF connector pin 4 from the
# CO pot integrated inside the stock Hitachi sensor head.  Pin 4 is an ECU
# INPUT — the pot wiper feeds a voltage back to the ECU; the ECU does not
# source voltage on this pin.
#
# When fitting a replacement sensor with no CO pot (e.g. Bosch 1.8T) pin 4
# is left floating.  The ECU sees this as out-of-range and stores fault 00521
# "CO-Poti Unterbrechung oder Kurzschluss" (CO pot open/short circuit).
#
# This patch makes the ECU accept any voltage (including floating/0V) on
# pin 4 without faulting, and zeros the trim gain so pin 4 has no effect on
# fuelling.
#
# Bytes found by diffing two clean stock ROMs (266D stock .034 vs 266B stock
# .034, both unscrambled) — confirmed identical in both variants (fixed
# scalars, not calibration data):
#
#   0x0762 = 10  (0x0A) — CO pot ADC low fault threshold  (~0.20V)
#   0x0763 = 238 (0xEE) — CO pot ADC high fault threshold (~4.67V)
#   0x0777 = 128 (0x80) — CO pot neutral target (midpoint, 2.5V)
#   0x0778 = 50  (0x32) — CO pot trim authority window (±50 ADC counts)
#   0x0779 = 4   (0x04) — CO pot trim gain per ADC count
#
# Fault table entry (266D only — 266B has different fault layout):
#   0x0AC9-0x0ACB = 02 09 1E  — fault 0x0209 (521 decimal), condition 0x1E
#
# Patch strategy
# --------------
# Three bytes are modified:
#   0x0762 → 0x00  widen low  threshold to 0   (0.00V) — no low-side fault
#   0x0763 → 0xFF  widen high threshold to 255 (5.00V) — no high-side fault
#   0x0779 → 0x00  zero the trim gain           — pin 4 has zero effect on fuelling
#
# Result: fault 00521 is never triggered regardless of pin 4 voltage, and
# the CO pot trim is permanently at neutral (0x0777 = 128 unchanged).
# The neutral target byte (0x0777) and window byte (0x0778) are left as-is —
# they are harmless with gain = 0.
#
# The fault table entry at 0x0AC9 is NOT modified — the fault can still be
# manually read via VAG-COM if triggered by something else, but with thresholds
# 0–255 it will never be triggered by a floating or resistor-held pin 4.
#
# Safe for: any 266D ROM with a 1.8T or other no-CO-pot MAF sensor fitted.
# NOT needed when fitting the 7A Hitachi sensor into the AAH V6 housing
# (CO pot is retained in that conversion — pin 4 wiring unchanged).
# ---------------------------------------------------------------------------

CO_POT_LOW_THRESHOLD_ADDR   = 0x0762   # ADC low  fault threshold (stock = 10)
CO_POT_HIGH_THRESHOLD_ADDR  = 0x0763   # ADC high fault threshold (stock = 238)
CO_POT_NEUTRAL_ADDR         = 0x0777   # neutral target ADC count  (stock = 128)
CO_POT_WINDOW_ADDR          = 0x0778   # trim authority window      (stock = 50)
CO_POT_GAIN_ADDR            = 0x0779   # trim gain per ADC count    (stock = 4)

CO_POT_PATCH_ADDRS = {
    CO_POT_LOW_THRESHOLD_ADDR:  0x00,   # widen: accept 0V
    CO_POT_HIGH_THRESHOLD_ADDR: 0xFF,   # widen: accept 5V
    CO_POT_GAIN_ADDR:           0x00,   # zero gain: trim has no effect
}

CO_POT_STOCK_ADDRS = {
    CO_POT_LOW_THRESHOLD_ADDR:  0x0A,   # restore: 10 (~0.20V low threshold)
    CO_POT_HIGH_THRESHOLD_ADDR: 0xEE,   # restore: 238 (~4.67V high threshold)
    CO_POT_GAIN_ADDR:           0x04,   # restore: gain = 4
}


def detect_co_pot_patch(data: bytes) -> str:
    """
    Inspect the CO pot scalar bytes in a 266D ROM and return the patch state.

    Returns:
        ``"stock"``    — all three bytes at stock values (CO pot active)
        ``"patched"``  — all three bytes at patched values (CO pot disabled)
        ``"unknown"``  — bytes don't match either known state (manual edit?)
    """
    if len(data) < CO_POT_GAIN_ADDR + 1:
        return "unknown"

    is_patched = all(data[addr] == val for addr, val in CO_POT_PATCH_ADDRS.items())
    is_stock   = all(data[addr] == val for addr, val in CO_POT_STOCK_ADDRS.items())

    if is_patched:
        return "patched"
    if is_stock:
        return "stock"
    return "unknown"


def apply_co_pot_patch(data: bytes, disable: bool = True) -> bytes:
    """
    Return a new bytes object with the CO pot trim either disabled or restored.

    Parameters
    ----------
    data    : raw 32 768-byte 266D ROM
    disable : True  → write patch values (disable CO pot, suppress fault 00521)
              False → restore stock values

    Raises ``ValueError`` if *data* is too short.
    """
    if len(data) < CO_POT_GAIN_ADDR + 1:
        raise ValueError("ROM data too short for CO pot patch")

    patch_map = CO_POT_PATCH_ADDRS if disable else CO_POT_STOCK_ADDRS
    rom = bytearray(data)
    for addr, val in patch_map.items():
        rom[addr] = val
    return bytes(rom)
