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


# ---------------------------------------------------------------------------
# Injection scaler resolution trick — AAH / MMS100 / MMS-200
# ---------------------------------------------------------------------------
#
# The injection scaler at 0x077E is a global multiplier on all injector pulse
# widths.  Stock AAH = 100 (1.0×).  When set to 50 (0.5×) the injectors fire
# at half the duration for any given fuel map cell value, so to deliver the
# same fuelling the fuel map cells must encode twice the lambda value.
#
# This doubles the effective resolution of the 8-bit fuel map — each step
# is half the fuelling change it would be at scaler=100.  034Motorsport used
# this technique on their Stage 1 AAH tune.
#
# IMPORTANT: This patch only rescales the existing fuel map mathematically.
# It does NOT reproduce the 034 Stage 1 tune — 034 also retuned the map
# values themselves.  This patch is useful for:
#   - Tuning with higher resolution starting from a stock baseline
#   - Round-tripping a rescaled ROM back to stock encoding for comparison
#
# Fuel map encoding (AAH / 266B):
#   lambda = signed(byte) × 0.007813 + 1.0
#   signed(byte) = (lambda - 1.0) / 0.007813
#
# Rescale from scaler=100 → scaler=50:
#   To deliver the same fuelling: new_lambda = old_lambda × 2.0
#   new_signed = (old_lambda × 2.0 - 1.0) / 0.007813
#   new_raw    = new_signed & 0xFF  (two's complement)
#
# Rescale from scaler=50 → scaler=100 (reverse):
#   old_lambda = (new_lambda + 1.0) / 2.0  ... actually:
#   old_signed = (old_lambda - 1.0) / 0.007813
#   old_lambda = signed(new_raw) × 0.007813 + 1.0
#   old_lambda_delivered = old_lambda / 2.0  (at scaler=50)
#   to restore: old_raw = round((old_lambda_delivered - 1.0) / 0.007813) & 0xFF
# ---------------------------------------------------------------------------

INJ_SCALER_ADDR  = 0x077E
INJ_SCALER_STOCK = 100
INJ_SCALER_HALF  = 50

FUEL_MAP_ADDR    = 0x0000
FUEL_MAP_SIZE    = 256   # 16×16

_LAMBDA_STEP = 0.007813


def detect_injection_scaler_trick(data: bytes, variant_key: str = '') -> str:
    """
    Detect whether the injection scaler resolution trick is applied.

    Only meaningful on AAH (4A0906266), MMS-200 (8A0906266A) and 266B
    (893906266B) — variants where 0x077E is a genuine tunable scaler.
    On 266D the byte at 0x077E is firmware-fixed at 50 and not a scaler.

    Returns
    -------
    'stock'       — scaler=100, fuel map in signed near-zero range (λ≈1.0)
    'halved'      — scaler=50,  fuel map rescaled (~190-230 raw)
    'not_applicable' — ROM does not use a tunable injection scaler
    'unknown'     — scaler or map values don't match either known state
    """
    if len(data) < INJ_SCALER_ADDR + 1:
        return 'unknown'

    scaler = data[INJ_SCALER_ADDR]
    fuel   = list(data[FUEL_MAP_ADDR:FUEL_MAP_ADDR + FUEL_MAP_SIZE])
    mean   = sum(fuel) / len(fuel)

    # 266D fuel maps run natively with mean ~225 and scaler=50 is firmware
    # constant — distinguish by checking if fuel map is signed-near-zero style
    # AAH stock: mean ~125 (signed values cluster around 0)
    # AAH halved: mean ~219 (values 190-240)
    # 266D/266B stock: mean ~220-230 but this is native encoding not a trick

    # Only applicable to variants with a tunable injection scaler
    # 266D firmware-fixes 0x077E at 50 — not a scaler, not applicable
    AAH_VARIANTS = {'AAH', 'MMS200'}
    if variant_key and variant_key not in AAH_VARIANTS:
        return 'not_applicable'

    # Without variant info, use heuristic: AAH stock mean clusters near 128
    # 266D/266B native encoding sits at mean ~220-230 (different formula)
    # If no variant supplied and mean > 175, assume 266D/266B native → not applicable
    if not variant_key and mean > 175 and scaler == INJ_SCALER_HALF:
        return 'not_applicable'

    if scaler == INJ_SCALER_STOCK and 100 <= mean <= 160:
        return 'stock'
    if scaler == INJ_SCALER_HALF and 180 <= mean <= 240:
        return 'halved'
    return 'unknown'


def apply_injection_scaler_trick(data: bytes, halve: bool = True) -> bytes:
    """
    Apply or reverse the injection scaler resolution trick.

    Mathematically rescales the 16×16 fuel map to maintain equivalent
    fuelling while halving (or doubling) the injection scaler.

    Parameters
    ----------
    data  : raw 32 768-byte AAH / 266B / MMS-200 ROM
    halve : True  → scaler 100→50, rescale map (higher resolution)
            False → scaler 50→100, rescale map back to stock encoding

    Raises ``ValueError`` if data is too short or current state conflicts.
    """
    if len(data) < INJ_SCALER_ADDR + 1:
        raise ValueError("ROM data too short for injection scaler patch")

    current_state = detect_injection_scaler_trick(data)
    if halve and current_state == 'halved':
        raise ValueError("Injection scaler already halved")
    if not halve and current_state == 'stock':
        raise ValueError("Injection scaler already at stock (100)")

    rom    = bytearray(data)
    fuel   = list(data[FUEL_MAP_ADDR:FUEL_MAP_ADDR + FUEL_MAP_SIZE])

    if halve:
        # scaler 100 → 50 : double the encoded lambda to maintain fuelling
        new_scaler = INJ_SCALER_HALF
        new_fuel   = []
        for raw in fuel:
            signed    = raw if raw < 128 else raw - 256
            lam       = signed * _LAMBDA_STEP + 1.0    # current lambda
            new_lam   = lam * 2.0                       # rescaled for ×0.5 scaler
            new_sig   = round((new_lam - 1.0) / _LAMBDA_STEP)
            new_fuel.append(new_sig & 0xFF)
    else:
        # scaler 50 → 100 : halve the encoded lambda
        new_scaler = INJ_SCALER_STOCK
        new_fuel   = []
        for raw in fuel:
            signed    = raw if raw < 128 else raw - 256
            lam       = signed * _LAMBDA_STEP + 1.0    # current encoded lambda
            # At scaler=50, delivered = lam × 0.5
            # To encode same delivery at scaler=100: new_lam = lam × 0.5
            new_lam   = lam * 0.5
            new_sig   = round((new_lam - 1.0) / _LAMBDA_STEP)
            new_fuel.append(new_sig & 0xFF)

    rom[INJ_SCALER_ADDR] = new_scaler
    for i, val in enumerate(new_fuel):
        rom[FUEL_MAP_ADDR + i] = val

    return bytes(rom)


# ---------------------------------------------------------------------------
# Pin 4 sensor definitions — freed ADC input
# ---------------------------------------------------------------------------
#
# When the CO pot patch is applied (or a no-CO-pot sensor is fitted),
# ECU pin 4 becomes a free 0–5V ADC input sampled every cycle.
# The following tables define the transfer functions for supported sensors.
#
# ADC encoding: 8-bit, 0V=0, 5V=255, resolution = 5/255 = 0.01961 V/count
#
# ROM correction table layout (when implemented):
#   Axis table  : 16 bytes — ADC breakpoints (evenly spaced 0–255)
#   Value table : 16 bytes — decoded values at each breakpoint
#   Total       : 32 bytes per 1D table
#   Best ROM location: 0x133E–0x17FF (1218 bytes free in 266D stock)
#
# Requirements to use pin 4 as a sensor input:
#   1. CO pot patch MUST be applied (gain=0, thresholds 0x00/0xFF)
#   2. Sensor fitted to MAF connector pin 4
#   3. For logging: Teensy analog input tapped on the same wire
#   4. For ROM correction: firmware patch required (future — not yet implemented)
# ---------------------------------------------------------------------------

# Standard 16-point ADC axis — evenly spaced, used by all sensor tables
PIN4_ADC_AXIS = [0, 17, 34, 51, 68, 85, 102, 119, 136, 153, 170, 187, 204, 221, 238, 255]

# ── Wideband O2 controllers ──────────────────────────────────────────────────
# Transfer function: linear 0–5V output
# Encoding: AFR * 10 stored as byte (e.g. 147 = 14.7 AFR)
# Range clipped to 0–255 (max storable AFR = 25.5)

PIN4_WIDEBAND_TABLES = {
    "innovate_lc2": {
        "label":       "Innovate LC-2 (gasoline)",
        "part":        "Innovate 3877",
        "afr_at_0v":   7.35,
        "afr_at_5v":   22.39,
        "stoich_adc":  124,   # 14.7 AFR @ 2.43V
        "stoich_v":    2.43,
        "afr_axis":    [7.4, 8.3, 9.4, 10.4, 11.4, 12.4, 13.4, 14.4,
                        15.4, 16.4, 17.4, 18.4, 19.4, 20.4, 21.4, 22.4],
        # Stored as AFR*10 truncated to byte
        "table_bytes": [74, 83, 94, 104, 114, 124, 134, 144,
                        154, 164, 174, 184, 194, 204, 214, 224],
        "notes":       "Linear 0-5V. Wire: WB controller analog out → pin 4. "
                       "Also tap to Teensy A-pin for logging.",
    },
    "aem_uego": {
        "label":       "AEM UEGO 30-0300 (gasoline)",
        "part":        "AEM 30-0300",
        "afr_at_0v":   8.50,
        "afr_at_5v":   18.00,
        "stoich_adc":  166,   # 14.7 AFR @ 3.25V
        "stoich_v":    3.25,
        "afr_axis":    [8.5, 9.1, 9.8, 10.4, 11.0, 11.7, 12.3, 12.9,
                        13.6, 14.2, 14.8, 15.5, 16.1, 16.7, 17.4, 18.0],
        "table_bytes": [85, 91, 98, 104, 110, 117, 123, 129,
                        136, 142, 148, 155, 161, 167, 174, 180],
        "notes":       "Linear 0-5V. Wire: WB controller analog out → pin 4.",
    },
    "zeitronix_zt3": {
        "label":       "Zeitronix ZT-3",
        "part":        "Zeitronix ZT-3",
        "afr_at_0v":   10.0,
        "afr_at_5v":   20.0,
        "stoich_adc":  119,   # 14.7 AFR @ 2.33V
        "stoich_v":    2.33,
        "afr_axis":    [10.0, 10.7, 11.3, 12.0, 12.7, 13.3, 14.0, 14.7,
                        15.3, 16.0, 16.7, 17.3, 18.0, 18.7, 19.3, 20.0],
        "table_bytes": [100, 107, 113, 120, 127, 133, 140, 147,
                        153, 160, 167, 173, 180, 187, 193, 200],
        "notes":       "Linear 0-5V. Wire: WB controller analog out → pin 4.",
    },
}

# ── MAP sensors ───────────────────────────────────────────────────────────────
# Transfer function: linear 0–5V absolute pressure output
# Encoding: kPa absolute stored as byte (1 byte = 1 kPa, range 0–255 kPa)

PIN4_MAP_TABLES = {
    "gm_1bar": {
        "label":       "GM 1-bar absolute (12569240)",
        "part":        "GM 12569240 / ACDelco 213-796",
        "kpa_at_0v":   10.0,
        "kpa_at_5v":   105.0,
        "range_bar":   1.0,
        "atm_adc":     245,   # 101.3 kPa @ 4.80V
        "boost_1bar":  None,  # exceeds sensor range
        "kpa_axis":    [10.0, 16.3, 22.7, 29.0, 35.3, 41.7, 48.0, 54.3,
                        60.7, 67.0, 73.3, 79.7, 86.0, 92.3, 98.7, 105.0],
        "table_bytes": [10, 16, 23, 29, 35, 42, 48, 54,
                        61, 67, 73, 80, 86, 92, 99, 105],
        "notes":       "NA only. Full-range vacuum to atmospheric. "
                       "Wire: MAP signal → pin 4, +5V supply, GND. "
                       "Vacuum port: tee into intake manifold.",
    },
    "gm_2bar": {
        "label":       "GM 2-bar absolute (16040749)",
        "part":        "GM 16040749 / ACDelco 213-4514",
        "kpa_at_0v":   10.0,
        "kpa_at_5v":   210.0,
        "range_bar":   2.0,
        "atm_adc":     116,   # 101.3 kPa @ 2.27V
        "boost_1bar":  243,   # 201.3 kPa @ 4.76V
        "kpa_axis":    [10.0, 23.3, 36.7, 50.0, 63.3, 76.7, 90.0, 103.3,
                        116.7, 130.0, 143.3, 156.7, 170.0, 183.3, 196.7, 210.0],
        "table_bytes": [10, 23, 37, 50, 63, 77, 90, 103,
                        117, 130, 143, 157, 170, 183, 197, 210],
        "notes":       "NA and mild boost to 1 bar. "
                       "Wire: MAP signal → pin 4, +5V supply, GND. "
                       "Vacuum port: tee into intake manifold.",
    },
    "gm_3bar": {
        "label":       "GM 3-bar absolute (12223861)",
        "part":        "GM 12223861 / ACDelco 213-2932",
        "kpa_at_0v":   10.0,
        "kpa_at_5v":   315.0,
        "range_bar":   3.0,
        "atm_adc":     76,    # 101.3 kPa @ 1.49V
        "boost_1bar":  159,   # 201.3 kPa @ 3.12V
        "kpa_axis":    [10.0, 30.3, 50.7, 71.0, 91.3, 111.7, 132.0, 152.3,
                        172.7, 193.0, 213.3, 233.7, 254.0, 274.3, 294.7, 315.0],
        "table_bytes": [10, 30, 51, 71, 91, 112, 132, 152,
                        173, 193, 213, 234, 254, 255, 255, 255],
        "notes":       "High-boost builds to 2 bar. "
                       "Wire: MAP signal → pin 4, +5V supply, GND.",
    },
    "bosch_2bar5": {
        "label":       "Bosch 2.5-bar (0261230036)",
        "part":        "Bosch 0261230036",
        "kpa_at_0v":   10.0,
        "kpa_at_5v":   250.0,
        "range_bar":   2.5,
        "atm_adc":     97,    # 101.3 kPa @ 1.90V
        "boost_1bar":  203,   # 201.3 kPa @ 3.98V
        "kpa_axis":    [10.0, 26.0, 42.0, 58.0, 74.0, 90.0, 106.0, 122.0,
                        138.0, 154.0, 170.0, 186.0, 202.0, 218.0, 234.0, 250.0],
        "table_bytes": [10, 26, 42, 58, 74, 90, 106, 122,
                        138, 154, 170, 186, 202, 218, 234, 250],
        "notes":       "Common VAG part. NA to 1.5 bar boost. "
                       "Wire: MAP signal → pin 4, +5V supply, GND.",
    },
}

# ── IAT NTC thermistor ────────────────────────────────────────────────────────
# Standard Bosch NTC B57861-S (same family as 7A coolant temp sensor)
# Circuit: 5V — 2.2kΩ — pin4 — NTC — GND
# Encoding: signed byte, 1 count = 1°C, offset 40 (byte 40 = 0°C, byte 80 = 40°C)

PIN4_IAT_TABLE = {
    "bosch_ntc": {
        "label":       "Bosch NTC IAT (B57861-S family)",
        "part":        "Bosch 0280130039 or equivalent",
        "pullup_ohm":  2200,
        "pullup_v":    5.0,
        # ADC values at each temperature breakpoint
        "temp_axis":   [-40, -30, -20, -10,  0,  10,  20,  30,
                          40,  50,  60,  70, 80,  90, 100, 110],
        "adc_axis":    [243, 235, 223, 207, 186, 161, 136, 111,
                          89,  70,  54,  42,  33,  25,  20,  16],
        # Stored as (temp + 40) so -40°C=0, 0°C=40, 100°C=140 — fits in byte
        "table_bytes": [  0,  10,  20,  30,  40,  50,  60,  70,
                          80,  90, 100, 110, 120, 130, 140, 150],
        "notes":       "Wire: 5V → 2.2kΩ resistor → pin 4 → NTC → GND. "
                       "Decoding: °C = table_value - 40. "
                       "Compatible with 1.8T 5-pin integrated IAT (pins 1+4).",
    },
}

# ── Sensor key → table lookup ─────────────────────────────────────────────────
PIN4_SENSOR_TABLES = {
    **{k: {"type": "wideband", **v} for k, v in PIN4_WIDEBAND_TABLES.items()},
    **{k: {"type": "map",      **v} for k, v in PIN4_MAP_TABLES.items()},
    "bosch_ntc": {"type": "iat", **PIN4_IAT_TABLE["bosch_ntc"]},
}

PIN4_ADC_AXIS_CONST = PIN4_ADC_AXIS   # alias for clarity in GUI code


# ---------------------------------------------------------------------------
# Pin 4 sensor table patch — writes linearisation tables into safe ROM space
# ---------------------------------------------------------------------------
#
# Sensor table block at 0x1E87–0x1FFF (377 bytes, confirmed safe in 266D):
#   0x1E87  [16]  Shared ADC axis (evenly spaced 0–255)
#   0x1E97  [16]  Active sensor value axis (AFR*10 / kPa / temp+40)
#   0x1EA7  [16]  Second sensor slot (optional, future use)
#   0x1EB7  [16]  Third sensor slot
#   0x1EC7  [1]   Sensor type: 0x00=none 0x01=wideband 0x02=map 0x03=iat 0xFF=raw
#   0x1EC8  [1]   Sensor subtype index (0=first entry in type dict)
#   0x1EC9–0x1FFF Reserved for future correction table
#
# Requirements:
#   1. CO pot patch MUST be applied first (gain=0, thresholds 0x00/0xFF)
#   2. Sensor wired to MAF connector pin 4
#   3. For ECU correction: firmware patch required (future — not yet implemented)
#   4. For Teensy logging: tap pin 4 physically, read table from ROM bus
#
# The Teensy can read the sensor type and table bytes directly from the emulated
# ROM image — it knows the sensor fitted without any extra wiring.
# ---------------------------------------------------------------------------

PIN4_TABLE_BASE        = 0x1E87
PIN4_ADC_AXIS_OFFSET   = 0x00   # 16 bytes — shared ADC axis
PIN4_VAL_AXIS_OFFSET   = 0x10   # 16 bytes — sensor value axis (primary slot)
PIN4_VAL2_AXIS_OFFSET  = 0x20   # 16 bytes — second slot (future)
PIN4_VAL3_AXIS_OFFSET  = 0x30   # 16 bytes — third slot (future)
PIN4_CONFIG_OFFSET     = 0x40   # 1 byte  — sensor type
PIN4_SUBTYPE_OFFSET    = 0x41   # 1 byte  — sensor subtype

PIN4_TYPE_NONE      = 0x00
PIN4_TYPE_WIDEBAND  = 0x01
PIN4_TYPE_MAP       = 0x02
PIN4_TYPE_IAT       = 0x03
PIN4_TYPE_RAW       = 0xFF

_PIN4_SUBTYPE_KEYS = {
    PIN4_TYPE_WIDEBAND: list(PIN4_WIDEBAND_TABLES.keys()),
    PIN4_TYPE_MAP:      list(PIN4_MAP_TABLES.keys()),
    PIN4_TYPE_IAT:      ["bosch_ntc"],
}


def detect_pin4_patch(data: bytes) -> dict:
    """
    Detect whether a pin 4 sensor table has been written to the ROM.

    Returns a dict:
      {
        'state':    'none' | 'patched' | 'unknown',
        'type':     PIN4_TYPE_* constant,
        'type_name': 'wideband' | 'map' | 'iat' | 'raw' | 'none',
        'subtype':  subtype key string or None,
        'label':    human-readable sensor label,
        'adc_axis': list[int] or None,
        'val_axis': list[int] or None,
      }
    """
    base = PIN4_TABLE_BASE
    if len(data) < base + PIN4_SUBTYPE_OFFSET + 1:
        return {'state': 'unknown', 'type': PIN4_TYPE_NONE,
                'type_name': 'unknown', 'subtype': None,
                'label': 'unknown', 'adc_axis': None, 'val_axis': None}

    sensor_type    = data[base + PIN4_CONFIG_OFFSET]
    sensor_subtype = data[base + PIN4_SUBTYPE_OFFSET]

    # Check if ADC axis has been written (not all 0xFF)
    adc_bytes = list(data[base + PIN4_ADC_AXIS_OFFSET:
                           base + PIN4_ADC_AXIS_OFFSET + 16])
    val_bytes = list(data[base + PIN4_VAL_AXIS_OFFSET:
                           base + PIN4_VAL_AXIS_OFFSET + 16])
    has_data  = not all(b == 0xFF for b in adc_bytes)

    if not has_data or sensor_type == PIN4_TYPE_NONE:
        return {'state': 'none', 'type': PIN4_TYPE_NONE,
                'type_name': 'none', 'subtype': None,
                'label': 'No sensor (pin 4 open)',
                'adc_axis': None, 'val_axis': None}

    type_names = {
        PIN4_TYPE_WIDEBAND: 'wideband',
        PIN4_TYPE_MAP:      'map',
        PIN4_TYPE_IAT:      'iat',
        PIN4_TYPE_RAW:      'raw',
    }
    type_name = type_names.get(sensor_type, 'unknown')

    # Resolve subtype label
    subtype_key = None
    label = type_name
    subtype_list = _PIN4_SUBTYPE_KEYS.get(sensor_type, [])
    if sensor_subtype < len(subtype_list):
        subtype_key = subtype_list[sensor_subtype]
        if sensor_type == PIN4_TYPE_WIDEBAND:
            label = PIN4_WIDEBAND_TABLES[subtype_key]['label']
        elif sensor_type == PIN4_TYPE_MAP:
            label = PIN4_MAP_TABLES[subtype_key]['label']
        elif sensor_type == PIN4_TYPE_IAT:
            label = PIN4_IAT_TABLE['bosch_ntc']['label']

    return {
        'state':     'patched',
        'type':      sensor_type,
        'type_name': type_name,
        'subtype':   subtype_key,
        'label':     label,
        'adc_axis':  adc_bytes if has_data else None,
        'val_axis':  val_bytes if has_data else None,
    }


def apply_pin4_patch(data: bytes, sensor_type: int, subtype_key: str = '') -> bytes:
    """
    Write a sensor linearisation table into the safe ROM block at 0x1E87.

    Parameters
    ----------
    data         : raw 32 768-byte 266D ROM (CO pot patch MUST already be applied)
    sensor_type  : PIN4_TYPE_* constant
    subtype_key  : key into the appropriate sensor table dict

    Returns new bytes with the table written.
    Raises ValueError if CO pot patch not applied, or bad arguments.
    """
    if len(data) < PIN4_TABLE_BASE + PIN4_SUBTYPE_OFFSET + 1:
        raise ValueError("ROM too short for pin 4 patch")

    # Require CO pot patch to be applied first
    if data[0x0779] != 0x00:
        raise ValueError(
            "CO pot patch must be applied before writing pin 4 sensor table. "
            "Apply CO pot patch first (Hardware tab → CO Pot).")

    rom = bytearray(data)
    base = PIN4_TABLE_BASE

    if sensor_type == PIN4_TYPE_NONE or sensor_type == PIN4_TYPE_RAW:
        # Clear the table back to 0xFF
        for i in range(0x42):
            rom[base + i] = 0xFF
        rom[base + PIN4_CONFIG_OFFSET] = (
            PIN4_TYPE_RAW if sensor_type == PIN4_TYPE_RAW else PIN4_TYPE_NONE)
        return bytes(rom)

    # Write shared ADC axis
    for i, v in enumerate(PIN4_ADC_AXIS):
        rom[base + PIN4_ADC_AXIS_OFFSET + i] = v

    # Write sensor value axis and config
    subtype_idx = 0
    if sensor_type == PIN4_TYPE_WIDEBAND:
        if subtype_key not in PIN4_WIDEBAND_TABLES:
            raise ValueError(f"Unknown wideband subtype: {subtype_key}")
        tbl = PIN4_WIDEBAND_TABLES[subtype_key]
        val_bytes = tbl['table_bytes']
        subtype_idx = list(PIN4_WIDEBAND_TABLES.keys()).index(subtype_key)

    elif sensor_type == PIN4_TYPE_MAP:
        if subtype_key not in PIN4_MAP_TABLES:
            raise ValueError(f"Unknown MAP sensor subtype: {subtype_key}")
        tbl = PIN4_MAP_TABLES[subtype_key]
        val_bytes = tbl['table_bytes']
        subtype_idx = list(PIN4_MAP_TABLES.keys()).index(subtype_key)

    elif sensor_type == PIN4_TYPE_IAT:
        tbl = PIN4_IAT_TABLE['bosch_ntc']
        val_bytes = tbl['table_bytes']
        subtype_idx = 0
    else:
        raise ValueError(f"Unknown sensor type: {sensor_type:#04x}")

    for i, v in enumerate(val_bytes):
        rom[base + PIN4_VAL_AXIS_OFFSET + i] = v

    rom[base + PIN4_CONFIG_OFFSET] = sensor_type
    rom[base + PIN4_SUBTYPE_OFFSET] = subtype_idx

    return bytes(rom)
