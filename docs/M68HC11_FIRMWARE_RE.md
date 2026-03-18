# M68HC11 Firmware Reverse Engineering Reference
# Hitachi MMS-05C / MMS-04B — 7A 20v ECU (893 906 266D / 266B)

This document collects the M68HC11 architectural knowledge needed to reverse
engineer the 7A ECU firmware, trace the CO pot ADC read, and implement the
pin 4 correction loop patch described in PIN4_SENSOR_OPTIONS.md.

**Primary reference:** NXP/Freescale M68HC11 Reference Manual Rev 6.1
`https://www.nxp.com/docs/en/reference-manual/M68HC11RM.pdf`

---

## CPU Architecture Overview

The M68HC11 is an 8-bit CPU with the following programmer-visible registers:

| Register | Width | Purpose |
|----------|-------|---------|
| A | 8-bit | Accumulator A — primary for byte operations |
| B | 8-bit | Accumulator B — secondary |
| D | 16-bit | Double accumulator (A:B concatenated) |
| X | 16-bit | Index register X — base for table lookups |
| Y | 16-bit | Index register Y — base for table lookups |
| SP | 16-bit | Stack pointer |
| PC | 16-bit | Program counter |
| CCR | 8-bit | Condition code register (N, Z, V, C, H, I, X, S bits) |

The 7A ECU runs the M68HC11 in **expanded multiplexed mode** — Port B carries
the high address byte (A8–A15), Port C carries the multiplexed low
address / data bus (AD0–AD7), and the AS (address strobe) pin demultiplexes
them. The Teensy EPROM emulator sits on this bus and answers fetch cycles
from the external address space (0x8000–0xFFFF for a 32KB EPROM).

---

## Addressing Modes — Table Lookup Patterns

Table lookups in M68HC11 firmware follow a highly recognisable pattern.
Once you can identify these in a disassembly, every calibration table in
the firmware becomes visible.

### Standard indexed table read (most common):

```asm
LDX  #$xxxx        ; Load table base address into X
LDAA $00,X         ; Load byte at X+0 into A  (or LDAA offset,X)
```

Or with a computed offset:

```asm
LDX  #$xxxx        ; Table base
ABX                ; X = X + B  (B holds the row/column index)
LDAA $00,X         ; Read table byte
```

### Two-register indexed lookup (16-bit result or 2D table):

```asm
LDX  #$xxxx        ; Row base
ABX                ; Add row index
LDY  #$xxxx        ; Column offset or second table
LDAA $00,Y
```

The CO pot ADC result will be used as an index into the fuel correction
scalar. Look for `LDAB` or `LDAA` reading an ADC result register, followed
by one of these patterns feeding into the fuel calculation path.

---

## ADC System (Section 12 of Reference Manual)

### Control and result registers (internal I/O space, base `$1000`):

| Register | Address | Function |
|----------|---------|----------|
| ADCTL | `$1030` | ADC control — starts conversion, selects channel |
| ADR1 | `$1031` | Conversion result 1 |
| ADR2 | `$1032` | Conversion result 2 |
| ADR3 | `$1033` | Conversion result 3 |
| ADR4 | `$1034` | Conversion result 4 |

### ADCTL register bits:

| Bit | Name | Function |
|-----|------|----------|
| 7 | CCF | Conversion complete flag (read-only; set when complete) |
| 6 | — | Reserved |
| 5 | SCAN | 0=single, 1=continuous scan |
| 4 | MULT | 0=4 conversions on one channel, 1=4 channels in sequence |
| 3:0 | CD:CA | Channel select |

**Channel select for CO pot (pin 4 of MAF connector):**
The specific ADC channel used for the CO pot signal needs tracing from the
firmware or the ECU schematic. Look for `STAA $1030` (write to ADCTL) with
a channel select value, followed later by `LDAA $1031` (read ADR1).

**Identifying the CO pot ADC read in disassembly:**
Search for write sequences to `$1030` and note the channel select bits.
The CO pot read is the one that feeds the fuel trim multiply/add sequence.
The result will be used in a `MUL` (multiply D = A × B) or `ADDA` instruction
shortly after.

### Typical ADC read sequence in firmware:

```asm
LDAA  #$xx          ; Channel select value (CD:CA bits set for CO pot channel)
STAA  $1030         ; Write ADCTL — starts conversion
; ... delay loop or poll CCF bit ...
LDAA  $1030         ; Read ADCTL — check CCF (bit 7)
BPL   *-3           ; Loop until CCF set (branch if plus = CCF clear)
LDAA  $1031         ; Read ADR1 — 8-bit result (0–255 = 0–5V)
```

The 8-bit result in A is then used as the CO pot scalar index.

---

## Interrupt Architecture (Section 5)

The main fuel calculation loop almost certainly runs inside a **timer
output compare interrupt** — the M68HC11 main timer fires at a fixed
rate tied to the engine crank signal or a fixed-period timer.

### Interrupt vector table (top of ROM, 0xFFCO–0xFFFF):

| Vector | Address | Source |
|--------|---------|--------|
| `$FFD6:D7` | Timer overflow | |
| `$FFE4:E5` | Output compare 1 | |
| `$FFE6:E7` | Output compare 2 | |
| `$FFE8:E9` | Output compare 3 | |
| `$FFEA:EB` | Output compare 4 | |
| `$FFEC:ED` | Output compare 5 | |
| `$FFF2:F3` | IRQ (external) | |
| `$FFF4:F5` | XIRQ (non-maskable) | |
| `$FFF8:F9` | SWI | |
| `$FFFC:FD` | COP failure | |
| `$FFFE:FF` | RESET | |

Read the reset vector first (`$FFFE:FF`) to find the firmware entry point.
Read the timer interrupt vectors to find the ISR entry points — the fuel
calculation subroutine will be called from one of these.

### ISR identification pattern:

```asm
; Timer ISR entry (no prologue — M68HC11 auto-stacks all registers on interrupt)
; ... fuel calculation code ...
RTI                 ; Return from interrupt (restores stacked registers)
```

Regular subroutines end with `RTS`. ISRs end with `RTI`. This distinction
makes ISR boundaries unambiguous in a disassembly.

---

## The CO Pot Trim Loop — What to Find and Patch

The stock firmware reads the CO pot ADC value and uses it to apply a
small fuel trim at idle. The sequence to find and eventually redirect:

1. **ADC read** — `STAA $1030` → poll CCF → `LDAA $1031`
2. **Scaling** — result multiplied or shifted to become a signed trim value
3. **Application** — trim added/subtracted from the base injection pulsewidth

Once located, the patch goal is:

**Option A — Firmware patch (cleanest):**
Replace the ADC read section with a table lookup into the correction
table the Teensy writes at `0x1E87`. The ECU reads the Teensy-maintained
table instead of the raw ADC value. The Teensy updates the table based on
the live wideband/MAP/IAT reading on its analog input.

```
Before: LDAA ADC_result → scale → apply trim
After:  LDAA [table@0x1E87 + current_load_index] → apply trim
```

**Option B — Teensy intercept (no firmware change needed):**
Identify a scalar or table cell that gets fetched from ROM address space
frequently during the fuel calculation loop. The Teensy monitors the
address bus and substitutes a dynamically calculated value when that
address is accessed. Requires knowing the exact ROM address, cycle timing,
and that the value is stable enough to substitute safely.

Option A is architecturally cleaner. Option B avoids writing new M68HC11
assembly but is harder to make robust against timing edge cases.

---

## Bootstrap Mode — Testing Patches Without Burning EPROMs

The M68HC11 has a **special bootstrap mode** activated by holding MODA and
MODB low at reset (Section 3.7.4). In this mode the CPU loads code via the
SCI (serial port) at 1200 baud into internal RAM and executes it.

For the 7A ECU this is not directly usable for live testing because the
firmware runs from external EPROM in expanded mode, not internal ROM. The
Teensy emulator is the practical test vehicle — modify the image the
Teensy serves and the ECU sees the new code immediately on next startup
without a physical EPROM burn.

The bootstrap mode is documented here because it reveals the SCI (UART)
pin assignments and baud rate configuration, which may be useful for other
diagnostic approaches.

---

## Memory Map (Expanded Mode, 266D / MMS-05C)

| Address Range | Size | Contents |
|---------------|------|----------|
| `$0000–$00FF` | 256B | Internal direct-page RAM (fast access) |
| `$0100–$1FFF` | ~7.8KB | External RAM (ECU board SRAM) |
| `$1000–$103F` | 64B | Internal I/O registers (overlaid in RAM space) |
| `$2000–$7FFF` | 24KB | External RAM / unmapped |
| `$8000–$FFFF` | 32KB | External EPROM (MMS-05C / 27C256 or 27C512 upper half) |

The EPROM occupies the top 32KB. All firmware code, calibration tables,
and the safe block at `0x1E87` (relative to EPROM base — absolute address
`$9E87`) live in this space.

**Safe block absolute address:** `$9E87–$9EC9` (confirmed 0xFF, no code
references in either 266D or 266B firmware).

---

## Recommended Disassembly Approach

1. Load the 32KB working half into a M68HC11 disassembler (GhiDRA has
   M68HC11 support via the processor module; also `m68hc11-elf-objdump`
   with a flat binary)
2. Set base address to `$8000`
3. Define the reset vector entry point first (`$FFFE:FF` → firmware start)
4. Define all interrupt vectors as code entry points
5. Mark internal I/O register addresses as named equates (`$1030` = ADCTL etc.)
6. Search for `STAA $1030` — each occurrence is an ADC conversion start
7. Trace forward from each ADC read to find what happens to the result
8. The one feeding a signed trim into the pulsewidth calculation is the
   CO pot trim loop

---

## Status

| Task | Status |
|------|--------|
| M68HC11 architecture understood | ✓ |
| ADC register map documented | ✓ |
| CO pot ADC channel — specific channel | ❌ Needs firmware trace |
| CO pot trim loop — exact address range | ❌ Needs disassembly |
| Safe block at `0x1E87` confirmed | ✓ (both 266D and 266B) |
| Teensy table read implemented | ✓ (sensor type + linearisation) |
| Option A firmware patch | ❌ Pending CO pot loop RE |
| Option B Teensy intercept | ❌ Pending address identification |
| Live correction loop (closed-loop wideband) | ❌ Pending above |

---

## References

- NXP M68HC11 Reference Manual Rev 6.1 — full CPU, ADC, interrupt architecture
- HachiROM `PIN4_SENSOR_OPTIONS.md` — sensor wiring, table layout, ROM addresses
- HachiROM `hachirom/roms.py` — `ROM_266D` and `ROM_266B` confirmed map addresses
- 034 Motorsport AAN/ABY decompile (UrROM corpus) — example of what a fully
  RE'd ECU firmware corpus looks like; same workflow applies to M68HC11
