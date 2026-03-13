"""
HachiROM — ROM variant definitions and map address tables.
Source of truth for all supported Hitachi ECU variants.

Map addresses and formulas confirmed from:
  - 034 Motorsport .ecu definition files (7A_Late_Generic_1.01.ecu,
    7A_Early_Generic_1.06.ecu, AAH_12v_V6_Generic_1_02.ecu)
  - Java decompilation of ECUGUI.jar / CustomizedStore.jar
  - Decoded stock ROM verification (audi90-teensy-ecu/tuner_app/ecu_profiles.py)

.034 FILE FORMAT
================
All .034 files are bit-scrambled. Apply unscramble_034() to recover
native ROM bytes before reading any addresses below.
"""

from dataclasses import dataclass, field
from typing import Optional, Callable
import zlib


# ---------------------------------------------------------------------------
# .034 unscramble
# ---------------------------------------------------------------------------

def _alg_zero(b: int) -> int:
    return (((b & 0xAA) >> 1) | (((b & 0x55) << 1) & 0xFF)) & 0xFF

def _b_swap(x: int) -> int:
    return ((x >> 4) | ((x << 4) & 0xFF)) & 0xFF

def unscramble_byte(b: int) -> int:
    return _b_swap(_alg_zero(b))

def unscramble_034(data: bytes) -> bytes:
    """Unscramble a .034 file to native ECU ROM bytes."""
    return bytes(unscramble_byte(b) for b in data)


# ---------------------------------------------------------------------------
# Axis constants (confirmed from decoded stock ROMs)
# ---------------------------------------------------------------------------

AXIS_FACTOR_RPM  = 25.0
AXIS_FACTOR_LOAD = 0.3922

RPM_AXIS_266D   = [600,800,1000,1250,1500,1750,2000,2250,2500,2750,3000,3500,4000,5000,6000,6300]
RPM_AXIS_266B   = [600,800,1000,1250,1500,2000,2500,2750,3000,3500,4000,4500,5000,5500,6000,6375]
TIMING_RPM_AXIS = [700,750,1000,1250,1500,1750,2000,3000,3500,4000,4400,4600,5000,5500,6000,6300]
LOAD_AXIS       = [12.6,18.8,23.5,28.2,32.9,38.8,44.7,50.6,56.9,63.1,69.4,75.7,82.0,88.2,94.5,100.0]
RPM_AXIS_AAH    = [500,750,1000,1250,1500,1750,2000,2300,2600,3000,3500,4000,4500,5000,5500,6000]
LOAD_AXIS_AAH   = [12.6,18.8,23.5,28.2,32.9,38.4,43.9,50.2,56.5,62.8,69.0,75.3,81.6,87.9,94.1,100.0]


# ---------------------------------------------------------------------------
# Display formula helpers
# ---------------------------------------------------------------------------

def fuel_266d_decode(v: int) -> float:
    signed = v if v < 128 else v - 256
    return float(signed + 128)

def fuel_266d_encode(display: float) -> int:
    return max(0, min(255, round(display - 128))) & 0xFF

def fuel_lambda_decode(v: int) -> float:
    signed = v if v < 128 else v - 256
    return round(signed * 0.007813 + 1.0, 3)

def fuel_lambda_encode(lam: float) -> int:
    return max(0, min(255, round((lam - 1.0) / 0.007813))) & 0xFF

def timing_decode(v: int) -> int:
    return v if v < 128 else v - 256

def timing_encode(deg: int) -> int:
    return deg & 0xFF


# ---------------------------------------------------------------------------
# Checksum parameters
# ---------------------------------------------------------------------------

CHECKSUM_PARAMS = {
    "266D": {"target": 3_384_576, "cs_from": 0x1600, "cs_to": 0x17FF},
    "266B": {"target": 3_894_528, "cs_from": 0x1400, "cs_to": 0x1FFF},
    "AAH":  {"target": 3_684_096, "cs_from": 0x6700, "cs_to": 0x7D1E},
}


# ---------------------------------------------------------------------------
# MapDef
# ---------------------------------------------------------------------------

@dataclass
class MapDef:
    name:       str
    address:    int
    rows:       int
    cols:       int
    description: str = ""
    unit:       str = ""
    rpm_axis:   list = field(default_factory=list)
    load_axis:  list = field(default_factory=list)
    decode:     Optional[Callable] = field(default=None, repr=False)
    encode:     Optional[Callable] = field(default=None, repr=False)

    @property
    def size(self) -> int:
        return self.rows * self.cols

    @property
    def is_2d(self) -> bool:
        return self.rows > 1 and self.cols > 1

    @property
    def is_scalar(self) -> bool:
        return self.rows == 1 and self.cols == 1


# ---------------------------------------------------------------------------
# ROMVariant
# ---------------------------------------------------------------------------

@dataclass
class ROMVariant:
    name:             str
    version_key:      str
    part_number:      str
    chip:             str
    size:             int
    description:      str
    maps:             list
    checksum:         dict = field(default_factory=dict)
    known_crc32s:     list = field(default_factory=list)
    reset_vector:     Optional[bytes] = None
    signature:        Optional[bytes] = field(default=None, repr=False)
    signature_offset: Optional[int] = None


# ---------------------------------------------------------------------------
# 266D — Late 7A ECU
# Confirmed from: 034 Motorsport decompile, address gap analysis, 266B comparison
# ---------------------------------------------------------------------------

_MAPS_266D = [
    # ── Primary tuning maps ──────────────────────────────────────────────────
    MapDef("Primary Fueling",       0x0000, 16, 16,
           "Fuel map (RPM×Load). signed(byte)+128, stock 40-123.", "fuel units",
           rpm_axis=RPM_AXIS_266D, load_axis=LOAD_AXIS,
           decode=fuel_266d_decode, encode=fuel_266d_encode),
    MapDef("Primary Timing",        0x0100, 16, 16,
           "Ignition advance. Raw byte >128 = retard (2s complement).", "deg BTDC",
           rpm_axis=TIMING_RPM_AXIS, load_axis=LOAD_AXIS,
           decode=timing_decode, encode=timing_encode),
    MapDef("Timing Knock Safety",   0x1000, 16, 16,
           "Fallback timing map under knock. Same axes as primary timing.", "deg BTDC",
           rpm_axis=TIMING_RPM_AXIS, load_axis=LOAD_AXIS,
           decode=timing_decode, encode=timing_encode),

    # ── Axis tables ──────────────────────────────────────────────────────────
    MapDef("RPM Axis (Fuel)",       0x0250,  1, 16, "Fuel map RPM breakpoints. raw×25=RPM.", "RPM"),
    MapDef("Load Axis (Fuel)",      0x0260,  1, 16, "Fuel map load breakpoints. raw×0.3922=kPa.", "kPa"),
    MapDef("RPM Axis (Timing)",     0x0270,  1, 16, "Timing map RPM breakpoints. raw×25=RPM.", "RPM"),
    MapDef("Load Axis (Timing)",    0x0280,  1, 16, "Timing map load breakpoints. raw×0.3922=kPa.", "kPa"),

    # ── Warmup / cold start ──────────────────────────────────────────────────
    MapDef("After-start Enrichment",0x0220,  1, 16,
           "Cold-start fuel enrichment taper. Decreases as engine warms. "
           "Coolant-temp indexed (same axis as idle target).", "fuel units"),
    MapDef("Idle Speed Target",     0x0290,  1, 16,
           "Target idle RPM vs coolant temp. raw×25=RPM. "
           "Cold: ~2000RPM, warm: ~800RPM.", "RPM"),
    MapDef("Idle Ignition Trim",    0x02A0,  1, 16,
           "Timing correction at idle vs coolant temp. Signed byte (deg). "
           "Advances when warm, retards cold to aid warm-up.", "deg"),

    # ── Accel enrichment ─────────────────────────────────────────────────────
    MapDef("Accel Enrichment",      0x0400,  1, 16,
           "TPS accel enrichment pulse vs RPM. Decreases at high RPM. "
           "Shared RPM axis with fuel map.", "fuel units"),
    MapDef("Accel Decay",           0x0430,  1, 16,
           "Accel enrichment decay rate vs RPM. Exponential taper 100→2. "
           "Higher = faster decay.", "raw"),

    # ── Closed loop / O2 ────────────────────────────────────────────────────
    MapDef("CL Load Threshold",     0x0660,  1, 16,
           "Load above which closed loop is disabled, per RPM. raw×0.3922=kPa.", "kPa"),
    MapDef("CL RPM Limit",          0x07E1,  1,  1,
           "Disable closed loop above this RPM. raw×25=RPM.", "RPM"),

    # ── Fuel cut / decel ────────────────────────────────────────────────────
    MapDef("Decel Cutoff",          0x0E30,  1, 16,
           "Injector decel fuel cut threshold per RPM. raw×0.3922=kPa.", "kPa"),
]

ROM_266D = ROMVariant(
    name="7A Late", version_key="266D", part_number="893906266D",
    chip="27C512", size=32768,
    description="Audi 90 / Coupe Quattro 2.3 20v NF/7A — late 4-connector ECU",
    maps=_MAPS_266D,
    checksum=CHECKSUM_PARAMS["266D"],
    known_crc32s=[0x609f1f40, 0x4152e167],
    reset_vector=bytes([0xE8, 0xB1]),
)


# ---------------------------------------------------------------------------
# 266B — Early 7A ECU
# Same map layout as 266D except: lambda fuel formula, MAF linearisation,
# no injection scaler at 0x077E (different connector, different hardware)
# ---------------------------------------------------------------------------

_MAPS_266B = [
    # ── Primary tuning maps ──────────────────────────────────────────────────
    MapDef("Primary Fueling",       0x0000, 16, 16,
           "Fuel map (Lambda). signed(byte)×0.007813+1.0, stock 0.625-0.867.", "lambda",
           rpm_axis=RPM_AXIS_266B, load_axis=LOAD_AXIS,
           decode=fuel_lambda_decode, encode=fuel_lambda_encode),
    MapDef("Primary Timing",        0x0100, 16, 16,
           "Ignition advance (deg BTDC). Raw byte >128 = retard.", "deg BTDC",
           rpm_axis=TIMING_RPM_AXIS, load_axis=LOAD_AXIS,
           decode=timing_decode, encode=timing_encode),
    MapDef("Timing Knock Safety",   0x1000, 16, 16,
           "Fallback timing map under knock.", "deg BTDC",
           rpm_axis=TIMING_RPM_AXIS, load_axis=LOAD_AXIS,
           decode=timing_decode, encode=timing_encode),

    # ── Axis tables ──────────────────────────────────────────────────────────
    MapDef("RPM Axis (Fuel)",       0x0250,  1, 16, "Fuel map RPM breakpoints. raw×25=RPM.", "RPM"),
    MapDef("Load Axis (Fuel)",      0x0260,  1, 16, "Fuel map load breakpoints. raw×0.3922=kPa.", "kPa"),
    MapDef("RPM Axis (Timing)",     0x0270,  1, 16, "Timing map RPM breakpoints. raw×25=RPM.", "RPM"),
    MapDef("Load Axis (Timing)",    0x0280,  1, 16, "Timing map load breakpoints. raw×0.3922=kPa.", "kPa"),

    # ── Warmup / cold start ──────────────────────────────────────────────────
    MapDef("After-start Enrichment",0x0220,  1, 16,
           "Cold-start enrichment taper vs coolant temp. Decoded as lambda offset.", "lambda"),
    MapDef("Idle Speed Target",     0x0290,  1, 16,
           "Target idle RPM vs coolant temp. raw×25=RPM.", "RPM"),
    MapDef("Idle Ignition Trim",    0x02A0,  1, 16,
           "Idle timing correction vs coolant temp. Signed byte (deg).", "deg"),

    # ── MAF (266B only — 266D uses MAP sensor only) ──────────────────────────
    MapDef("MAF Linearization",     0x02D0,  1, 64,
           "MAF sensor linearisation table. 64×16-bit big-endian values. "
           "266B only — not present on 266D (MAP-only).", "raw"),

    # ── Accel enrichment ─────────────────────────────────────────────────────
    MapDef("Accel Enrichment",      0x0400,  1, 16,
           "TPS accel enrichment pulse vs RPM.", "lambda"),
    MapDef("Accel Decay",           0x0430,  1, 16,
           "Accel enrichment decay rate vs RPM. Higher = faster.", "raw"),

    # ── Closed loop / O2 ─────────────────────────────────────────────────────
    MapDef("CL Load Threshold",     0x0660,  1, 16,
           "Load above which closed loop disabled, per RPM. raw×0.3922=kPa.", "kPa"),
    MapDef("Injection Scaler",      0x077E,  1,  1, "Global injector scaler.", "raw"),
    MapDef("CL RPM Limit",          0x07E1,  1,  1, "Disable CL above this RPM. raw×25=RPM.", "RPM"),

    # ── Fuel cut / decel ─────────────────────────────────────────────────────
    MapDef("Decel Cutoff",          0x0E30,  1, 16,
           "Decel fuel cut threshold per RPM. raw×0.3922=kPa.", "kPa"),
]

ROM_266B = ROMVariant(
    name="7A Early", version_key="266B", part_number="893906266B",
    chip="27C512", size=32768,
    description="Audi 90 / Coupe Quattro 2.3 20v NF/7A — early 2-connector ECU",
    maps=_MAPS_266B,
    checksum=CHECKSUM_PARAMS["266B"],
    known_crc32s=[0x7739bde5],
    reset_vector=bytes([0xD7, 0xBC]),
)


# ---------------------------------------------------------------------------
# AAH — 2.8L V6 12v
# Extra maps confirmed from ROM hex analysis of AAH_MMS100_4A0906266 stock ROM.
# Notes:
#   0x0670-0x06CF: lambda-decoded values 1.0-1.5 — likely OL enrichment
#                  correction or per-bank injection timing. NOT a standard CL
#                  lambda target (those would cluster near 1.0). Marked
#                  uncertain — do not tune without further verification.
#   0x1001-0x10FF: structured 0-32 value table after knock map — possibly
#                  per-bank knock threshold (V6 has 2 knock sensors / 2 banks).
#                  Marked read-only until confirmed.
# ---------------------------------------------------------------------------

_MAPS_AAH = [
    # ── Primary tuning maps ──────────────────────────────────────────────────
    MapDef("Primary Fueling",       0x0000, 16, 16,
           "Fuel map (Lambda). signed(byte)×0.007813+1.0.", "lambda",
           rpm_axis=RPM_AXIS_AAH, load_axis=LOAD_AXIS_AAH,
           decode=fuel_lambda_decode, encode=fuel_lambda_encode),
    MapDef("Primary Timing",        0x0100, 16, 16,
           "Ignition advance (deg BTDC). Raw byte >128 = retard.", "deg BTDC",
           rpm_axis=RPM_AXIS_AAH, load_axis=LOAD_AXIS_AAH,
           decode=timing_decode, encode=timing_encode),
    MapDef("Timing Knock Safety",   0x1000, 16, 16,
           "Knock fallback timing map.", "deg BTDC",
           rpm_axis=RPM_AXIS_AAH, load_axis=LOAD_AXIS_AAH,
           decode=timing_decode, encode=timing_encode),

    # ── Axis tables (confirmed from ROM data — match RPM_AXIS_AAH exactly) ───
    MapDef("RPM Axis (Fuel)",       0x0250,  1, 16,
           "Fuel map RPM breakpoints. raw×25=RPM.", "RPM"),
    MapDef("Load Axis (Fuel)",      0x0260,  1, 16,
           "Fuel map load breakpoints. raw×0.3922=kPa.", "kPa"),
    MapDef("RPM Axis (Timing)",     0x0270,  1, 16,
           "Timing map RPM breakpoints. raw×25=RPM. Starts at 600 (not 500).", "RPM"),
    MapDef("Load Axis (Timing)",    0x0280,  1, 16,
           "Timing map load breakpoints. raw×0.3922=kPa.", "kPa"),

    # ── Warmup / cold start (confirmed from ROM hex analysis) ────────────────
    MapDef("After-start Enrichment",0x0220,  1, 16,
           "Cold-start enrichment taper. Decoded: 64→32 = lambda 1.5→1.25. "
           "Coolant-temp indexed. Reduces as engine warms.", "lambda",
           decode=fuel_lambda_decode, encode=fuel_lambda_encode),
    MapDef("Idle Speed Target",     0x0290,  1, 16,
           "Target idle RPM vs coolant temp. raw×25=RPM. "
           "Stock: cold=2000RPM, warm=800RPM.", "RPM"),
    MapDef("Idle Ignition Trim",    0x02A0,  1, 16,
           "Idle timing trim vs coolant temp. Signed byte (deg BTDC). "
           "Stock: +7→-9deg (advances warm, retards cold).", "deg",
           decode=timing_decode, encode=timing_encode),

    # ── Accel enrichment (confirmed from ROM hex analysis) ───────────────────
    MapDef("Accel Enrichment",      0x0400,  1, 16,
           "TPS accel enrichment pulse vs RPM. Stock: 104→48 (less at high RPM). "
           "Shared RPM axis with fuel map.", "raw"),
    MapDef("Accel Decay",           0x0430,  1, 16,
           "Accel enrichment decay rate vs RPM. Stock: 100→2 (exponential). "
           "Higher value = faster decay.", "raw"),

    # ── Scalars ──────────────────────────────────────────────────────────────
    MapDef("Injection Scaler",      0x077E,  1,  1,
           "Global injector scaler. Stock=100. Raise for larger injectors.", "raw"),
    MapDef("CL Disable RPM",        0x07E1,  1,  1,
           "Disable closed loop above this RPM. raw×25=RPM.", "RPM"),

    # ── Fuel cut / decel ─────────────────────────────────────────────────────
    MapDef("Decel Cutoff",          0x0E30,  1, 16,
           "Decel fuel cut threshold per RPM. raw×0.3922=kPa.", "kPa"),
]

ROM_AAH = ROMVariant(
    name="AAH 12v", version_key="AAH", part_number="4A0906266",
    chip="27C512", size=32768,
    description="Audi 100 / A6 / S4 / Coupe Quattro 2.8L V6 12v",
    maps=_MAPS_AAH,
    checksum=CHECKSUM_PARAMS["AAH"],
    known_crc32s=[0x13db1432, 0x4818fa0b, 0x6875638d],
    reset_vector=bytes([0xEF, 0x18]),
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

ALL_VARIANTS: list[ROMVariant] = [ROM_266D, ROM_266B, ROM_AAH]

_CRC32_MAP: dict[int, ROMVariant] = {}
for _v in ALL_VARIANTS:
    for _c in _v.known_crc32s:
        _CRC32_MAP[_c] = _v

_RESET_VEC_MAP: dict[tuple, ROMVariant] = {
    (0xE8, 0xB1): ROM_266D,
    (0xD7, 0xBC): ROM_266B,
    (0xEF, 0x18): ROM_AAH,
}

