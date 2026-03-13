"""
HachiROM — Known ROM definitions and detection logic.
Source of truth for all supported Hitachi ECU variants.
"""

from dataclasses import dataclass, field
from typing import Optional
import hashlib

# ---------------------------------------------------------------------------
# Map descriptor
# ---------------------------------------------------------------------------

@dataclass
class MapDef:
    name: str
    address: int
    rows: int
    cols: int
    description: str = ""
    unit: str = ""
    # optional decode lambda: raw_byte -> human value
    decode: Optional[callable] = field(default=None, repr=False)
    encode: Optional[callable] = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# ECU / ROM variant descriptors
# ---------------------------------------------------------------------------

@dataclass
class ROMVariant:
    name: str                  # e.g. "7A Late (893906266D)"
    part_number: str           # e.g. "893906266D"
    chip: str                  # e.g. "27C512"
    size: int                  # bytes — 65536 for 27C512
    description: str
    maps: list                 # list[MapDef]
    # Known SHA256 hashes of stock ROMs (may be empty list)
    known_hashes: list = field(default_factory=list)
    # Offset of a known signature byte pattern used for detection
    signature: Optional[bytes] = field(default=None, repr=False)
    signature_offset: Optional[int] = None


# ---------------------------------------------------------------------------
# Decode helpers
# ---------------------------------------------------------------------------

def _ign_decode(v: int) -> float:
    """Digifant ignition byte → degrees BTDC"""
    return round((210 - v) / 2.86, 2)

def _ign_encode(deg: float) -> int:
    return max(0, min(255, round(210 - deg * 2.86)))

def _rpm_decode(hi: int, lo: int) -> int:
    """16-bit big-endian word → RPM  (30,000,000 / word)"""
    word = (hi << 8) | lo
    return int(30_000_000 / word) if word else 0

def _rpm_scalar_decode(hi: int, lo: int) -> int:
    """16-bit big-endian word → RPM axis  (15,000,000 / word)"""
    word = (hi << 8) | lo
    return int(15_000_000 / word) if word else 0


# ---------------------------------------------------------------------------
# 7A / NF  —  Late ECU  893906266D  (27C512, 64 KB)
# This is the primary target: 1990 Audi 90 / Coupe Quattro 2.3 20v
# Map offsets derived from 034 Motorsport XDF + community decompilation
# ---------------------------------------------------------------------------

_7A_LATE_MAPS = [
    MapDef("Ignition",          0x2800, 16, 16,
           "Main ignition advance table",
           "°BTDC",
           decode=lambda v: _ign_decode(v),
           encode=lambda v: _ign_encode(v)),

    MapDef("Fuel",              0x2900, 16, 16,
           "Main fuel / injection duration table",
           "raw"),

    MapDef("RPM Scalar",        0x2A00, 1,  16,
           "RPM axis values for ignition/fuel tables (16-bit words)",
           "RPM"),

    MapDef("Warmup Enrichment", 0x2B00, 1,  17,
           "Cold start warmup enrichment vs ECT",
           "%"),

    MapDef("IAT Compensation",  0x2B20, 1,  17,
           "Intake air temperature fuel compensation",
           "%"),

    MapDef("ECT Compensation",  0x2B40, 1,  17,
           "Engine coolant temperature fuel compensation",
           "%"),

    MapDef("Knock Retard",      0x2C00, 1,  16,
           "Per-cell knock retard values",
           "°"),

    MapDef("Coil Dwell",        0x2C20, 1,  16,
           "Coil dwell time vs RPM",
           "ms"),

    MapDef("WOT Enrichment",    0x2D00, 1,  17,
           "Wide open throttle enrichment",
           "%"),

    MapDef("Idle Speed",        0x2D40, 1,  16,
           "ISV / idle speed control table",
           "raw"),

    MapDef("Rev Limit",         0x3FF0, 1,   2,
           "Rev limiter (16-bit big-endian word: 30,000,000 / RPM)",
           "RPM"),

    MapDef("Accel Enrichment",  0x2E00, 1,  16,
           "Acceleration enrichment (transient fueling)",
           "raw"),
]

_7A_LATE_PATCHES = {
    # name: (address, stock_bytes, patched_bytes, description)
    "Open Loop Lambda": (0x3C00, bytes([0xBD, 0x6D, 0x07]), bytes([0x01, 0x01, 0x01]),
                         "Disables closed-loop lambda correction"),
    "ISV Disable":      (0x3D00, bytes([0xBD, 0x66, 0x0C]), bytes([0x01, 0x01, 0x01]),
                         "Disables idle speed valve control"),
}

ROM_7A_LATE = ROMVariant(
    name="7A Late",
    part_number="893906266D",
    chip="27C512",
    size=65536,
    description="Audi 90 / Coupe Quattro 2.3 20v NF/7A — late 4-connector ECU",
    maps=_7A_LATE_MAPS,
    known_hashes=[],       # populate with verified SHA256 of stock dump
    signature=None,        # TODO: add once stock ROM is confirmed
)


# ---------------------------------------------------------------------------
# 7A Early  —  893906266B  (27C512, 64 KB)
# Earlier 2-connector variant — slightly different map offsets
# ---------------------------------------------------------------------------

_7A_EARLY_MAPS = [
    MapDef("Ignition",          0x2600, 16, 16, "Main ignition advance", "°BTDC",
           decode=lambda v: _ign_decode(v), encode=lambda v: _ign_encode(v)),
    MapDef("Fuel",              0x2700, 16, 16, "Main fuel table", "raw"),
    MapDef("RPM Scalar",        0x2800, 1,  16, "RPM axis", "RPM"),
    MapDef("Warmup Enrichment", 0x2900, 1,  17, "Warmup enrichment", "%"),
    MapDef("Rev Limit",         0x3DE0, 1,   2, "Rev limiter", "RPM"),
]

ROM_7A_EARLY = ROMVariant(
    name="7A Early",
    part_number="893906266B",
    chip="27C512",
    size=65536,
    description="Audi 90 / Coupe Quattro 2.3 20v NF/7A — early 2-connector ECU",
    maps=_7A_EARLY_MAPS,
    known_hashes=[],
)


# ---------------------------------------------------------------------------
# AAH  —  4A0906266  (27C512, 64 KB)
# Audi 100 / A6 / S4 2.8L V6 12v
# ---------------------------------------------------------------------------

_AAH_MAPS = [
    MapDef("Ignition",          0x3000, 16, 16, "Main ignition advance", "°BTDC",
           decode=lambda v: _ign_decode(v), encode=lambda v: _ign_encode(v)),
    MapDef("Fuel",              0x3100, 16, 16, "Main fuel table", "raw"),
    MapDef("RPM Scalar",        0x3200, 1,  16, "RPM axis", "RPM"),
    MapDef("Warmup Enrichment", 0x3300, 1,  17, "Warmup enrichment", "%"),
    MapDef("IAT Compensation",  0x3320, 1,  17, "IAT compensation", "%"),
    MapDef("ECT Compensation",  0x3340, 1,  17, "ECT compensation", "%"),
    MapDef("Rev Limit",         0x4FF0, 1,   2, "Rev limiter", "RPM"),
]

ROM_AAH = ROMVariant(
    name="AAH 12v",
    part_number="4A0906266",
    chip="27C512",
    size=65536,
    description="Audi 100 / A6 / S4 2.8L V6 12v",
    maps=_AAH_MAPS,
    known_hashes=[],
)


# ---------------------------------------------------------------------------
# Registry — all known variants
# ---------------------------------------------------------------------------

ALL_VARIANTS: list[ROMVariant] = [
    ROM_7A_LATE,
    ROM_7A_EARLY,
    ROM_AAH,
]
