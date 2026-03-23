# MAF Sensor Wiring — 7A ECU (266D / 266B)

This document covers wiring for the three supported MAF sensor configurations
on the 7A 20v ECU.  All changes described here are made at the **MAF connector
pigtail only** — no ECU-side wiring changes are required.

---

## Stock Configuration (no changes)

**Sensor:** Hitachi 054 133 471 / A  
**Housing:** 50 mm stock housing  
**Connector:** 4-pin  
**ROM profile:** `stock_7a`

| Pin | Wire   | Function                        |
|-----|--------|---------------------------------|
| 1   | —      | MAF signal output → ECU input   |
| 2   | —      | Ground                          |
| 3   | —      | +12 V supply                    |
| 4   | —      | CO pot wiper output → ECU input |

No wiring changes.  No ROM patch required.

---

## AAH V6 Housing + 7A Sensor Transplant

**Sensor:** Hitachi 054 133 471 A (with Index A)  
**Housing:** 078 133 471 (no suffix — Index A/AX are incompatible, different bolt pattern)  
**Connector:** 4-pin — unchanged from stock  
**ROM profile:** `aah_v6_housing`

The 7A sensor unit (element + CO pot assembly) is physically moved into the
larger 74 mm AAH V6 housing.  The 4-pin connector, all four wires, and the CO
pot are retained exactly as stock.

**No wiring changes whatsoever.**

ROM patch required — apply the `aah_v6_housing` profile in HachiROM to rescale
the MAF axis for the larger bore.  Without the ROM patch the ECU will read low
airflow and run rich.

> **Housing compatibility note:**  
> `078 133 471` (no suffix) — correct, mounting holes match  
> `078 133 471 A` / `078 133 471 AX` — **incompatible**, mirrored holes, different sensor depth  
> `054 133 471 A` (with Index A) fits directly  
> `054 133 471` (without Index A) fits with shim washers

---

## AAH V6 Housing + AAH Sensor (3-wire, direct fit)

**Sensor:** AAH V6 stock sensor — 078 133 471 (no suffix)  
**Housing:** Same unit — sensor and housing are one assembly  
**Connector:** 3-pin  
**ROM profile:** `aah_v6_3wire`

The AAH V6 stock MAF sensor uses the same Hitachi hot-wire element in the same
74mm housing as the 7A transplant mod above. The difference is the connector:
the AAH ECU handles idle trim via self-learning so the 4th CO pot wire was
removed — the sensor is 3-pin only.

Because the element and housing are identical, the MAF axis is the same as
`aah_v6_housing`. Only the connector pinout and CO pot handling differ.

**Source:** 20v-sauger-tuning.de — explicitly confirms same element family.

| AAH sensor pin | Function                  | → 7A ECU pin |
|----------------|---------------------------|--------------|
| 1              | MAF signal output → ECU   | 1            |
| 2              | Ground                    | 2            |
| 3              | +12V supply               | 3            |
| —              | (no pin 4)                | 4 → apply CO pot ROM patch, leave open |

No CO pot is present. Apply the **CO Pot disable patch** in HachiROM to
suppress fault 00521 and leave ECU pin 4 unconnected.

> **Part number note:**  
> `078 133 471` (no suffix) — correct  
> `078 133 471 A` / `078 133 471 AX` — **not this sensor**, different connector/housing revision

---



> **Warning:** The MAF axis values for both 1.8T profiles are derived from
> transfer function data and bore area calculations.  They have not been
> verified on a running engine.  Always validate fuelling with a wideband O2
> sensor before road use.

**Sensor:** Bosch 0280218114  
**Available housings:**
- 60 mm stock 1.8T housing → ROM profile `sensor_1_8t_60`
- 69.85 mm VR6 / TT225 housing (Bosch 0280218042 / 0280218116) → ROM profile `sensor_1_8t_vr6`

### Connector variants

The Bosch 1.8T sensor was used across several VAG engines with two different
connector types.  Identify which variant you have before wiring.

**AEB engine — 4-pin rectangular connector**

| 1.8T Pin | Function                        |
|----------|---------------------------------|
| 1        | Ground                          |
| 2        | Signal ground → ECU             |
| 3        | +12 V supply                    |
| 4        | MAF signal output → ECU         |

No integrated IAT on the AEB variant.

**ATW / AUG / AWM engines — 5-pin round connector**

| 1.8T Pin | Function                                       |
|----------|------------------------------------------------|
| 1        | IAT signal output (not used — leave open)      |
| 2        | +12 V supply                                   |
| 3        | Signal ground → ECU                            |
| 4        | 5 V reference for IAT (not used — leave open)  |
| 5        | MAF signal output → ECU                        |

The 5-pin sensor contains an integrated IAT (intake air temperature) sensor on
pins 1 and 4.  The 7A ECU has no IAT input — it uses internal temperature
compensation inside the MAF element.  **Leave pins 1 and 4 unconnected.**
Only three wires are needed.

---

### Conversion wiring — 5-pin ATW/AUG/AWM sensor to 7A ECU

Build a new pigtail at the MAF connector.  The 7A ECU connector remains
untouched.

| 7A ECU pin | Function         | → | 1.8T sensor pin |
|------------|------------------|---|-----------------|
| 3          | +12 V supply     | → | Pin 2           |
| 2          | Ground           | → | Pin 3           |
| 1          | MAF signal       | → | Pin 5           |
| 4          | CO pot input     | → | see below       |
| —          | IAT 5 V ref      |   | Pin 4 — **leave open** |
| —          | IAT signal       |   | Pin 1 — **leave open** |

### Conversion wiring — 4-pin AEB sensor to 7A ECU

| 7A ECU pin | Function         | → | 1.8T sensor pin |
|------------|------------------|---|-----------------|
| 3          | +12 V supply     | → | Pin 3           |
| 2          | Ground           | → | Pin 1           |
| 1          | MAF signal       | → | Pin 4           |
| 4          | CO pot input     | → | see below       |

---

### CO pot — pin 4 (applies to all no-pot sensor conversions)

Pin 4 on the 7A MAF connector is an **input to the ECU**.  The stock Hitachi
sensor contains an internal CO pot whose wiper feeds a voltage back to the ECU
on pin 4.  The ECU uses this at idle only to apply a small lambda trim
correction — it was an emissions adjustment tool so a technician could turn the
pot during an annual inspection to make the car pass the CO exhaust test.

---

#### What the ECU does with pin 4

The ECU reads pin 4 via an 8-bit ADC (0 V = 0, 5 V = 255).  On every idle
cycle it compares the ADC reading against a baseline and applies a small
fuel trim proportional to the deviation.  If the pot is **missing,
disconnected, disturbed, or replaced by a 3-wire sensor**, pin 4 floats to an
unpredictable voltage.  The ECU then either:
- Triggers fault **00521** `CO-Poti Unterbrechung oder Kurzschluss`
- Applies a continuous non-zero trim if the voltage lands in an active
  range — causing hunting, rough idle, and exhaust popping on overrun as the
  ECU fights its own fuel map

---

#### The ROM patch — instruction redirect (confirmed on-car)

The CO pot disable patch works by redirecting the ECU's fuel trim calculation
to produce zero output on every cycle, regardless of what pin 4 reads.

**How the ECU uses pin 4 (M68HC11 disassembly):**

The ECU reads pin 4 via ADC channel 8 and stores the result to a RAM location.
Once per idle cycle it runs this trim calculation:

```
266D (MMS-05C):                      266B (MMS-04B):
  $A348  LDAA $16F4  ; CO pot ADC      $A3A4  LDAA $42F4  ; CO pot ADC
  $A34B  SUBA $149D  ; delta=pot-ch0   $A3A7  SUBA $409D  ; delta=pot-ch0
  $A34E  BHS  +1     ; clamp ≥ 0       $A3AA  BHS  +1     ; clamp ≥ 0
  $A350  CLRA        ;                  $A3AC  CLRA        ;
```

The LDAA loads the CO pot ADC result.  The SUBA subtracts a baseline channel
reading (ch0).  The delta feeds downstream trim logic that adjusts fuelling.

**The patch:** redirect the LDAA to load ch0 instead of the CO pot:

```
266D: LDAA $16F4 → LDAA $149D   (file bytes 0x2349-0x234A: 0x16,0xF4 → 0x14,0x9D)
266B: LDAA $42F4 → LDAA $409D   (file bytes 0x23A5-0x23A6: 0x42,0xF4 → 0x40,0x9D)
```

Now SUBA computes (ch0 − ch0) = 0 on every cycle.  The CO pot ADC still runs
but its result is never read by the fuel path.  Pin 4 can float, be
disconnected, or be connected — doesn't matter.  No fault, no trim, no
interaction with the fuel map.

**Checksum:** The ECU validates `sum(all 32,768 bytes) mod 256 = 0` at startup.
HachiROM applies checksum correction automatically on every save — no manual
step required.  This was confirmed on-car: a patched ROM without checksum
correction causes the engine to die under throttle application.

> **History note (March 2026):** An earlier version of this patch targeted
> calibration scalars at 0x0762, 0x0763, and 0x0779 — widening fault thresholds
> and zeroing a "gain" byte.  This was **wrong**.  Those addresses are unrelated
> 16-bit calibration constants in the fuel/ignition path:
> - 0x0762–0x0763: loaded as a 16-bit word by `LDD $8762` (4 firmware refs)
> - 0x0779: subtraction operand in `SUBA $8779` (fuel calculation chain)
>
> Modifying them corrupts fuel delivery.  The instruction redirect above is the
> correct and only supported patch.

---

#### Confirming the patch is applied

In HachiROM, the **Hardware tab → CO Pot** section shows the patch state:

| State       | Meaning |
|-------------|---------|
| `patched`   | LDAA redirected to ch0 — CO pot disabled |
| `stock`     | LDAA reads CO pot ADC — CO pot active |
| `unknown`   | Bytes don't match either known state |

HachiROM auto-detects whether the loaded ROM is 266D or 266B and checks the
correct file offset for each variant.

---

**Applying the patch: HachiROM Hardware tab → CO Pot**

Open the ROM in HachiROM, go to the **Hardware** tab, and click
**Change CO Pot State…** → select **Disabled**.  Save and burn.  HachiROM
auto-detects 266D vs 266B and patches the correct file offset.  Checksum
correction is applied automatically on save.  Pin 4 can then be left
**unconnected** with no fault code or fuelling effect.

**Alternative: external adjustable pot (if ROM patch is not desired)**

Wire a 20 kΩ 10-turn precision pot (Reichelt 534-20K or equivalent):

```
Pin 3 (+12 V) ──┬── [pot pin 3]
                │
              [20 kΩ pot]
                │
              [pot wiper] ──── 7A ECU pin 4
                │
              [1 kΩ resistor]
                │
Pin 2 (GND) ────┘
```

Adjust the wiper to produce approximately 2.5 V at pin 4 (neutral = 128 ADC
counts) to centre the trim at zero and keep clear of both fault thresholds.

---

## ROM Patches Required by Configuration

| Configuration             | MAF axis patch | CO pot patch |
|---------------------------|---------------|--------------|
| Stock 7A / 50 mm          | none          | none         |
| AAH V6 housing + 7A sensor| ✓ required    | none         |
| 1.8T sensor (any housing) | ✓ required    | ✓ required   |

Both patches are applied via HachiROM and are independently reversible.
Apply the MAF patch first, then the CO pot patch, then save and burn the ROM.

---

## 7A Hardware Versions — MMS-04B vs MMS05C

The 7A engine was produced in two distinct hardware versions, split at the
March 1990 production date (3/90).  The ECU variant directly reflects this:

| Feature                  | Pre-3/90 — 266B (MMS-04B)         | Post-3/90 — 266D (MMS05C)         |
|--------------------------|------------------------------------|------------------------------------|
| ECU connector            | 2-plug                             | 4-plug                             |
| ISV (idle stabiliser)    | Rotary valve (old style)           | New style solenoid valve           |
| Exhaust manifold         | Tubular/fabricated (Fächerkrümmer) | Cast iron (Gusskrümmer)            |
| TPS connector            | 2-connector                        | Single central connector           |
| Evap purge solenoids     | 1 solenoid                         | 2 solenoids                        |
| MAF connector            | 4-pin (same sensor, same element)  | 4-pin (same sensor, same element)  |
| CO set procedure         | Manual — tester at exhaust probe   | VAG 1551 / VCDS measuring block 8  |
| Diagnostic bridge        | Required during CO setup (7/88–3/90)| Not required — VAG tool only      |

*Source: 20v-sauger-tuning.de — unterscheidungsmerkmale_mpi.htm,
grundeinstellung_bis_390.htm, grundeinstellung_ab_390.htm*

### CO setting procedure — post-3/90 (266D / MMS05C)

The new-version CO procedure reads measuring block value 8 via VAG 1551 or
VCDS and adjusts the CO pot screw until the displayed value reaches **128**.

The ECU reports the current ADC reading on pin 4 as measuring block 8, and the
technician turns the pot until it matches the factory neutral target.  With the
screw centred at 128, the trim delta is zero and the fuel map runs unmodified.

This confirms why the CO pot patch works: with the LDAA redirected to load ch0,
the delta computation always returns zero — the trim path is inert regardless
of what pin 4 reads or what measuring block 8 reports.

### CO setting procedure — pre-3/90 (266B / MMS-04B)

The old-version procedure uses a separate exhaust CO analyser — there is no
VAG measuring block for CO on the 2-plug ECU.  Idle speed (screw 1 on throttle
body) and CO content (screw 2 on MAF) are set together manually, targeting
0.5–1.0 Vol.% CO at idle.  A diagnostic bridge must be jumpered at the
connector during setup on vehicles built between 7/88 and 3/90.
