# M68HC11 Firmware Reverse Engineering Reference
# Hitachi MMS-05C / MMS-04B — 7A 20v ECU (893 906 266D / 266B)

This document collects the M68HC11 architectural knowledge needed to reverse
engineer the 7A ECU firmware, trace the CO pot ADC read, and implement the
pin 4 correction loop patch described in PIN4_SENSOR_OPTIONS.md.

**Primary reference:** NXP/Freescale M68HC11 Reference Manual Rev 6.1
`https://www.nxp.com/docs/en/reference-manual/M68HC11RM.pdf`

---

## Tooling

Three options exist, from free/DOS to professional. All are valid for
the 266D work — they produce the same disassembly, just with different
workflows and ergonomics.

### Option 1 — DHC11 + ASHC11 (recommended starting point, free, DOS)

**DHC11** is a code-seeking disassembler for the M68HC11 family.
**ASHC11** is the companion macro assembler. Both by Peter Gargano,
available from `https://www.techedge.com.au/utils/dhc11.htm`

This is the tool used by the automotive ECU RE community (GM ECMs,
Subaru, etc.) for M68HC11 work. It runs in DOSBox on any modern OS.

**Why DHC11 is particularly good for ECU ROMs:**

The **code-seeking** algorithm is the critical feature. It starts from
declared entry points (reset vector, interrupt vectors) and follows every
branch and call target, marking code vs data automatically over multiple
passes. For an ECU ROM with many calibration tables interspersed with
code, this prevents the garbage output you get from linear disassemblers
that decode data bytes as instructions.

The **configuration file** lets you pre-seed all known labels, equates,
entry points, data table ranges, and indirect vector tables before
running. The disassembly comes back with meaningful names already
substituted throughout. For the 266D, you pre-declare all the I/O
register addresses, the interrupt vectors, and the known calibration
table addresses from HachiROM's `roms.py`.

The **round-trip reassembly** is the verification step. ASHC11 reassembles
DHC11 output back to binary; diff against original. If they match, the
disassembly is complete and any patch written in ASHC11 source can be
verified before burning.

**DOSBox setup:**
```
1. Install DOSBox (dosbox.com or dosbox-x for better Windows integration)
2. Mount a working directory:  mount c c:\hc11work
3. Copy DHC11.EXE, ASHC11.EXE, and the 266D ROM binary into c:\hc11work
4. Run: DHC11 266D.CFG
```

**266D configuration file template (266D.CFG):**
```
; DHC11 configuration for 893906266D / MMS-05C
; Load 32KB working half at $8000
INPUT   266D_stock.bin
OUTPUT  266D_disasm.asm
LOAD    $8000
ADDRESSES
OPCODES

; ── Reset and interrupt entry points ────────────────────────────────
ENTRY   $8000   RESET_HANDLER           ; actual address read from $FFFE:FF
VECTORS $FFD6   10  INT_VECTORS         ; full interrupt vector table
ENTRY   $FFFE   RESET_VECTOR            ; declare reset vector itself

; ── Known I/O register equates (M68HC11 internal, $1000 base) ───────
LABEL   $1030   ADCTL                   ; ADC control register
LABEL   $1031   ADR1                    ; ADC result 1
LABEL   $1032   ADR2                    ; ADC result 2
LABEL   $1033   ADR3                    ; ADC result 3
LABEL   $1034   ADR4                    ; ADC result 4
LABEL   $1024   SPCR                    ; SPI control
LABEL   $102B   BAUD                    ; SCI baud rate
LABEL   $102C   SCCR1                   ; SCI control 1
LABEL   $102D   SCCR2                   ; SCI control 2
LABEL   $102E   SCSR                    ; SCI status
LABEL   $102F   SCDR                    ; SCI data
LABEL   $1022   TMSK1                   ; Timer mask 1
LABEL   $1023   TFLG1                   ; Timer flag 1
LABEL   $1024   TMSK2                   ; Timer mask 2
LABEL   $1025   TFLG2                   ; Timer flag 2

; ── Known calibration tables (from HachiROM roms.py, 266D) ──────────
; Addresses relative to EPROM base $8000
LABEL   $8000   FUEL_MAP                ; 16x16 fuel map (0x0000 in ROM)
LABEL   $8100   IGN_MAP_1               ; ignition map 1
LABEL   $82DB   IGN_MAP_2               ; etc.
LABEL   $9E87   PIN4_LINEARISE_TABLE    ; safe block — Teensy/pin4 table
LABEL   $9EC7   PIN4_SENSOR_TYPE        ; sensor type byte

; ── Known data table ranges (prevents code-seeking into them) ────────
BYTES   $8000   256     FUEL_MAP_DATA
BYTES   $8100   256     IGN_MAP_1_DATA

; ── Indirect vector table ────────────────────────────────────────────
VECTORS $FFD6   16      INT_VEC
```

**To refine the config iteratively:**
1. First pass: only declare reset vector and interrupt vectors
2. Run DHC11, review output — data bytes decoded as instructions signal
   undeclared entry points or table ranges
3. Add `BYTES` declarations for identified tables, `ENTRY` for any missed
   subroutines, re-run
4. Each pass improves the output; repeat until reassembly matches original

---

### Option 2 — IDA Pro (professional, paid)

IDA Pro has a native **6811 processor module** documented at:
`https://docs.hex-rays.com/user-guide/disassembler/disassembly-gallery/6811-disassembler`

IDA is the industry-standard tool for firmware RE — it has a persistent
database, cross-references, struct definitions, scripting, and the
Hex-Rays decompiler. The 6811 module supports all M68HC11 variants.

**Workflow for 266D in IDA:**
1. File → New, select processor: `68HC11` (6811 module)
2. Load binary, set ROM base to `$8000`
3. IDA auto-detects reset vector from `$FFFE:FF` and starts analysis
4. Use Names window to define I/O register equates (same list as DHC11 above)
5. Mark known data tables as `db` arrays to prevent code analysis into them
6. Use `Alt+K` (change stack pointer) annotations at ISR entry/exit points

IDA's cross-reference system (`X` key on any address) is where it pulls
ahead of DHC11 — you can instantly see every place `ADCTL` (`$1030`) is
written to across the entire firmware, finding all ADC reads in one step
rather than manually searching.

IDA Free (version 8.x) supports 6811 but without decompiler and with
database size limits. For a 32KB ECU ROM it should be sufficient.

---

### Option 3 — Ghidra (free, modern)

NSA's Ghidra has a 6811 processor module available via the community
plugin `ghidra-mc6811` (search GitHub). Less mature than IDA for this
architecture but free, open-source, and scriptable in Java/Python.
Reasonable choice if IDA cost is prohibitive.

---

## CPU Architecture Overview

The M68HC11 is an 8-bit CPU with the following programmer-visible registers:

| Register | Width | Purpose |
|----------|-------|---------|
| A | 8-bit | Accumulator A — primary for byte operations |
| B | 8-bit | Accumulator B — secondary |
| D | 16-bit | Double accumulator (A:B concatenated) |
| X | 16-bit | Index register X — table lookups |
| Y | 16-bit | Index register Y — table lookups |
| SP | 16-bit | Stack pointer |
| PC | 16-bit | Program counter |
| CCR | 8-bit | Condition code register (N, Z, V, C, H, I, X, S bits) |

The 7A ECU runs the M68HC11 in **expanded multiplexed mode** — Port B
carries the high address byte (A8–A15), Port C is the multiplexed low
address / data bus (AD0–AD7), and the AS (address strobe) pin
demultiplexes them. The Teensy EPROM emulator sits on this bus and
answers fetch cycles from the external address space ($8000–$FFFF).

---

## Addressing Modes — Table Lookup Patterns

Table lookups follow a highly recognisable pattern in M68HC11 assembly.
Identifying these unlocks every calibration table in the firmware.

### Standard indexed lookup:
```asm
LDX  #$xxxx        ; Load table base address into X
LDAA $00,X         ; Load byte at X+offset into A
```

### Computed offset (most common for 2D map lookup):
```asm
LDX  #$xxxx        ; Table base
ABX                ; X = X + B  (B holds row×cols + col index)
LDAA $00,X         ; Read table cell
```

### Two-register 2D lookup:
```asm
LDX  #table_base
ABX                ; add row offset
LDY  $00,X         ; load column pointer or value
```

The CO pot ADC result will be used as a computed index or multiplier
feeding into the fuel trim path. Look for `LDAB`/`LDAA` reading `ADR1`
(`$1031`), followed immediately by one of these patterns.

---

## ADC System (Reference Manual Section 12)

### Control and result registers (internal I/O, base `$1000`):

| Register | Address | Function |
|----------|---------|----------|
| ADCTL | `$1030` | ADC control — starts conversion, selects channel |
| ADR1  | `$1031` | Conversion result 1 |
| ADR2  | `$1032` | Conversion result 2 |
| ADR3  | `$1033` | Conversion result 3 |
| ADR4  | `$1034` | Conversion result 4 |

### ADCTL register bits:

| Bit | Name | Function |
|-----|------|----------|
| 7 | CCF | Conversion complete flag (set when done, read-only) |
| 5 | SCAN | 0=single conversion, 1=continuous |
| 4 | MULT | 0=4 samples on one channel, 1=4 channels in sequence |
| 3:0 | CD:CA | Channel select (0–7 = PE0–PE7) |

### Typical ADC read sequence in firmware:
```asm
LDAA  #$xx          ; Channel select (CO pot channel bits in CD:CA)
STAA  $1030         ; Write ADCTL — initiates conversion
; ... wait loop or poll ...
LDAA  $1030         ; Read ADCTL
BPL   *-3           ; Branch if CCF clear (bit 7 = 0 = not done); loop
LDAA  $1031         ; Read ADR1 — 8-bit result (0x00–0xFF = 0–5V)
```

The specific CO pot channel number needs to be determined from the firmware
trace — it's the ADCTL write that eventually feeds a fuel trim calculation.

**Finding all ADC reads quickly:**
- DHC11: text-search output for `STAA  $1030` or `STAA  ADCTL`
- IDA: right-click `$1030` → List cross references → filter for writes

---

## Interrupt Architecture (Reference Manual Section 5)

The main fuel calculation almost certainly runs inside a **timer output
compare interrupt** firing on each crank/cam signal or at a fixed rate.

### Interrupt vector table (top of 64KB space, always at these addresses):

| Vector addr | Source | Priority |
|------------|--------|----------|
| `$FFD6:D7` | SCI (serial) | |
| `$FFD8:D9` | SPI transfer complete | |
| `$FFDA:DB` | Pulse accumulator input edge | |
| `$FFDC:DD` | Pulse accumulator overflow | |
| `$FFDE:DF` | Timer overflow | |
| `$FFE0:E1` | Output compare 5 | |
| `$FFE2:E3` | Output compare 4 | |
| `$FFE4:E5` | Output compare 3 | |
| `$FFE6:E7` | Output compare 2 | |
| `$FFE8:E9` | Output compare 1 | ← likely fuel ISR |
| `$FFEA:EB` | Input capture 3 | |
| `$FFEC:ED` | Input capture 2 | |
| `$FFEE:EF` | Input capture 1 | |
| `$FFF0:F1` | Real-time interrupt | |
| `$FFF2:F3` | IRQ (external) | |
| `$FFF4:F5` | XIRQ (non-maskable) | |
| `$FFF6:F7` | SWI (software interrupt) | |
| `$FFF8:F9` | Illegal opcode | |
| `$FFFA:FB` | COP failure | |
| `$FFFC:FD` | Clock monitor fail | |
| `$FFFE:FF` | **RESET** ← start here | |

**Read `$FFFE:FF` first** to get the firmware entry point (boot code).
Then declare all vectors above as entry points in your DHC11 config or
IDA analysis. The OC1 vector (`$FFE8:E9`) is the most likely fuel ISR.

### ISR identification in disassembly:
- Regular subroutines end with `RTS` (return from subroutine)
- ISRs end with `RTI` (return from interrupt — restores full register state)
- M68HC11 auto-stacks: CCR, B, A, X, Y, PC on interrupt entry
- No explicit prologue needed; look for `RTI` to find ISR boundaries

---

## The CO Pot Trim Loop — Finding and Patching

### What to find:

1. **The ADC channel** — which bits in the ADCTL write select the CO pot
   (MAF pin 4 → ECU ADC input). Find by searching for ADCTL writes and
   tracing which one's result feeds a fuel correction path.

2. **The trim calculation** — after the ADC read, there will be a scaling
   sequence: typically a `MUL` (A×B → D), `ADDD`, or signed add producing
   a pulsewidth correction delta.

3. **The application point** — where the correction delta is added to or
   subtracted from the base injection pulsewidth value.

### Patch Option A — Firmware patch (cleanest, needs M68HC11 assembly):

Replace the ADC read with a table lookup into the Teensy-maintained
correction table at ROM address `$9E87` (absolute). The ECU reads the
table instead of raw ADC. The Teensy updates the table based on whatever
sensor is on pin 4 (wideband AFR, MAP, IAT).

```asm
; BEFORE (stock CO pot read):
LDAA  #$04          ; (example) select CO pot channel
STAA  ADCTL
@wait: LDAA ADCTL
BPL   @wait
LDAA  ADR1          ; raw CO pot ADC value (0-255)
; ... scale and apply trim ...

; AFTER (Teensy correction table lookup):
LDX   #$9E97        ; correction value axis in safe block
LDAB  LOAD_INDEX    ; current load index (0-15, from existing fuel calc)
ABX
LDAA  $00,X         ; correction value from Teensy-updated table
; ... same scale and apply path as before ...
```

The Teensy watches the address bus. When pin 4 has a wideband reading, it
calculates which load cell the engine is in and updates `$9E97+index`
with the appropriate trim value each cycle. The ECU reads it as if it
were static ROM data.

### Patch Option B — Teensy bus intercept (no firmware change):

Identify a ROM address the ECU reads frequently during the fuel loop —
ideally a scalar or small table whose value directly scales injection.
The Teensy monitors for that address on the bus and substitutes a
dynamically calculated value on the fly.

Requires knowing timing constraints of the M68HC11 bus cycle
(address valid → data required in ~200ns at 2MHz E-clock) — the Teensy
4.1 at 600MHz has plenty of headroom for this.

More brittle than Option A but requires zero firmware modification.

---

## Memory Map (Expanded Mode, 266D / MMS-05C)

| Address Range | Size | Contents |
|---------------|------|----------|
| `$0000–$00FF` | 256B | Internal direct-page RAM (fast 1-byte addressing) |
| `$0100–$0FFF` | ~3.8KB | External SRAM (ECU board) |
| `$1000–$103F` | 64B | Internal I/O registers (overlaid) |
| `$1040–$7FFF` | ~28KB | External SRAM / unmapped |
| `$8000–$FFFF` | 32KB | External EPROM (MMS-05C / Teensy emulator) |

The EPROM occupies the top 32KB. All firmware code and calibration tables
live here. The safe block at `$9E87–$9EC9` (HachiROM confirmed: 100% 0xFF,
zero code references in both 266D and 266B firmware) is where the
Teensy-readable sensor table is written.

**Safe block absolute address:** `$9E87` = EPROM offset `$1E87` from `$8000`

---

## Bootstrap Mode (Reference Manual Section 3.7.4)

Activated by holding MODA and MODB low at reset. CPU loads a small
program via SCI (serial) at 1200 baud into internal RAM and executes it.

Not directly useful for 266D ECU testing (firmware runs from external
EPROM in expanded mode, not internal ROM). The **Teensy emulator is the
practical test vehicle** — update the served image and the ECU sees new
code on next startup without a physical EPROM burn.

Bootstrap is documented here because:
- The SCI pin assignments (PD0=RxD, PD1=TxD) and baud calculation are
  the same in expanded mode, relevant if serial debug output is ever added
- The BUFFALO monitor (Motorola's 68HC11 development monitor) uses this
  mode — relevant background for anyone coming from HC11 development docs

---

## Practical Workflow: First RE Session

```
1. Get a clean 32KB working half of the 266D ROM
   (HachiROM normalize_rom() handles 64KB chip reads automatically)

2. Read reset vector: bytes at offset $7FFE:$7FFF = entry point
   e.g. if bytes are $A2, $00 → entry point is $A200 (absolute $A200)

3. Read all interrupt vectors: offsets $77D6–$7FFF
   List each non-zero pair as an ENTRY in the DHC11 config

4. Create 266D.CFG from the template above
   Fill in actual entry point address from step 2

5. Run: DHC11 266D.CFG
   Review output for areas where code/data boundary is wrong
   Add BYTES declarations for mis-decoded tables, re-run

6. Search output for "STAA  ADCTL" (or "STAA  $1030")
   There may be several — each is an ADC conversion
   For each one, trace forward to see what happens to the result

7. The CO pot trim loop will be the one whose result feeds:
   - A MUL instruction (multiply = scaling)
   - Then an ADDD or ADDA applying to a pulsewidth accumulator

8. Record the exact addresses. Update this document.
```

---

## Status

| Task | Status |
|------|--------|
| M68HC11 architecture documented | ✓ |
| ADC register map documented | ✓ |
| Interrupt vector table documented | ✓ |
| DHC11 + ASHC11 workflow documented | ✓ |
| IDA Pro 6811 workflow documented | ✓ |
| 266D.CFG template created | ✓ |
| CO pot ADC channel — specific channel | ❌ Needs firmware trace |
| CO pot trim loop — exact address range | ❌ Needs disassembly |
| Load index variable — RAM address | ❌ Needs firmware trace |
| Safe block at `$9E87` confirmed | ✓ (both 266D and 266B) |
| Teensy sensor table read implemented | ✓ (type byte + linearisation) |
| Option A firmware patch written | ❌ Pending CO pot RE |
| Option B Teensy intercept | ❌ Pending address identification |
| Live closed-loop wideband correction | ❌ Pending above |

---

## References

| Resource | URL / Location |
|----------|---------------|
| NXP M68HC11 Reference Manual Rev 6.1 | `https://www.nxp.com/docs/en/reference-manual/M68HC11RM.pdf` |
| DHC11 disassembler + ASHC11 assembler | `https://www.techedge.com.au/utils/dhc11.htm` |
| DHC11 tutorial | `https://www.techedge.com.au/utils/dhc11tut.htm` |
| IDA Pro 6811 processor module docs | `https://docs.hex-rays.com/user-guide/disassembler/disassembly-gallery/6811-disassembler` |
| pcmhacking.net — DHC11 ECU RE thread | `https://pcmhacking.net/forums/viewtopic.php?t=1573` |
| HachiROM PIN4_SENSOR_OPTIONS.md | `docs/PIN4_SENSOR_OPTIONS.md` |
| HachiROM roms.py — confirmed map addresses | `hachirom/roms.py` ROM_266D / ROM_266B |
