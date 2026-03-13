"""
HachiROM
========
Source-of-truth ROM library for Hitachi ECU variants (7A 20v, AAH 12v).
Also serves as the map definition backend for audi90-teensy-ecu.

Quick start
-----------
    import hachirom as hr

    data   = hr.load_bin("my_rom.bin")       # .bin or .034 files accepted
    result = hr.detect(data)
    print(result.variant.name)               # "7A Late"

    fuel = hr.read_map(data, result.variant.maps[0])

Teensy bridge
-------------
    from hachirom.bridge import (
        get_flat_fuel_map, get_flat_timing_map,
        set_cell, apply_checksum, compare_roms
    )
"""

from .detect import detect, load_bin, save_bin, load_bin_normalised, DetectionResult
from .maps   import (read_map, read_map_decoded, write_map, write_map_encoded,
                     read_axis, read_scalar, write_scalar,
                     compute_sum, verify_checksum, apply_checksum,
                     compare_roms, diff_summary, DiffByte)
from .roms   import (ROMVariant, MapDef, ALL_VARIANTS,
                     ROM_266D, ROM_266B, ROM_AAH,
                     unscramble_034, unscramble_byte,
                     fuel_266d_decode, fuel_266d_encode,
                     fuel_lambda_decode, fuel_lambda_encode,
                     timing_decode, timing_encode,
                     RPM_AXIS_266D, RPM_AXIS_266B, TIMING_RPM_AXIS,
                     LOAD_AXIS, RPM_AXIS_AAH, LOAD_AXIS_AAH,
                     CHECKSUM_PARAMS)

__version__ = "0.2.0"

__all__ = [
    "detect", "load_bin", "save_bin", "load_bin_normalised", "DetectionResult",
    "read_map", "read_map_decoded", "write_map", "write_map_encoded",
    "read_axis", "read_scalar", "write_scalar",
    "compute_sum", "verify_checksum", "apply_checksum",
    "compare_roms", "diff_summary", "DiffByte",
    "ROMVariant", "MapDef", "ALL_VARIANTS",
    "ROM_266D", "ROM_266B", "ROM_AAH",
    "unscramble_034", "unscramble_byte",
    "fuel_266d_decode", "fuel_266d_encode",
    "fuel_lambda_decode", "fuel_lambda_encode",
    "timing_decode", "timing_encode",
    "RPM_AXIS_266D", "RPM_AXIS_266B", "TIMING_RPM_AXIS",
    "LOAD_AXIS", "RPM_AXIS_AAH", "LOAD_AXIS_AAH",
    "CHECKSUM_PARAMS",
]
