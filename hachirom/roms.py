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
# ---------------------------------------------------------------------------

_MAPS_266D = [
    MapDef("Primary Fueling",    0x0000, 16, 16,
           "Fuel map (RPM×Load). signed(byte)+128, stock 40-123.", "fuel units",
           rpm_axis=RPM_AXIS_266D, load_axis=LOAD_AXIS,
           decode=fuel_266d_decode, encode=fuel_266d_encode),
    MapDef("Primary Timing",     0x0100, 16, 16,
           "Ignition advance. Raw byte, >128=retard.", "deg BTDC",
           rpm_axis=TIMING_RPM_AXIS, load_axis=LOAD_AXIS,
           decode=timing_decode, encode=timing_encode),
    MapDef("Timing Knock Safety",0x1000, 16, 16,
           "Knock fallback timing map.", "deg BTDC",
           rpm_axis=TIMING_RPM_AXIS, load_axis=LOAD_AXIS,
           decode=timing_decode, encode=timing_encode),
    MapDef("RPM Axis (Fuel)",    0x0250,  1, 16, "Fuel RPM axis. raw*25=RPM.", "RPM"),
    MapDef("Load Axis",          0x0260,  1, 16, "Load axis. raw*0.3922=kPa.", "kPa"),
    MapDef("RPM Axis (Timing)",  0x0270,  1, 16, "Timing RPM axis. raw*25=RPM.", "RPM"),
    MapDef("Load Axis (Timing)", 0x0280,  1, 16, "Timing load axis.", "kPa"),
    MapDef("CL Load Threshold",  0x0660,  1, 16, "CL disable load threshold per RPM.", "kPa"),
    MapDef("CL RPM Limit",       0x07E1,  1,  1, "Disable CL above RPM. raw*25=RPM.", "RPM"),
    MapDef("Decel Cutoff",       0x0E30,  1, 16, "Injector decel cutoff per RPM.", "kPa"),
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
# ---------------------------------------------------------------------------

_MAPS_266B = [
    MapDef("Fueling Map",       0x0000, 16, 16,
           "Fuel map (Lambda). signed(byte)*0.007813+1.0, stock 0.625-0.867.", "lambda",
           rpm_axis=RPM_AXIS_266B, load_axis=LOAD_AXIS,
           decode=fuel_lambda_decode, encode=fuel_lambda_encode),
    MapDef("Timing Map",        0x0100, 16, 16,
           "Ignition advance (deg BTDC).", "deg BTDC",
           rpm_axis=TIMING_RPM_AXIS, load_axis=LOAD_AXIS,
           decode=timing_decode, encode=timing_encode),
    MapDef("Timing Map Knock",  0x1000, 16, 16,
           "Knock fallback timing map.", "deg BTDC",
           rpm_axis=TIMING_RPM_AXIS, load_axis=LOAD_AXIS,
           decode=timing_decode, encode=timing_encode),
    MapDef("MAF Linearization", 0x02D0,  1, 64,
           "MAF linearization — 64x16-bit big-endian values.", "raw"),
    MapDef("Injection Scaler",  0x077E,  1,  1, "Global injector scaler.", "raw"),
    MapDef("CL Disable RPM",    0x07E1,  1,  1, "Disable CL above RPM.", "RPM"),
    MapDef("Decel Cutoff",      0x0E30,  1, 16, "Decel cutoff per RPM.", "kPa"),
    MapDef("CL Load Limit",     0x0660,  1, 16, "CL disable load limit per RPM.", "kPa"),
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
# ---------------------------------------------------------------------------

_MAPS_AAH = [
    MapDef("Fueling Map",       0x0000, 16, 16,
           "Fuel map (Lambda). signed(byte)*0.007813+1.0.", "lambda",
           rpm_axis=RPM_AXIS_AAH, load_axis=LOAD_AXIS_AAH,
           decode=fuel_lambda_decode, encode=fuel_lambda_encode),
    MapDef("Timing Map",        0x0100, 16, 16,
           "Ignition advance (deg BTDC).", "deg BTDC",
           rpm_axis=RPM_AXIS_AAH, load_axis=LOAD_AXIS_AAH,
           decode=timing_decode, encode=timing_encode),
    MapDef("Timing Map Knock",  0x1000, 16, 16,
           "Knock fallback timing map.", "deg BTDC",
           rpm_axis=RPM_AXIS_AAH, load_axis=LOAD_AXIS_AAH,
           decode=timing_decode, encode=timing_encode),
    MapDef("Injection Scaler",  0x077E,  1,  1, "Global injector scaler (stock=100).", "raw"),
    MapDef("CL Disable RPM",    0x07E1,  1,  1, "Disable CL above RPM.", "RPM"),
    MapDef("Decel Cutoff",      0x0E30,  1, 16, "Decel cutoff per RPM.", "kPa"),
]

ROM_AAH = ROMVariant(
    name="AAH 12v", version_key="AAH", part_number="4A0906266",
    chip="27C512", size=32768,
    description="Audi 100 / A6 / S4 / Coupe Quattro 2.8L V6 12v",
    maps=_MAPS_AAH,
    checksum=CHECKSUM_PARAMS["AAH"],
    known_crc32s=[0x13db1432, 0x4818fa0b, 0x6875638d],
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
}
