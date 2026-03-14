# Reference ROMs

Verified EPROM dumps for Hitachi MMS-family ECUs.
All files are flat 32KB `.bin` images, ready for HachiROM.

---

## 893906266D — MMS05C (7A Late, post-3/90)

| File | Source | CRC32 | Notes |
|------|--------|-------|-------|
| `893906266D_MMS05C_stock.bin` | Physical EPROM read | `0x4152e167` | Primary truth reference. Checksum valid. |
| `893906266D_MMS05C_034stock.bin` | 034Motorsport `.034` (unscrambled) | `0x9babe5c5` | Complete ROM incl. code region. |

---

## 893906266B — MMS-04B (7A Early, pre-3/90)

| File | Source | CRC32 | Notes |
|------|--------|-------|-------|
| `893906266B_MMS04B_stock.bin` | Physical EPROM read (partial) | `0x27f98765` | `0x1100–0x1FFF` erased. Maps intact. |
| `893906266B_MMS04B_034stock.bin` | 034Motorsport `.034` (unscrambled) | `0xa0abd0be` | Complete ROM. |

---

## 4A0906266 — MMS100 (AAH 12v V6)

| File | Source | CRC32 | Notes |
|------|--------|-------|-------|
| `4A0906266_MMS100_stock.bin` | Flat bin | `0x6875638d` | Stock calibration. |
| `4A0906266_MMS100_RIPChip_stock.bin` | 034Motorsport RIP Chip `.034` (unscrambled) | `0x13db1432` | Stock RIP Chip base map. |
| `4A0906266_MMS100_stock_edited.bin` | Flat bin | `0xadab4b96` | Minor edit from stock — checksum valid. |
| `4A0906266_MMS100_RIPChip_stage1.bin` | 034Motorsport Stage 1 `.034` (unscrambled) | `0xdb5aab67` | Stage 1 tune. |

---

## 8A0906266A — MMS-200 (AAH/ACK 2.8 V6, 1992–95)

| File | Source | CRC32 | Notes |
|------|--------|-------|-------|
| `8A0906266A_MMS200_stock.bin` | NefMoto forums (LHN) | `0x1f78f1fe` | Internal ID: `MMS-200C V6H9D34B4 3700`. Same map layout as MMS100. NMAX 16-bit LE at `0x077D`. |

---

## 8A0906266B — MMS-300 (AAH/ACK 2.8 V6, later revision)

| File | Source | CRC32 | Notes |
|------|--------|-------|-------|
| `8A0906266B_MMS300_stock.bin` | Community contribution | `0x84dde88e` | **Truncated dump** — original 61056 bytes, first 32KB extracted. Maps fully intact (fuel@0x0700, timing@0x1100/1200). NMAX 16-bit LE at 0x0524 → 6400 RPM. No padding — real data throughout. Full clean dump wanted. |

---

## Wanted

Needed to expand detection and map coverage — please open a GitHub issue:

- **8A0906266B (MMS-300)** — any stock dump
- **4A0906266 (MMS100)** — additional stock variants (different CRC32s)
- **893906266B** — additional production date variants
- **893906266D** — additional stock variants

Include: ECU part number sticker, vehicle, whether previously programmed,
CRC32 and SHA256 of the file.
