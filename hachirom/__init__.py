"""
HachiROM
========
Source-of-truth ROM library for Hitachi ECU variants used in
Audi / VW applications (7A 20v, AAH 12v, and related).

Quick start
-----------
    from hachirom import load_bin, detect, read_map

    data = load_bin("my_rom.bin")
    result = detect(data)
    print(result.variant.name)   # e.g. "7A Late"

    ign_map = read_map(data, result.variant.maps[0])
"""

from .detect import detect, load_bin, save_bin, detect_patches, DetectionResult
from .maps   import (read_map, read_map_decoded, write_map, write_map_encoded,
                     read_rev_limit, write_rev_limit,
                     compute_checksum, verify_checksum,
                     compare_roms, diff_summary, DiffByte)
from .roms   import (ROMVariant, MapDef, ALL_VARIANTS,
                     ROM_7A_LATE, ROM_7A_EARLY, ROM_AAH,
                     _ign_decode, _ign_encode, _rpm_decode)

__version__ = "0.1.0"
__all__ = [
    # detect
    "detect", "load_bin", "save_bin", "detect_patches", "DetectionResult",
    # maps
    "read_map", "read_map_decoded", "write_map", "write_map_encoded",
    "read_rev_limit", "write_rev_limit",
    "compute_checksum", "verify_checksum",
    "compare_roms", "diff_summary", "DiffByte",
    # roms
    "ROMVariant", "MapDef", "ALL_VARIANTS",
    "ROM_7A_LATE", "ROM_7A_EARLY", "ROM_AAH",
    "_ign_decode", "_ign_encode", "_rpm_decode",
]
