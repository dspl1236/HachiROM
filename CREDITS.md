# HachiROM — Credits & Acknowledgements

HachiROM is an open-source ROM editor and EPROM emulator companion tool for
Hitachi MMS-family ECUs (MMS05C, MMS100, MMS-200, MMS-300).

---

## ROM Research & XDF Files

**LHN** (NefMoto Forums)
- XDF definition files for 4A0906266 / 8A0906266A (MMS-100 / MMS-200)
- Confirmed shared ROM layout between MMS-100 and MMS-200 platforms
- Source: nefariousmotorsports.com, topics 2662 and 9732

**20v-sauger-tuning.de**
- MAF housing transplant documentation (078 133 471 AAH V6 housing mod)
- CO pot wiring and pin function confirmation
- AAH V6 housing bore dimensions used for King's law MAF axis calculation
- Source: www.20v-sauger-tuning.de/luftmassenmesserumbau3.htm

**S2forums.com community**
- Stock ROM dumps and ECU identification assistance
- 7A engine tuning knowledge base

**034Motorsport** (historical)
- RIP Chip map files and MAF axis research reference
- Big MAF axis data used to cross-validate aah_v6_housing profile

---

## ROM Dumps

| File | Variant | Source | Notes |
|------|---------|--------|-------|
| 893906266D_MMS05C_physical.bin | 266D | Physical EPROM read | Primary truth reference |
| 034_-_893906266D_Stock.034 | 266D | 034Motorsport (archived) | Stock baseline |
| 034_-_893906266B_Stock.034 | 266B | 034Motorsport (archived) | Stock baseline |
| V6AAHCoupeMMS200.bin | 8A0906266A | NefMoto forums (LHN) | MMS-200 map verification |

---

## Tools & Prior Art

**TunerPro / TunerPro RT**
- XDF format used as reference for map address extraction

**NefMoto** (Tony)
- Community ECU flashing and tuning platform
- Forum is the primary knowledge base for Hitachi MMS ECU research

---

## Project

HachiROM is developed by **dspl1236** as a companion to the
[audi90-teensy-ecu](https://github.com/dspl1236/audi90-teensy-ecu) project —
a Teensy 4.1-based EPROM emulator and map switcher for Hitachi MMS ECUs.

If you have ROM dumps, XDF files, or hardware documentation for any MMS-family
ECU not listed above, please open an issue or pull request on GitHub.

Particularly wanted:
- 8A0906266B (MMS-300) — any stock dump
- 893906266B early stock dumps with known-good checksums
- 4A0906266 additional stock variants (different CRC32s)
