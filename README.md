# HachiROM

**Hitachi ECU ROM editor and analysis library**  
Source of truth for the [audi90-teensy-ecu](https://github.com/dspl1236/audi90-teensy-ecu) project.

[![Build HachiROM](https://github.com/dspl1236/HachiROM/actions/workflows/build.yml/badge.svg)](https://github.com/dspl1236/HachiROM/actions/workflows/build.yml)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20Mac-blue)
![ROM](https://img.shields.io/badge/ROM-27C512%2064KB-yellow)
![ECU](https://img.shields.io/badge/ECU-7A%2020v%20%7C%20AAH%2012v-orange)

## ⬇ Download

**→ [Download HachiROM (latest build)](https://github.com/dspl1236/HachiROM/releases/latest)**

Windows `.exe`, macOS, and Linux binaries — no install required.

---

## Features

- 🔍 **ROM Detection** — Auto-identifies variant by hash, signature, or size
- 🔥 **Heatmap Map Editor** — Ignition, fuel, warmup, IAT/ECT, boost, rev limit, and more
- ⊕ **ROM Compare / Diff** — Byte-by-byte diff with map region tagging and delta values
- ✅ **Checksum** — Compute and verify ROM checksums
- ⚑ **Patch Detection** — Auto-detects known code patches (open loop lambda, ISV disable, etc.)
- 💾 **BIN Save/Load** — Load and save modified `.bin` files ready for flashing
- 📦 **Python Library** — Use as a library in other projects (e.g. Teensy companion tools)

---

## Supported ECUs

| ECU | Chip | Engine | Notes |
|-----|------|--------|-------|
| 893906266D | 27C512 (64KB) | 7A / NF 2.3 20v | Late 4-connector — primary target |
| 893906266B | 27C512 (64KB) | 7A / NF 2.3 20v | Early 2-connector |
| 4A0906266  | 27C512 (64KB) | AAH 2.8 12v V6  | Audi 100 C4 2.8 12v |

---

## Map Locations — 7A Late (893906266D)

| Map | Address | Size | Unit |
|-----|---------|------|------|
| Ignition | 0x2800 | 16×16 | °BTDC |
| Fuel | 0x2900 | 16×16 | raw |
| RPM Scalar | 0x2A00 | 1×16 | RPM |
| Warmup Enrichment | 0x2B00 | 1×17 | % |
| IAT Compensation | 0x2B20 | 1×17 | % |
| ECT Compensation | 0x2B40 | 1×17 | % |
| Knock Retard | 0x2C00 | 1×16 | ° |
| Coil Dwell | 0x2C20 | 1×16 | ms |
| WOT Enrichment | 0x2D00 | 1×17 | % |
| Idle Speed (ISV) | 0x2D40 | 1×16 | raw |
| Accel Enrichment | 0x2E00 | 1×16 | raw |
| Rev Limit | 0x3FF0 | 16-bit word | RPM |

---

## Formula Reference

| Parameter | Formula |
|-----------|---------|
| Ignition | `(210 - byte) / 2.86 = °BTDC` |
| Rev Limit | `30,000,000 / 16-bit word = RPM` |
| RPM Scalar | `15,000,000 / 16-bit word = RPM` |

---

## Usage

### Desktop App

Download from releases and run. No install required.

### Run from Source

```bash
pip install PyQt5
python app/main.py
```

### As a Python Library

```python
from hachirom import load_bin, detect, read_map, compare_roms

data = load_bin("my_rom.bin")
result = detect(data)
print(result.variant.name)    # "7A Late"

ign = read_map(data, result.variant.maps[0])
diffs = compare_roms(data, load_bin("other_rom.bin"), result.variant)
```

### Build Standalone Binary

```bash
pip install pyinstaller
python build.py
```

---

## Relation to audi90-teensy-ecu

HachiROM is the **source of truth** for map definitions, offsets, and formulas.
The Teensy project imports `hachirom` directly for real-time cell editing via serial.

```
HachiROM  ──(pip install / submodule)──▶  audi90-teensy-ecu (companion app)
    │
    └── hachirom/roms.py   ← map definitions, addresses, formulas
    └── hachirom/maps.py   ← read/write/checksum logic
    └── hachirom/detect.py ← variant detection
```

---

## Reference ROMs

Stock dumps go in [`roms/`](roms/). See [`roms/README.md`](roms/README.md).

---

## References

- [034 Motorsport RIP Chip Maps](https://www.034motorsport.com/downloads) — 7A ECU definitions and stock maps
- [audi90-teensy-ecu](https://github.com/dspl1236/audi90-teensy-ecu) — Teensy EPROM emulator project
- [DigifantTool](https://github.com/dspl1236/DigifantTool) — Related Digifant-1 ECU editor (G60/G40)
