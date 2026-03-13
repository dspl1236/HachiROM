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
# MAF hardware patch tables — 266D and 266B only
# (AAH uses a MAP-sensor-derived load axis, not a MAF ADC axis)
#
# The 266D/266B fuel/timing maps are indexed by MAF ADC counts (0-255 = 0-5V).
# These tables are stored at TWO locations in the ROM:
#   0x05D0 — fuel map MAF axis   (16 bytes)
#   0x05E0 — timing map MAF axis (16 bytes, identical copy)
# Swapping the sensor housing requires rewriting both locations with the new
# sensor's transfer function in ADC counts so the ECU interpolates correctly.
#
# Airflow reference points (g/s) for each of the 16 axis breakpoints:
#   [0, 5, 15, 25, 45, 60, 80, 100, 140, 165, 190, 220, 280, 295, 300, 300]
#
# Profile grouping
# ────────────────
#   Group A — 7A Hitachi sensor (4-pin, CO pot integrated):
#     stock_7a          Original sensor in 50mm housing — stock, no changes
#     aah_v6_housing    7A sensor transplanted into 74mm AAH V6 housing
#                       (plug-and-play CO pot, ROM patch required)
#
#   Group B — Bosch 1.8T sensor (3-wire, no CO pot — external pot required):
#     sensor_1_8t_57    1.8T sensor in 57mm 1.8T housing
#     sensor_1_8t_vr6   1.8T sensor in 69.85mm VR6/TT225 housing
#
# CO pot — detailed wiring (source: 20v-sauger-tuning.de)
#   The stock 7A MAF (054 133 471 / A) is 4-pin:
#     Pin 1: MAF signal (0-5V to ECU)
#     Pin 2: Ground
#     Pin 3: +12V supply
#     Pin 4: CO pot signal
#
#   The ECU sends ~9V on pin 4.  The original CO pot (integrated into the
#   sensor head) divides this to 1.0–7.5V.  The ECU reads this voltage at
#   idle to trim the lambda target — it is only active at idle.
#   Fault code if missing: 00521 "CO-Poti Unterbrechung oder Kurzschluss"
#   Symptoms: poor idle, stumble off idle, fault code stored.
#   Normal driving is unaffected — CO pot is idle-only.
#
#   For 3-wire replacement sensors (no CO pot):
#     External pot wiring (from 20v-sauger-tuning.de page 2):
#       1 kΩ resistor from pot pin 1 → GND
#       Pot wiper (pin 2) → original pin 4 wire (to ECU)
#       20 kΩ 10-turn precision pot (Reichelt 534-20K or similar)
#     This covers the 1–7.5V range, no fault code, adjustable like original.
#
#   AAH V6 housing + 7A sensor transplant (plug-and-play option):
#     Move the 7A sensor unit (054 133 471 A) into the AAH housing (078 133 471).
#     This retains the 4-pin connector and CO pot — NO wiring changes at all.
#     Requires ROM patch for correct fuelling (see aah_v6_housing profile).
#     IMPORTANT housing compatibility:
#       Use 078 133 471 (no suffix) — mounting holes match 7A sensor unit.
#       078 133 471 A / AX have mirrored holes and different sensor depth — INCOMPATIBLE.
#       054 133 471 A  (with Index A) fits directly; without Index A needs shim washers.
# ---------------------------------------------------------------------------

MAF_AXIS_ADDR_FUEL   = 0x05D0   # fuel map MAF axis location in ROM
MAF_AXIS_ADDR_TIMING = 0x05E0   # timing map MAF axis location (identical copy)
MAF_AXIS_LEN         = 16       # 16 breakpoints

# Sensor / housing compatibility
# ─────────────────────────────
# Two sensor elements are supported:
#
#   7A Hitachi (054 133 471 / A)  — 4-pin, integrated CO pot
#     Fits: 50mm stock housing, 74mm AAH V6 housing (transplant mod)
#     Does NOT fit: 1.8T or VR6/TT225 housings (different internal geometry)
#
#   Bosch 1.8T (0280218114)       — 3-pin, no CO pot
#     Fits: 57mm 1.8T housing, 69.85mm VR6/TT225 housing
#     Does NOT fit: 50mm or 74mm VAG housings (different internal geometry)
#
# This gives exactly four valid hardware combinations:
#
#   stock_7a          7A sensor  + 50mm housing   — stock, CO pot retained
#   aah_v6_housing    7A sensor  + 74mm AAH housing — CO pot retained, ROM patch needed
#   sensor_1_8t_57    1.8T sensor + 57mm 1.8T housing  — 3-wire, external CO pot
#   sensor_1_8t_vr6   1.8T sensor + 69.85mm VR6 housing — 3-wire, external CO pot

# ── Group A — 7A Hitachi sensor ─────────────────────────────────────────────

# Stock axis — original Hitachi sensor in 50mm housing (054 133 471 / A)
# Confirmed from physical ROM read: 893906266D_MMS05C_physical.bin
# Housing bore: 50mm, bypass: 8mm, total flow area: 2013.76 mm²
# Sensor capacity: ~480 kg/h
MAF_AXIS_STOCK_7A   = [5, 10, 20, 30, 50, 62, 75, 87, 116, 131, 145, 160, 225, 243, 255, 255]

# 7A sensor transplanted into AAH 2.8L V6 housing (078 133 471 no-suffix)
# Source: 20v-sauger-tuning.de — measured housing dimensions:
#   Housing bore: 74mm, bypass: 10mm, rib: 19×74mm, total flow area: 2972.53 mm²
#   Velocity ratio at same airflow: 2013.76 / 2972.53 = 0.6775
#   King's law voltage correction: sqrt(0.6775) = 0.8231
# PLUG-AND-PLAY: 4-pin connector and CO pot are retained — no wiring changes.
# REQUIRES this ROM patch — ECU under-reads airflow without it and runs lean.
# DO NOT remove the centre rib from the AAH housing — destroys bypass ratio.
# IMPORTANT part number: use 078 133 471 (no suffix only).
#   078 133 471 A / AX — mirrored holes, different depth — INCOMPATIBLE.
#   054 133 471 A (with Index A) fits directly; without Index A needs shim washers.
MAF_AXIS_AAH_V6     = [4, 8, 16, 25, 41, 51, 62, 72, 95, 108, 119, 132, 185, 200, 255, 255]

# ── Group B — Bosch 1.8T sensor (0280218114) ────────────────────────────────
# 3-wire sensor — no integrated CO pot.
# Requires external pot wiring on ECU pin 4 (see CO pot note in header comment).

# 1.8T sensor in 57mm 1.8T housing
# Bore: 57mm, flow area: 2551.8 mm²
# Axis derived from published 1.8T transfer function data for this housing.
# Compared to VR6/TT225 housing: smaller bore → higher air velocity → higher voltage
#   Velocity ratio (57mm vs 69.85mm): 3832.0 / 2551.8 = 1.5017
#   King's law voltage scale: sqrt(1.5017) = 1.2254
# NOTE: verify against a wideband before road use.
MAF_AXIS_1_8T_57    = [5, 10, 20, 33, 56, 69, 85, 99, 131, 150, 168, 186, 246, 255, 255, 255]

# 1.8T sensor in VR6 / TT225 housing (69.85mm / 2.75")
# Bore: 69.85mm, flow area: 3832.0 mm²
# Same sensor element as above — larger housing bore → lower voltage at same airflow.
# Axis derived from published 1.8T / VR6 transfer function data.
# Housing: MK4 VR6 / Audi TT 225 — Bosch 0280218042 / 0280218116
# Suitable for K04 / hybrid turbo setups, ~250–300 hp.
# NOTE: verify against a wideband before road use.
MAF_AXIS_1_8T_VR6   = [4, 8, 16, 27, 46, 56, 69, 81, 107, 122, 137, 152, 201, 219, 242, 242]

# Human-readable sensor profiles — ordered by sensor then bore size
MAF_PROFILES: dict = {
    # ── Group A — 7A Hitachi sensor ───────────────────────────────────────
    "stock_7a":         {
        "label":        "Stock 7A  (50mm)",
        "group":        "7A Hitachi sensor",
        "axis":          MAF_AXIS_STOCK_7A,
        "housing":      "Hitachi 054 133 471 / A — 50mm bore",
        "hp_note":      "Stock — ~170 hp limit",
        "co_pot":        True,
        "plug_play":     True,
    },
    "aah_v6_housing":   {
        "label":        "AAH V6 housing + 7A sensor  (74mm)",
        "group":        "7A Hitachi sensor",
        "axis":          MAF_AXIS_AAH_V6,
        "housing":      "078 133 471 (no suffix) housing + 054 133 471 A sensor unit",
        "hp_note":      "NA / mild boost — CO pot retained, ROM patch required",
        "co_pot":        True,
        "plug_play":     True,
    },
    # ── Group B — Bosch 1.8T sensor ───────────────────────────────────────
    "sensor_1_8t_57":   {
        "label":        "1.8T sensor + 1.8T housing  (57mm)",
        "group":        "Bosch 1.8T sensor  (3-wire — external CO pot required)",
        "axis":          MAF_AXIS_1_8T_57,
        "housing":      "Stock 1.8T MAF housing — Bosch 0280218114",
        "hp_note":      "Mild–moderate power upgrade",
        "co_pot":        False,
        "plug_play":     False,
        "note":         "Axis derived from transfer function data — verify on dyno.",
    },
    "sensor_1_8t_vr6":  {
        "label":        "1.8T sensor + VR6/TT225 housing  (69.85mm)",
        "group":        "Bosch 1.8T sensor  (3-wire — external CO pot required)",
        "axis":          MAF_AXIS_1_8T_VR6,
        "housing":      "MK4 VR6 / Audi TT 225 housing — Bosch 0280218042 / 0280218116",
        "hp_note":      "~250–300 hp — K04 / hybrid turbo",
        "co_pot":        False,
        "plug_play":     False,
        "note":         "Axis derived from transfer function data — verify on dyno.",
    },
}


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

def timing_encode(deg) -> int:
    return int(deg) & 0xFF


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

    MapDef("RPM Limit",           0x07D2,  1,  1,
           "Rev limiter (fuel cut). raw×25=RPM. Stock=254 (6350 RPM). "
           "Raise with caution.", "RPM",
           decode=lambda v: v * 25,
           encode=lambda v: max(0, min(255, round(v / 25)))),
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

    MapDef("RPM Limit",           0x07D2,  1,  1,
           "Rev limiter (fuel cut). raw×25=RPM. Stock=254 (6350 RPM). "
           "Raise with caution.", "RPM",
           decode=lambda v: v * 25,
           encode=lambda v: max(0, min(255, round(v / 25)))),
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
    MapDef("RPM Limit",           0x07D2,  1,  1,
           "Rev limiter (fuel cut). raw×25=RPM. Stock=254 (6350 RPM). "
           "Raise with caution.", "RPM",
           decode=lambda v: v * 25,
           encode=lambda v: max(0, min(255, round(v / 25)))),

    # ── Fuel cut / decel ─────────────────────────────────────────────────────
    MapDef("Decel Cutoff",          0x0E30,  1, 16,
           "Decel fuel cut threshold per RPM. raw×0.3922=kPa.", "kPa"),
]

ROM_AAH = ROMVariant(
    name="AAH 12v", version_key="AAH", part_number="4A0906266",
    chip="27C512", size=32768,
    description="Audi 100 C4 2.8 12v (AAH)",
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

