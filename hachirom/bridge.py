"""
hachirom.bridge
===============
Compatibility layer between HachiROM and the audi90-teensy-ecu tuner_app.

The Teensy project has a well-developed ecu_profiles.py. Rather than replace
it, this bridge lets tuner_app import shared constants and utilities from
HachiROM where it makes sense, avoiding duplication.

Usage in tuner_app (drop-in additions):
    from hachirom.bridge import (
        get_variant_for_version,
        read_fuel_map, read_timing_map,
        write_fuel_map, write_timing_map,
        verify_checksum, apply_checksum,
        compare_roms, diff_summary,
        load_bin, save_bin,
        unscramble_034,
    )

These functions accept the version strings used by ecu_profiles.py:
    "266D", "266B", "AAH"
"""

from .roms  import (ALL_VARIANTS, ROM_266D, ROM_266B, ROM_AAH,
                    ROMVariant, MapDef,
                    fuel_266d_decode, fuel_266d_encode,
                    fuel_lambda_decode, fuel_lambda_encode,
                    timing_decode, timing_encode,
                    unscramble_034,
                    RPM_AXIS_266D, RPM_AXIS_266B, TIMING_RPM_AXIS,
                    LOAD_AXIS, RPM_AXIS_AAH, LOAD_AXIS_AAH,
                    CHECKSUM_PARAMS)
from .maps  import (read_map, read_map_decoded, write_map, write_map_encoded,
                    read_axis, read_scalar, write_scalar,
                    compute_sum, verify_checksum, apply_checksum,
                    compare_roms, diff_summary, DiffByte)
from .detect import detect, load_bin, save_bin, DetectionResult

_VERSION_MAP = {
    "266D": ROM_266D,
    "266B": ROM_266B,
    "AAH":  ROM_AAH,
}


def get_variant(version: str) -> ROMVariant:
    """Return ROMVariant for a version string ("266D", "266B", "AAH")."""
    v = _VERSION_MAP.get(version)
    if v is None:
        raise ValueError(f"Unknown version: {version!r}. Use one of: {list(_VERSION_MAP)}")
    return v


def get_map(version: str, name: str) -> MapDef:
    """Look up a MapDef by version + partial name match."""
    variant = get_variant(version)
    name_lower = name.lower()
    for m in variant.maps:
        if name_lower in m.name.lower():
            return m
    raise KeyError(f"Map {name!r} not found in variant {version!r}")


def read_fuel_map(native_rom: bytes, version: str = "266D") -> list[list[int]]:
    """Read raw fuel map bytes as 2D list [row][col]."""
    return read_map(native_rom, get_map(version, "fuel") or get_map(version, "fueling"))


def read_timing_map(native_rom: bytes, version: str = "266D") -> list[list[int]]:
    """Read raw timing map bytes as 2D list [row][col]."""
    return read_map(native_rom, get_map(version, "primary timing"))


def read_fuel_map_decoded(native_rom: bytes, version: str = "266D") -> list[list]:
    """Read fuel map with display values applied."""
    m = get_map(version, "fuel") if version != "266D" else get_map(version, "fueling") if version != "266D" else get_map(version, "primary fueling")
    return read_map_decoded(native_rom, m)


def write_fuel_map(data: bytearray, values: list[list[int]], version: str = "266D") -> bytearray:
    """Write raw fuel map bytes back into ROM bytearray."""
    name = "primary fueling" if version == "266D" else "fueling"
    return write_map(data, get_map(version, name), values)


def write_timing_map(data: bytearray, values: list[list[int]], version: str = "266D") -> bytearray:
    """Write raw timing map bytes back into ROM bytearray."""
    name = "primary timing" if version == "266D" else "timing map"
    return write_map(data, get_map(version, name), values)


def set_cell(data: bytearray, map_type: str, row: int, col: int, value: int,
             version: str = "266D") -> bytearray:
    """
    Set a single cell in fuel or timing map — matches Teensy serial protocol.
    map_type: 'fuel' or 'timing'
    """
    name = ("primary fueling" if version == "266D" else "fueling map") \
           if map_type == "fuel" else \
           ("primary timing" if version == "266D" else "timing map")
    m = get_map(version, name)
    offset = m.address + row * m.cols + col
    if 0 <= offset < len(data):
        data[offset] = max(0, min(255, value))
    return data


def get_flat_fuel_map(native_rom: bytes, version: str = "266D") -> list[int]:
    """Return fuel map as flat 256-byte list (matches Teensy MAP:FUEL, protocol)."""
    rows = read_fuel_map(native_rom, version)
    return [v for row in rows for v in row]


def get_flat_timing_map(native_rom: bytes, version: str = "266D") -> list[int]:
    """Return timing map as flat 256-byte list (matches Teensy MAP:TIMING, protocol)."""
    rows = read_timing_map(native_rom, version)
    return [v for row in rows for v in row]


__all__ = [
    "get_variant", "get_map",
    "read_fuel_map", "read_timing_map",
    "read_fuel_map_decoded",
    "write_fuel_map", "write_timing_map",
    "set_cell",
    "get_flat_fuel_map", "get_flat_timing_map",
    "verify_checksum", "apply_checksum", "compute_sum",
    "compare_roms", "diff_summary", "DiffByte",
    "load_bin", "save_bin",
    "detect", "DetectionResult",
    "unscramble_034",
    # Axis data
    "RPM_AXIS_266D", "RPM_AXIS_266B", "TIMING_RPM_AXIS",
    "LOAD_AXIS", "RPM_AXIS_AAH", "LOAD_AXIS_AAH",
    # Formulas
    "fuel_266d_decode", "fuel_266d_encode",
    "fuel_lambda_decode", "fuel_lambda_encode",
    "timing_decode", "timing_encode",
    # Variants
    "ROM_266D", "ROM_266B", "ROM_AAH", "ALL_VARIANTS",
]
