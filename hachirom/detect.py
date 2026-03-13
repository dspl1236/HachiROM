"""
HachiROM — ROM detection engine.
Identifies which variant a loaded .bin file corresponds to.
"""

import hashlib
from pathlib import Path
from typing import Optional
from .roms import ROMVariant, ALL_VARIANTS


class DetectionResult:
    def __init__(self, variant: Optional[ROMVariant], sha256: str,
                 size: int, confidence: str, notes: list[str]):
        self.variant = variant
        self.sha256 = sha256
        self.size = size
        self.confidence = confidence   # "hash_match" | "size_match" | "unknown"
        self.notes = notes

    def __repr__(self):
        name = self.variant.name if self.variant else "Unknown"
        return f"<DetectionResult variant={name!r} confidence={self.confidence!r}>"


def detect(data: bytes) -> DetectionResult:
    """
    Attempt to identify the ROM variant from raw binary data.
    Returns a DetectionResult with the best match (or None if unknown).
    """
    sha256 = hashlib.sha256(data).hexdigest()
    size = len(data)
    notes: list[str] = []

    # 1. Hash match (most reliable — exact stock dump)
    for variant in ALL_VARIANTS:
        if sha256 in variant.known_hashes:
            return DetectionResult(variant, sha256, size, "hash_match",
                                   [f"Exact hash match for {variant.name}"])

    # 2. Signature byte match
    for variant in ALL_VARIANTS:
        if (variant.signature is not None
                and variant.signature_offset is not None
                and size >= variant.signature_offset + len(variant.signature)):
            window = data[variant.signature_offset:
                          variant.signature_offset + len(variant.signature)]
            if window == variant.signature:
                notes.append(f"Signature match at 0x{variant.signature_offset:04X}")
                return DetectionResult(variant, sha256, size, "signature_match", notes)

    # 3. Size heuristic — narrow by chip size
    candidates = [v for v in ALL_VARIANTS if v.size == size]
    if len(candidates) == 1:
        notes.append(f"Only one known variant matches size {size} bytes")
        return DetectionResult(candidates[0], sha256, size, "size_match", notes)
    elif len(candidates) > 1:
        names = [v.name for v in candidates]
        notes.append(f"Multiple variants match size {size}: {names}. Manual selection needed.")
        return DetectionResult(candidates[0], sha256, size, "ambiguous", notes)

    notes.append(f"Unknown ROM: {size} bytes, SHA256 {sha256[:16]}…")
    return DetectionResult(None, sha256, size, "unknown", notes)


def detect_patches(data: bytes, variant: ROMVariant) -> dict[str, bool]:
    """
    Check which known patches are applied in the ROM.
    Returns dict of patch_name -> is_patched.
    """
    from .roms import _7A_LATE_PATCHES
    # Only 7A Late has defined patches for now
    patch_map = {}
    if not hasattr(variant, '_patches'):
        # attach patches to variant lazily if it matches
        if variant.part_number == "893906266D":
            patches = _7A_LATE_PATCHES
        else:
            return {}
    else:
        patches = variant._patches

    for name, (addr, stock, patched, _desc) in patches.items():
        window = data[addr:addr + len(stock)]
        if window == patched:
            patch_map[name] = True
        elif window == stock:
            patch_map[name] = False
        else:
            patch_map[name] = None  # unexpected / custom

    return patch_map


def load_bin(path: str | Path) -> bytes:
    """Load a .bin file from disk."""
    return Path(path).read_bytes()


def save_bin(data: bytes, path: str | Path) -> None:
    """Save binary data to a .bin file."""
    Path(path).write_bytes(data)
