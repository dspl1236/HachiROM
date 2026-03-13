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
sensor contains an internal CO pot whose wiper feeds a voltage (approximately
1.0–7.5 V within a 0–5 V ADC window) back to the ECU on pin 4.  The ECU uses
this at idle only to apply a small lambda trim correction.

The Bosch 1.8T sensor has no CO pot.  Without intervention the ECU will:
- Store fault **00521** "CO-Poti Unterbrechung oder Kurzschluss" on every key cycle
- Apply an unpredictable idle trim based on whatever voltage appears on pin 4

**Recommended fix: ROM patch (HachiROM CO Pot button)**

Use the **CO Pot** button in HachiROM to apply the CO pot disable patch.
This widens the fault thresholds to 0–5 V and zeros the trim gain — pin 4 can
be left **unconnected** without any fault code or fuelling effect.

Patch bytes written:

| Address  | Stock value | Patched value | Effect                          |
|----------|-------------|---------------|---------------------------------|
| `0x0762` | `0x0A` (10) | `0x00` (0)    | Low fault threshold → 0 V       |
| `0x0763` | `0xEE` (238)| `0xFF` (255)  | High fault threshold → 5 V      |
| `0x0779` | `0x04` (4)  | `0x00` (0)    | Trim gain zeroed → no effect    |

No external hardware required when this patch is applied.

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

Adjust the wiper to produce a voltage within the ECU's valid window
(approximately 0.20–4.67 V measured at pin 4) to avoid fault 00521.
This replicates the original CO pot behaviour and allows idle trim adjustment.

---

## ROM Patches Required by Configuration

| Configuration             | MAF axis patch | CO pot patch |
|---------------------------|---------------|--------------|
| Stock 7A / 50 mm          | none          | none         |
| AAH V6 housing + 7A sensor| ✓ required    | none         |
| 1.8T sensor (any housing) | ✓ required    | ✓ required   |

Both patches are applied via HachiROM and are independently reversible.
Apply the MAF patch first, then the CO pot patch, then save and burn the ROM.
