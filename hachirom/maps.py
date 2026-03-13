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
