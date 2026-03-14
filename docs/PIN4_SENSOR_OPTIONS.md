# Pin 4 — Freed ADC Input Options

When the CO pot disable patch is applied, ECU pin 4 (MAF connector) becomes
an electrically inert input — the ADC still samples it every cycle but the
gain is zeroed so the reading has no effect on fuelling.

**Availability depends on MAF configuration:**

| MAF setup | Pin 4 status | Free for use? |
|-----------|-------------|---------------|
| Stock 7A sensor (054 133 471) | CO pot wiper — in use | Only if CO pot patch applied |
| AAH V6 housing + 7A sensor transplant | CO pot wiper — in use | Only if CO pot patch applied |
| AAH V6 3-wire sensor (078 133 471) | No connection | ✓ Always free |
| Bosch 1.8T (4-pin AEB) | No CO pot | ✓ Always free (patch required) |
| Bosch 1.8T (5-pin ATW/AWM) | No CO pot | ✓ Always free (patch required) |

---

## Option A — External data logging (Teensy)

The simplest use: tap pin 4 before the ECU and feed it to a Teensy analog
input. The ECU remains unaware. No ROM changes needed beyond the CO pot patch.

**Useful for:**
- Wideband O2 (0–5V analog output from Innovate LC-2, AEM UEGO etc)
- Boost pressure (MAP sensor 0–5V absolute)
- IAT from an integrated sensor (e.g. 1.8T 5-pin MAF)

The Teensy can log pin 4 voltage alongside the active map slot, RPM, and
any other channels — giving a data stream tied directly to ECU operation.

---

## Option B — ROM correction tables

Pin 4 feeds the CO pot ADC in the ECU firmware. With the gain zeroed the
value is read but ignored. **If** the firmware code that reads this ADC value
can be identified and redirected, it becomes a real ECU input.

This is speculative until the firmware is disassembled — but the groundwork
is: the ADC is 8-bit (0–5V maps to 0–255 counts), and the following table
sizes are viable within available ROM free space:

### ADC resolution

| Sensor | Output range | 16-point axis res | 32-point axis res |
|--------|-------------|-------------------|-------------------|
| Wideband (Innovate LC-2) | 0V=7.4→5V=22.4 AFR | 0.94 AFR/step | 0.47 AFR/step |
| Wideband (AEM UEGO) | 0V=8.5→5V=18.0 AFR | 0.59 AFR/step | 0.30 AFR/step |
| MAP sensor (0–5V abs) | 0–2 bar absolute | 0.31 psi/step | 0.15 psi/step |
| IAT NTC | -20°C→+100°C | ~7°C/step | ~3.5°C/step |

### Table size options

| Table type | Size | Use case |
|-----------|------|---------|
| 1D correction curve | 16 bytes | Simple sensor trim (IAT correction) |
| 1D correction curve | 32 bytes | Higher resolution trim |
| 2D map (sensor × RPM) | 256 bytes | Wideband feedback or boost vs RPM |
| 2D map (sensor × load) | 256 bytes | MAP load axis replacement |
| 2D map (sensor × RPM, 32-col) | 512 bytes | High-res wideband correction |

### ROM free space (266D physical)

Total available (0xFF regions ≥16 bytes): **2195 bytes**

| Block | Size | Notes |
|-------|------|-------|
| `0x133E–0x17FF` | 1218 bytes | Largest — fits a 256-byte 2D map + axes |
| `0x1E87–0x1FFF` | 377 bytes | Second largest |
| `0x7CC3–0x7DFF` | 317 bytes | Near top of ROM |
| `0x1270–0x12FF` | 144 bytes | Small — 1D tables only |

A 2D 16×16 correction map (256 bytes) + two 16-byte axes (32 bytes) = **288 bytes**
— fits comfortably in the `0x133E` block with room to spare.

---

## Option C — MAP sensor as load axis replacement

The most significant possible use: replace the MAF-derived load axis with
a real MAP sensor reading. The 266D currently derives load from MAF ADC
counts. A MAP sensor on pin 4 would allow the ECU to use manifold pressure
directly as the load index — identical in concept to how the AAH/MMS100
ECU works natively.

This requires firmware-level changes (redirecting which ADC channel feeds
the load calculation) and is not currently implemented. Documented here
as a future research direction.

---

## Implementation in HachiROM (planned)

The Hardware tab → MAF SENSOR section will be extended with a
**Pin 4 Use** dropdown, available when a no-CO-pot sensor is selected:

| Selection | Effect |
|-----------|--------|
| Unconnected (default) | CO pot patch applied, pin 4 ignored |
| Wideband logging | Documents wiring for Teensy ADC tap |
| MAP sensor logging | Documents wiring for Teensy ADC tap |
| IAT logging | Documents wiring + NTC curve for Teensy |
| MAP load axis (experimental) | Placeholder — firmware work required |

Logging options require no ROM changes — they are purely hardware/wiring
guidance. The ROM correction table options will be added as they are
verified against live ECU behaviour.
