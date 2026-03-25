# HachiROM

**Hitachi MMS ECU ROM editor — 7A 20v and AAH 12v**  
Standalone desktop app plus Python library.

> **⚠ Work in Progress — Use at Your Own Risk**
>
> This tool is under active development. Features may be incomplete, map
> addresses may be unverified, and patches may not have been tested on all
> hardware variants. **Always read and back up your original ROM before making
> any changes.** Read it twice, compare the files, keep both copies safe.
>
> If you find a bug, incorrect address, or have a ROM dump to contribute,
> please [open an issue](https://github.com/dspl1236/HachiROM/issues).


[![Build](https://github.com/dspl1236/HachiROM/actions/workflows/build.yml/badge.svg)](https://github.com/dspl1236/HachiROM/actions/workflows/build.yml)
[![Download](https://img.shields.io/github/v/release/dspl1236/HachiRom?label=Download&logo=github)](https://github.com/dspl1236/HachiRom/releases/latest)

## ⬇ Download

**→ [Download HachiROM (latest build)](https://github.com/dspl1236/HachiROM/releases/latest)**

Windows `.exe` — no install required. Run from source on Linux/macOS: `pip install -r requirements.txt && python app/main.py`

---

> **⚠ Before writing any ROM** — always read and save the original chip first. Read it twice, compare the files, keep both copies safe. A write to the wrong address is silent and only shows at startup.


## Supported ECUs — Hitachi MMS family

| Part number | Hardware | Engine | Connector | Notes |
|-------------|----------|--------|-----------|-------|
| 893906266D  | MMS05C   | 7A 20v — 2.3L (1991–1995) | 4-pin MAF | Primary target — all patches supported |
| 893906266B  | MMS-04B  | 7A 20v — 2.3L (pre-1991)  | 4-pin MAF | Earlier platform than 266D (MMS05C). MAF linearisation table present. |
| 4A0906266   | MMS100   | AAH 12v — 2.8L V6         | 3-pin MAF  | Separate ECU generation — maps editable, no MAF/CO pot patches |
| 8A0906266A  | MMS-200  | AAH/ACK 2.8L V6 (1992–95) | 3-pin MAF  | Same ROM layout as MMS100. NMAX 16-bit LE at 0x077D. Verified. |
| 8A0906266B  | MMS-300  | AAH/ACK 2.8L V6 (later)   | 3-pin MAF  | Fuel@0x0700, timing@0x1100/0x1200, NMAX@0x0524. Timing near-identical to MMS-200. |

The 266D uses the MMS05C hardware platform. The 266B uses the earlier MMS-04B platform. The AAH MMS100 is a later
generation with a different load sensing architecture (MAP-based, not MAF-based).

---

## Features

- 🔍 **ROM Detection** — Auto-identifies variant by signature, hash, and reset vector
- 🗺 **Heatmap Map Editor** — Fuel and timing maps with colour-coded cell editing
- ⊕ **ROM Compare / Diff** — Side-by-side byte diff with map region tagging and delta values
- ✅ **Checksum** — Auto-corrected on save (verify before burn)
- 🔧 **MAF Axis Patch** — Rescale fuel/timing axis for a different MAF housing (266D/266B)
- 🔧 **CO Pot Disable Patch** — Suppress fault 00521 when fitting a no-CO-pot sensor (266D + 266B)
- 💾 **Multi-format Save** — 32KB `.bin` (Teensy), 64KB 27C512 `.bin` (EPROM programmer)
- 📦 **Python Library** — Use as a library in other projects

---

## ROM Formats

Auto-detected on open:

| Format | Size | Notes |
|--------|------|-------|
| `.bin` 32KB | 32 768 bytes | Raw ROM — Teensy SD card |
| `.bin` 64KB | 65 536 bytes | 27C512 image (two mirrored halves) |
| `.034`      | 65 536 bytes | MMS bit-scrambled 27C512 — standard tuning file |

---

## Map Locations — 7A (893906266D / 266B)

| Map | Address | Size | Description |
|-----|---------|------|-------------|
| Fuel | `0x0000` | 16×16 | Lambda offset — signed, midpoint = 128 |
| Timing | `0x0100` | 16×16 | Ignition advance — degrees BTDC |
| RPM axis | `0x05C0` | 16 bytes | Raw × 50 = RPM (250–7000) |
| MAF axis (fuel) | `0x05D0` | 16 bytes | ADC breakpoints 0–255 |
| MAF axis (timing) | `0x05E0` | 16 bytes | Identical copy of fuel MAF axis |
| RPM limit | `0x07D2` | 1 byte | Raw × 25 = RPM |
| Injection scaler | `0x077E` | 1 byte | Global fuelling scalar |

---

## Patches — 266D and 266B

### MAF Axis Patch

Rewrites the 16-point MAF ADC lookup axis at `0x05D0` (fuel) and `0x05E0` (timing)
to match a different sensor/housing combination. Both copies always updated together.
Fuel and timing map data is untouched — only the axis interpolation is rescaled.

| Profile key | Sensor | Housing | CO pot |
|-------------|--------|---------|--------|
| `stock_7a` | Hitachi 054 133 471/A | 50mm stock | ✓ |
| `aah_v6_housing` | Hitachi 054 133 471 A | 74mm AAH V6 housing | ✓ |
| `sensor_1_8t_60` ⚠ | Bosch 0280218114 | 60mm 1.8T housing | ✗ |
| `sensor_1_8t_vr6` ⚠ | Bosch 0280218114 | 69.85mm VR6/TT225 | ✗ |

⚠ = EXPERIMENTAL — derived from King's law bore area calculations. Not verified on engine.  
Always validate with a wideband O2 sensor before road use.

**Note:** All MAF profiles are **axis-only** patches (32 bytes). Analysis of 034 Motorsport's
"NA Big MAF" calibration shows a full MAF housing swap also requires recalibrating the
linearization table (0x02D0), fuel map, timing map, and enrichment tables (682 bytes total).
The axis patch gets the car running safely but is not a complete recalibration.

See [`docs/MAF_SENSOR_WIRING.md`](docs/MAF_SENSOR_WIRING.md) for full wiring and conversion details.

### CO Pot Disable Patch

Disables idle lambda trim (pin 4) and suppresses fault **00521** when no CO pot is present.
Works on both 266D and 266B — HachiROM auto-detects the variant.

The patch redirects the LDAA instruction that reads the CO pot ADC result to
load the baseline channel instead, making the trim delta always zero:

| Variant | File offset | Stock | Patched | Effect |
|---------|-------------|-------|---------|--------|
| 266D | `0x2349–0x234A` | `0x16 0xF4` | `0x14 0x9D` | LDAA $16F4 → LDAA $149D |
| 266B | `0x23A5–0x23A6` | `0x42 0xF4` | `0x40 0x9D` | LDAA $42F4 → LDAA $409D |

Pin 4 can be left unconnected after this patch. Checksum is auto-corrected on save.
Both patches are independently reversible.

---

## Chip Burning Workflow

1. Open ROM in HachiROM, make edits
2. **Save 27C512 .bin** (64KB) for EPROM programmers (TL866, T48, etc.)  
   or **Save .bin** (32KB) for Teensy SD card
3. Checksum is auto-corrected on save
4. Program a 27C256 or 27C512 EPROM
5. Install chip — notch toward ECU connector edge

---

## Run from Source

```bash
pip install PyQt5
python app/main.py
```

## As a Python Library

```python
import hachirom as hr

with open("my_rom.bin", "rb") as f:
    data = f.read()

result = hr.detect(data)
print(result.variant.version_key)       # "266D"

fuel = hr.read_map(data, result.variant.maps[0])

# MAF axis patch
patched = hr.apply_maf_patch(data, "aah_v6_housing")

# CO pot disable
patched = hr.apply_co_pot_patch(patched, disable=True)

# Detect patch state
print(hr.detect_maf_patch(data))        # "stock_7a"
print(hr.detect_co_pot_patch(data))     # "stock"
```

---

## Relation to audi90-teensy-ecu

HachiROM is the source of truth for map definitions, offsets, and formulas.
The Teensy project imports `hachirom` directly.

```
HachiROM ──(pip install / submodule)──▶ audi90-teensy-ecu
    │
    ├── hachirom/roms.py    ← map definitions, MAF profiles, CO pot addresses
    ├── hachirom/maps.py    ← read/write/patch/checksum logic
    └── hachirom/detect.py  ← variant detection
```

---

## Contributing

Stock ROM dumps (`.bin` or `.034`) for 266D, 266B, and AAH variants are always welcome.
More dumps improve detection confidence and enable further ROM analysis.
Please open a GitHub issue with your CRC32 and ECU part number.

https://github.com/dspl1236/HachiROM
