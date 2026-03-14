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
cycle it compares the ADC reading against a neutral target and applies a small
fuel trim proportional to the deviation.  Five scalars in the ROM control this
behaviour:

| Address  | Name           | Stock value   | Role |
|----------|----------------|---------------|------|
| `0x0762` | Low threshold  | `0x0A` (10)   | ADC counts below this → fault 00521 (open circuit) |
| `0x0763` | High threshold | `0xEE` (238)  | ADC counts above this → fault 00521 (short circuit) |
| `0x0777` | Neutral target | `0x80` (128)  | ADC midpoint = no trim (pot centred ≈ 2.5 V) |
| `0x0778` | Window         | `0x32` (50)   | Trim only active within ±50 counts of neutral |
| `0x0779` | Gain           | `0x04` (4)    | Fuel trim applied per ADC count of deviation |

The trim loop runs approximately:

```
deviation = adc_pin4 - neutral_target        // signed, range ±50
if |deviation| <= window:
    fuel_trim += deviation * gain            // small correction each idle cycle
```

With the stock pot centred at `0x80` (128 ADC counts ≈ 2.5 V), deviation is
zero and no trim is applied.  A technician turning the pot shifts the wiper
voltage and the ECU richens or leans the idle mixture accordingly.

If the pot is **missing, disconnected, disturbed, or replaced by a 3-wire
sensor**, pin 4 floats to an unpredictable voltage.  The ECU then either:
- Triggers fault **00521** `CO-Poti Unterbrechung oder Kurzschluss` if the
  voltage falls outside the `0x0762`–`0x0763` window
- Applies a continuous non-zero trim if the voltage lands inside the window
  but away from neutral — causing hunting, rough idle, and exhaust popping
  on overrun as the ECU fights its own fuel map

---

#### The ROM patch — three bytes, full effect

The CO pot disable patch works by attacking all three pathways simultaneously:

**1. Widen the fault thresholds to the full ADC range**

```
0x0762: 0x0A → 0x00   (low threshold: 0.20 V → 0 V)
0x0763: 0xEE → 0xFF   (high threshold: 4.67 V → 5 V)
```

This tells the ECU that any voltage on pin 4 is "valid" — the full 0–5 V
range is within spec.  Fault 00521 cannot fire regardless of what pin 4 sees,
including a completely floating or open-circuit input.

**2. Zero the trim gain**

```
0x0779: 0x04 → 0x00   (gain: 4 → 0)
```

With gain = 0, the trim calculation produces zero output regardless of
deviation from neutral.  Even if pin 4 has a voltage and the ECU reads it,
the result multiplied by zero is zero — no fuelling effect whatsoever.

The neutral target (`0x0777 = 0x80`) and window (`0x0778 = 0x32`) are left
unchanged.  With gain = 0 they are mathematically irrelevant, but leaving them
at stock values makes the patch cleaner to detect and easier to reverse.

**Net result:** pin 4 is electrically inert.  Leave it unconnected.  The ECU
reads it, calculates a deviation, multiplies by zero, and moves on.  No fault,
no trim, no interaction with the fuel map.

---

#### Confirming the patch is applied

In HachiROM, open the **⚙ Scalars** tab after patching and verify:

| Address  | Patched value |
|----------|---------------|
| `0x0762` | `0x00` (0)    |
| `0x0763` | `0xFF` (255)  |
| `0x0779` | `0x00` (0)    |

The **Hardware tab → CO Pot** section shows `patched` when all three bytes are
at their patched values, `stock` when restored to stock, and `unknown` if any
byte is at a non-standard value.

---

**Applying the patch: HachiROM Hardware tab → CO Pot**

Open the ROM in HachiROM, go to the **Hardware** tab, and click
**Change CO Pot State…** → select **Disabled**.  Save and burn.  Pin 4 can
then be left **unconnected** with no fault code or fuelling effect.

No external hardware required.

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
