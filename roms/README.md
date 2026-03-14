# Reference ROMs

Verified stock EPROM dumps for Hitachi MMS-family ECUs.
All files here are flat 32KB `.bin` images ready for HachiROM.

---

## Included Files

| File | ECU Part | Platform | Source | CRC32 | SHA256 (first 24) |
|------|----------|----------|--------|-------|-------------------|
| `893906266D_MMS05C_stock.bin` | 893906266D | MMS05C | Physical EPROM read | `0x4152e167` | `6a3d773e50afd5ba...` |
| `893906266D_MMS05C_034stock.bin` | 893906266D | MMS05C | 034Motorsport .034 (unscrambled) | `0x9babe5c5` | `2d385db6f428d988...` |
| `893906266B_MMS04B_stock.bin` | 893906266B | MMS-04B | Physical EPROM read (partial) | `0x27f98765` | `94c9ad8bf08991b1...` |
| `893906266B_MMS04B_034stock.bin` | 893906266B | MMS-04B | 034Motorsport .034 (unscrambled) | `0xa0abd0be` | `1289fbd176211366...` |
| `8A0906266A_MMS200_stock.bin` | 8A0906266A | MMS-200 | NefMoto forums (LHN) | `0x1f78f1fe` | `47c33af4fb496f59...` |

---

## Notes

**893906266D_MMS05C_stock.bin** — Physical read from a production ECU chip.
Primary truth reference for all map address work. Checksum valid.

**893906266D_MMS05C_034stock.bin** — Unscrambled from the 034Motorsport
RIP Chip stock `.034` file archived from their website. Identical firmware
to the physical read — different CRC32 due to minor calibration differences
in the code region.

**893906266B_MMS04B_stock.bin** — Physical read, partial EPROM dump.
Region `0x1100–0x1FFF` is erased (0xFF) — checksum region unprogrammed.
Fuel and timing maps intact and verified. 5 bytes differ from 034 stock
at `0x0E3A–0x0E3F` (Decel Cutoff, ±1 count minor revision).

**893906266B_MMS04B_034stock.bin** — Unscrambled from 034Motorsport stock
`.034`. Complete ROM including code region.

**8A0906266A_MMS200_stock.bin** — Stock ROM from NefMoto forums (author: LHN).
Internal version string: `8A0906266A MMS-200C V6H9D34B4 3700`.
Map layout confirmed identical to 4A0906266 (MMS100).
NMAX at `0x077D` (16-bit LE, RPM = raw / 4, stock = 6400 RPM).

---

## Wanted

The following stock dumps are needed to expand HachiROM's detection and
map address coverage. If you have any of these, please open a GitHub issue
or pull request:

- **8A0906266B (MMS-300)** — any stock dump
- **4A0906266 (MMS100/AAH)** — additional stock variants (different CRC32s)
- **893906266B** — additional dumps from different production dates
- **893906266D** — additional stock variants and Stage 1 tunes

To submit a dump, include the ECU part number from the sticker, the vehicle
it came from, and whether the chip has been previously programmed.
SHA256 and CRC32 of the file are helpful for deduplication.
