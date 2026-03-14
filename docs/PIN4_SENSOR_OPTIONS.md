# Pin 4 — Freed ADC Input: Sensor Options & Patches

When the CO pot disable patch is applied, ECU pin 4 (MAF connector) becomes
a free 0–5V ADC input. The signal is still sampled every cycle but the gain
is zeroed, so it has no effect on fuelling.

HachiROM can write a linearisation table for the fitted sensor into a safe
free ROM block. This documents the sensor for the Teensy emulator and enables
future correction table support when firmware patches are implemented.

---

## Requirements

1. **CO pot patch must be applied first** — zeroes the gain so pin 4 has no
   fuelling effect regardless of voltage. Apply via Hardware tab → CO Pot.
2. **Sensor wired to MAF connector pin 4** — see wiring notes per sensor below.
3. **Teensy tap (optional)** — for active logging, also wire pin 4 to a Teensy
   analog input. The Teensy reads the sensor type from the ROM table automatically.
4. **ROM correction loop** — requires a future M68HC11 firmware patch to redirect
   the CO pot ADC read into a correction table. Not yet implemented.

---

## Supported Sensors

### Wideband O2

All controllers output a linear 0–5V signal. Wire analog output → MAF pin 4.

| Controller | Part | 0V AFR | 5V AFR | Stoich V | Stoich ADC |
|-----------|------|--------|--------|----------|-----------|
| Innovate LC-2 | 3877 | 7.35 | 22.39 | 2.43V | 124 |
| AEM UEGO | 30-0300 | 8.50 | 18.00 | 3.25V | 166 |
| Zeitronix ZT-3 | ZT-3 | 10.0 | 20.0 | 2.33V | 119 |

**Wiring:** `WB analog out → MAF pin 4`. Also tap to Teensy analog input for logging.

**Table encoding:** AFR × 10 stored as byte (e.g. 147 = 14.7 AFR).

---

### MAP Sensor (0–5V absolute)

| Sensor | Part | Range | Atm ADC | +1 bar ADC |
|--------|------|-------|---------|-----------|
| GM 1-bar | 12569240 | 10–105 kPa | 245 | N/A |
| GM 2-bar | 16040749 | 10–210 kPa | 116 | 243 |
| GM 3-bar | 12223861 | 10–315 kPa | 76 | 159 |
| Bosch 2.5-bar | 0261230036 | 10–250 kPa | 97 | 203 |

**Wiring:** `MAP signal → pin 4`. `MAP +5V → switched supply`. `MAP GND → chassis`.
Tee vacuum port into intake manifold.

**Table encoding:** kPa absolute stored as byte (1 count = 1 kPa).

---

### IAT Sensor — NTC Thermistor

Standard Bosch NTC (same family as 7A coolant sensor). Compatible with the
integrated IAT in 1.8T 5-pin MAF sensors (ATW/AUG/AWM — use MAF pins 1+4).

**Circuit:** `5V → 2.2kΩ resistor → MAF pin 4 → NTC → GND`

| Temp | ADC | | Temp | ADC |
|------|-----|-|------|-----|
| −40°C | 243 | | +40°C | 89 |
| −20°C | 223 | | +60°C | 54 |
|   0°C | 186 | | +80°C | 33 |
| +20°C | 136 | | +100°C | 20 |

**Table encoding:** (temp + 40) as byte. Decode: °C = byte − 40.

---

## ROM Table Layout

Written to `0x1E87–0x1EC8` — confirmed safe block (no code references,
377 bytes of 0xFF in the stock 266D ROM):

| Offset | Address | Size | Content |
|--------|---------|------|---------|
| +0x00 | 0x1E87 | 16 | ADC axis (shared): `[0,17,34,51…255]` |
| +0x10 | 0x1E97 | 16 | Sensor value axis (AFR×10 / kPa / temp+40) |
| +0x20 | 0x1EA7 | 16 | Second slot (future) |
| +0x30 | 0x1EB7 | 16 | Third slot (future) |
| +0x40 | 0x1EC7 | 1 | Sensor type: `0x00`=none `0x01`=WB `0x02`=MAP `0x03`=IAT `0xFF`=raw |
| +0x41 | 0x1EC8 | 1 | Sensor subtype index |
| +0x42 | 0x1EC9 | 311 | Reserved — future correction table |

The Teensy reads `0x1EC7` on startup to know what sensor is fitted and which
decode table to apply to the analog ADC reading on its input pin.

---

## Availability

| MAF setup | Pin 4 | CO pot patch needed |
|-----------|-------|---------------------|
| Stock 7A 4-pin (054 133 471) | CO pot wiper | Yes |
| 1.8T 4-pin (AEB) | Unused | Yes (to prevent fault) |
| 1.8T 5-pin (ATW/AWM) — integrated IAT | IAT signal | Yes |
| AAH V6 3-wire (078 133 471) | Unused | Yes (to prevent fault) |

---

## How to Apply in HachiROM

1. Open your ROM (Hardware tab)
2. Apply CO Pot patch if not already done
3. Under **PIN 4 — FREED ADC INPUT**, select your sensor from the dropdown
4. Click **Apply to ROM…** — writes linearisation table to 0x1E87
5. Save 27C512 and burn

The Overview tab ROM card will show the detected sensor after applying.
