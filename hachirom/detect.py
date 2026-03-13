"""
HachiROM — ROM detection engine.
Detection priority:
  1. CRC32 against known stock hashes              → confidence "hash"
  2. Reset vector at 0x7FFE                        → confidence "reset_vector"
  3. Structural scoring (byte sum, map markers)    → confidence "heuristic"
  4. Fallthrough                                   → confidence "unknown"

Edited ROMs always fail CRC32 — that is expected. The structural scorer is
designed to remain stable across any edited or tuned ROM of a given variant.

File size handling (load_bin normalises before detect sees anything):
  64KB (27C512 image):
    - lower all-0xFF → use upper half  (our Save 27C512 layout)
    - upper all-0xFF → use lower half  (some programmer reads)
    - lower == upper → mirrored, use lower half
    - otherwise      → prefer whichever half scores better
  <32KB but >0:      → zero-pad to 32KB, note truncation
  >64KB:             → use first 64KB then apply 64KB rules
"""

import hashlib
import zlib
from pathlib import Path
from typing import Optional
from .roms import ROMVariant, ALL_VARIANTS, _CRC32_MAP, _RESET_VEC_MAP, unscramble_034

_FF_THRESHOLD = 0.995   # half is "all 0xFF" if >= 99.5% of bytes are 0xFF


class DetectionResult:
    def __init__(self, variant: Optional[ROMVariant], sha256: str, crc32: int,
                 size: int, confidence: str, notes: list[str]):
        self.variant    = variant
        self.sha256     = sha256
        self.crc32      = crc32
        self.size       = size          # original file size before normalisation
        self.confidence = confidence    # "hash"|"reset_vector"|"heuristic"|"unknown"
        self.notes      = notes

    def __repr__(self):
        name = self.variant.name if self.variant else "Unknown"
        return f"<DetectionResult variant={name!r} confidence={self.confidence!r}>"


# ---------------------------------------------------------------------------
# File normalisation — called by load_bin and detect()
# ---------------------------------------------------------------------------

def _normalise(data: bytes, notes: list[str]) -> bytes:
    """
    Return a 32KB native ROM from whatever the user dropped on us.
    Handles: 27C512 64KB images (mirrored / padded / either-half),
             truncated files, over-sized files, .034 scrambled files.
    Modifies `notes` in-place to describe what was done.
    """
    original_size = len(data)

    # --- Step 1: Collapse >32KB to candidate 32KB halves -----------------
    if original_size == 65536 or original_size > 32768:
        lo = data[:32768]
        hi = data[32768:65536]

        lo_ff = sum(1 for b in lo if b == 0xFF) / 32768
        hi_ff = sum(1 for b in hi if b == 0xFF) / 32768

        if lo == hi:
            notes.append("64KB file: both halves identical (mirrored chip) — using lower half")
            data = lo
        elif lo_ff >= _FF_THRESHOLD and hi_ff < _FF_THRESHOLD:
            notes.append("64KB file: lower half is erased (0xFF pad), using upper half")
            data = hi
        elif hi_ff >= _FF_THRESHOLD and lo_ff < _FF_THRESHOLD:
            notes.append("64KB file: upper half is erased (0xFF pad), using lower half")
            data = lo
        else:
            # Both halves have data — score each and pick the better one
            score_lo = _quick_score(lo)
            score_hi = _quick_score(hi)
            if score_hi >= score_lo:
                notes.append(
                    f"64KB file: both halves have data "
                    f"(lo_score={score_lo}, hi_score={score_hi}) — using upper half")
                data = hi
            else:
                notes.append(
                    f"64KB file: both halves have data "
                    f"(lo_score={score_lo}, hi_score={score_hi}) — using lower half")
                data = lo

    # --- Step 2: Handle files smaller than 32KB --------------------------
    if len(data) < 32768:
        pad = 32768 - len(data)
        notes.append(
            f"File is {original_size} bytes (< 32KB) — "
            f"zero-padded {pad} bytes to 32KB for analysis")
        data = data + bytes(pad)

    # --- Step 3: Trim to exactly 32KB ------------------------------------
    rom32 = data[:32768]

    # --- Step 4: Try .034 unscramble if CRC not recognised ---------------
    crc = zlib.crc32(rom32) & 0xFFFFFFFF
    if crc not in _CRC32_MAP:
        unscrambled = unscramble_034(rom32)
        if (zlib.crc32(unscrambled) & 0xFFFFFFFF) in _CRC32_MAP:
            notes.append("Auto-detected .034 scrambled file — unscrambled")
            return unscrambled

    return rom32


def _quick_score(half: bytes) -> int:
    """
    Fast structural score for choosing between two 32KB halves.
    Uses only the most reliable markers (reset vector + byte sum proximity).
    """
    score = 0
    vec = (half[0x7FFE], half[0x7FFF])
    if vec in _RESET_VEC_MAP:
        score += 50
    for v in ALL_VARIANTS:
        target = v.checksum.get("target", 0)
        if abs(sum(half) - target) < 20000:
            score += 20
            break
    ff_pct = sum(1 for b in half if b == 0xFF) / 32768
    if ff_pct < 0.5:      # real ROM data
        score += 10
    return score


# ---------------------------------------------------------------------------
# Structural variant scorer
# ---------------------------------------------------------------------------

def _score_variant(rom32: bytes, variant: ROMVariant) -> int:
    """
    Score a 32KB ROM against a variant using stable structural markers.
    Returns an integer; ≥30 with ≥15 margin over next = confident.
    All markers are outside tunable map regions.
    """
    score = 0
    vk    = variant.version_key
    vec   = (rom32[0x7FFE], rom32[0x7FFF])

    # Reset vector (unique per variant, high weight)
    if variant.reset_vector and tuple(variant.reset_vector) == vec:
        score += 50

    # Byte sum vs checksum target
    cs_target = variant.checksum.get("target", 0)
    cs_actual = sum(rom32)
    if cs_actual == cs_target:
        score += 35
    elif abs(cs_actual - cs_target) < 2000:
        score += 20
    elif abs(cs_actual - cs_target) < 20000:
        score += 5

    # Variant-specific structural markers
    if vk == "AAH":
        if rom32[0x077E] == 100:                        # injection scaler stock=100
            score += 10
        if 200 <= rom32[0x07E1] <= 255:                 # CL RPM high range
            score += 5
        if len(set(rom32[0x6700:0x6720])) > 8:          # cs region has varied data
            score += 5

    elif vk == "266D":
        blank_7e = sum(1 for b in rom32[0x7E00:0x7F00] if b == 0xFF)
        if blank_7e < 20:                               # 266D is fully programmed
            score += 15
        if len(set(rom32[0x1600:0x1620])) > 6:
            score += 5

    elif vk == "266B":
        blank_7e = sum(1 for b in rom32[0x7E00:0x7F00] if b == 0xFF)
        if blank_7e > 180:                              # 266B has large blank region
            score += 25
        if len(set(rom32[0x02D0:0x02E0])) > 4:         # MAF linearisation data
            score += 5

    return score


# ---------------------------------------------------------------------------
# Main detection entry point
# ---------------------------------------------------------------------------

def detect(data: bytes) -> DetectionResult:
    """
    Identify the ROM variant. Accepts:
      - Raw 32KB .bin
      - 64KB 27C512 image (mirrored, upper-pad, or lower-pad)
      - Scrambled .034 file
      - Truncated / partial files
    Always returns a result — variant is None only for truly unrecognised ROMs.
    """
    notes: list[str] = []
    original_size = len(data)
    rom32 = _normalise(data, notes)

    sha256 = hashlib.sha256(rom32).hexdigest()
    crc32  = zlib.crc32(rom32) & 0xFFFFFFFF
    vec    = (rom32[0x7FFE], rom32[0x7FFF])

    # 1. CRC32 exact match
    if crc32 in _CRC32_MAP:
        v = _CRC32_MAP[crc32]
        return DetectionResult(v, sha256, crc32, original_size, "hash",
                               notes + [f"CRC32 match: {v.name} ({v.part_number})"])

    # 2. Reset vector match
    if vec in _RESET_VEC_MAP:
        v = _RESET_VEC_MAP[vec]
        notes.append(f"Reset vector {vec[0]:02X} {vec[1]:02X} → {v.name}")
        return DetectionResult(v, sha256, crc32, original_size, "reset_vector", notes)

    # 3. Structural scoring
    scores = [(v, _score_variant(rom32, v)) for v in ALL_VARIANTS]
    scores.sort(key=lambda x: -x[1])
    best_v, best_score = scores[0]
    second_score       = scores[1][1]
    margin             = best_score - second_score

    if best_score >= 30 and margin >= 15:
        notes.append(
            f"Structural match → {best_v.name} "
            f"(score {best_score}, margin +{margin})")
        notes.append(
            f"vec={vec[0]:02X}{vec[1]:02X}  "
            f"bytesum={sum(rom32):,}  "
            f"target={best_v.checksum.get('target', 0):,}")
        return DetectionResult(best_v, sha256, crc32, original_size, "heuristic", notes)

    # 4. Unknown
    guess = f"{best_v.name} (score {best_score})" if best_score > 0 else "none"
    notes.append(
        f"No confident match. Best guess: {guess}. "
        f"vec={vec[0]:02X}{vec[1]:02X}  bytesum={sum(rom32):,}")
    return DetectionResult(None, sha256, crc32, original_size, "unknown", notes)


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def load_bin(path: str | Path) -> bytes:
    """
    Load a ROM file from disk. Normalisation (27C512 unwrap, pad, .034
    unscramble) happens inside detect() — load_bin returns raw bytes so
    the caller can decide whether to normalise or not.
    """
    return Path(path).read_bytes()


def load_bin_normalised(path: str | Path) -> tuple[bytes, list[str]]:
    """
    Load and normalise to a 32KB native ROM, returning (rom32, notes).
    Use this when you want the ready-to-edit bytes, not the raw file.
    """
    raw   = Path(path).read_bytes()
    notes: list[str] = []
    rom32 = _normalise(raw, notes)
    return rom32, notes


def save_bin(data: bytes, path: str | Path) -> None:
    Path(path).write_bytes(data)
