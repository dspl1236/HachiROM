"""
HachiROM — Map I/O, checksum, and compare tools.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from .roms import ROMVariant, MapDef


# ---------------------------------------------------------------------------
# Map extraction
# ---------------------------------------------------------------------------

def read_map(data: bytes, map_def: MapDef) -> list[list[int]]:
    """
    Extract a 2D map from ROM bytes.
    Returns a rows x cols list of raw byte values.
    Single-row maps return a 1 x cols list.
    16-bit maps (cols=2 for 1 row special cases) handled separately.
    """
    rows, cols = map_def.rows, map_def.cols
    addr = map_def.address
    result = []
    for r in range(rows):
        row = []
        for c in range(cols):
            offset = addr + r * cols + c
            if offset < len(data):
                row.append(data[offset])
            else:
                row.append(0)
        result.append(row)
    return result


def read_map_decoded(data: bytes, map_def: MapDef) -> list[list]:
    """
    Like read_map but applies the decode function if one is defined.
    """
    raw = read_map(data, map_def)
    if map_def.decode is None:
        return raw
    return [[map_def.decode(v) for v in row] for row in raw]


def write_map(data: bytearray, map_def: MapDef, values: list[list[int]]) -> bytearray:
    """
    Write a 2D map of raw byte values back into the ROM bytearray.
    Returns the modified bytearray.
    """
    addr = map_def.address
    rows, cols = map_def.rows, map_def.cols
    for r in range(rows):
        for c in range(cols):
            offset = addr + r * cols + c
            if r < len(values) and c < len(values[r]) and offset < len(data):
                data[offset] = max(0, min(255, int(values[r][c])))
    return data


def write_map_encoded(data: bytearray, map_def: MapDef, values: list[list]) -> bytearray:
    """
    Write decoded (human) values back after applying encode function.
    """
    if map_def.encode is None:
        return write_map(data, map_def, values)
    raw = [[map_def.encode(v) for v in row] for row in values]
    return write_map(data, map_def, raw)


def read_rev_limit(data: bytes, map_def: MapDef) -> int:
    """Read a 16-bit big-endian rev limit word → RPM."""
    addr = map_def.address
    if addr + 1 >= len(data):
        return 0
    word = (data[addr] << 8) | data[addr + 1]
    return int(30_000_000 / word) if word else 0


def write_rev_limit(data: bytearray, map_def: MapDef, rpm: int) -> bytearray:
    """Write RPM as 16-bit big-endian word to rev limit address."""
    word = int(30_000_000 / rpm)
    addr = map_def.address
    data[addr]     = (word >> 8) & 0xFF
    data[addr + 1] = word & 0xFF
    return data


# ---------------------------------------------------------------------------
# Checksum
# ---------------------------------------------------------------------------

def compute_checksum(data: bytes) -> int:
    """Simple 8-bit sum checksum over entire ROM."""
    return sum(data) & 0xFF


def verify_checksum(data: bytes, expected: int) -> bool:
    return compute_checksum(data) == expected


def find_checksum_byte(data: bytes) -> Optional[int]:
    """
    Heuristic: scan for a byte whose position makes the ROM sum to 0x00.
    Returns address if found, None otherwise.
    """
    total = sum(data) & 0xFF
    # Look for last non-zero candidate in the final 256 bytes
    for addr in range(len(data) - 1, len(data) - 256, -1):
        if data[addr] == (0x100 - total + data[addr]) & 0xFF:
            return addr
    return None


# ---------------------------------------------------------------------------
# ROM compare
# ---------------------------------------------------------------------------

@dataclass
class DiffByte:
    address: int
    a: int
    b: int
    map_name: Optional[str] = None   # which map region this falls in, if any


def compare_roms(data_a: bytes, data_b: bytes,
                 variant: Optional[ROMVariant] = None) -> list[DiffByte]:
    """
    Byte-by-byte diff of two ROM images.
    If a variant is supplied, tags each diff byte with the map region it belongs to.
    Returns a list of DiffByte entries for every address that differs.
    """
    length = min(len(data_a), len(data_b))
    diffs: list[DiffByte] = []

    # Pre-build address → map_name lookup for the variant
    addr_map: dict[int, str] = {}
    if variant:
        for m in variant.maps:
            for r in range(m.rows):
                for c in range(m.cols):
                    addr_map[m.address + r * m.cols + c] = m.name

    for addr in range(length):
        if data_a[addr] != data_b[addr]:
            diffs.append(DiffByte(
                address=addr,
                a=data_a[addr],
                b=data_b[addr],
                map_name=addr_map.get(addr),
            ))

    return diffs


def diff_summary(diffs: list[DiffByte]) -> dict[str, int]:
    """
    Summarise diff by map region.
    Returns dict of {region_name: count_of_changed_bytes}.
    """
    from collections import Counter
    c: Counter = Counter()
    for d in diffs:
        c[d.map_name or "unknown"] += 1
    return dict(c)
