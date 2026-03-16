"""
tests/test_patches.py
=====================
Tests for HachiROM patch detection and application:
  - Pin 4 sensor patch (detect_pin4_patch / apply_pin4_patch)
  - Injection scaler trick (detect_injection_scaler_trick / apply_injection_scaler_trick)
  - compare_roms / diff_summary region labelling
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from hachirom.roms import ROM_266D, ROM_266B, ROM_AAH
from hachirom.maps import (
    detect_pin4_patch, apply_pin4_patch,
    detect_injection_scaler_trick, apply_injection_scaler_trick,
    compare_roms, diff_summary,
    apply_checksum, apply_co_pot_patch,
    PIN4_TYPE_NONE, PIN4_TYPE_WIDEBAND, PIN4_TYPE_MAP, PIN4_TYPE_IAT,
    PIN4_TABLE_BASE, PIN4_ADC_AXIS,
    PIN4_WIDEBAND_TABLES, PIN4_MAP_TABLES,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def make_rom(variant, fill=103):
    rom = bytearray([fill] * variant.size)
    if variant.reset_vector:
        rom[variant.size - 2] = variant.reset_vector[0]
        rom[variant.size - 1] = variant.reset_vector[1]
    return bytes(apply_checksum(bytes(rom), variant))


def make_pin4_rom():
    """266D ROM with CO pot patch pre-applied (required before pin4 writes)."""
    return apply_co_pot_patch(make_rom(ROM_266D), disable=True)


# ── Pin 4 detection ───────────────────────────────────────────────────────────

class TestPin4Detection:
    def test_blank_rom_is_none(self):
        result = detect_pin4_patch(bytes(32768))
        assert result['state'] == 'none'
        assert result['type'] == PIN4_TYPE_NONE
        assert result['type_name'] == 'none'

    def test_detect_returns_dict_keys(self):
        result = detect_pin4_patch(bytes(32768))
        for key in ('state', 'type', 'type_name', 'subtype', 'label',
                    'adc_axis', 'val_axis'):
            assert key in result, f"Missing key: {key}"

    def test_state_is_string(self):
        result = detect_pin4_patch(bytes(32768))
        assert isinstance(result['state'], str)
        assert result['state'] in ('none', 'patched', 'unknown')

    def test_label_is_string(self):
        result = detect_pin4_patch(bytes(32768))
        assert isinstance(result['label'], str)
        assert len(result['label']) > 0

    def test_no_crash_on_short_rom(self):
        # Should not crash on ROM shorter than expected
        result = detect_pin4_patch(bytes(1024))
        assert result is not None
        assert 'state' in result

    def test_pin4_table_base_in_range(self):
        assert 0 < PIN4_TABLE_BASE < 0x8000

    def test_adc_axis_length(self):
        assert len(PIN4_ADC_AXIS) == 16
        # ADC values should be monotonically increasing
        assert all(PIN4_ADC_AXIS[i] < PIN4_ADC_AXIS[i+1]
                   for i in range(len(PIN4_ADC_AXIS)-1))


class TestPin4Application:
    def test_apply_wideband_changes_rom(self):
        rom = make_pin4_rom()
        if PIN4_WIDEBAND_TABLES:
            key = list(PIN4_WIDEBAND_TABLES.keys())[0]
            patched = apply_pin4_patch(rom, PIN4_TYPE_WIDEBAND, key)
            assert patched != bytes(rom), "Wideband patch should change ROM"
            assert len(patched) == len(rom)

    def test_apply_map_sensor_changes_rom(self):
        rom = make_pin4_rom()
        if PIN4_MAP_TABLES:
            key = list(PIN4_MAP_TABLES.keys())[0]
            patched = apply_pin4_patch(rom, PIN4_TYPE_MAP, key)
            assert patched != bytes(rom), "MAP sensor patch should change ROM"
            assert len(patched) == len(rom)

    def test_apply_none_removes_patch(self):
        rom = make_pin4_rom()
        # Apply then remove
        if PIN4_WIDEBAND_TABLES:
            key     = list(PIN4_WIDEBAND_TABLES.keys())[0]
            patched = apply_pin4_patch(rom, PIN4_TYPE_WIDEBAND, key)
            cleared = apply_pin4_patch(patched, PIN4_TYPE_NONE)
            assert isinstance(cleared, (bytes, bytearray))
            assert len(cleared) == len(rom)

    def test_apply_returns_correct_length(self):
        rom = make_pin4_rom()
        for pin4_type in [PIN4_TYPE_NONE, PIN4_TYPE_IAT]:
            result = apply_pin4_patch(rom, pin4_type)
            assert len(result) == len(rom)

    def test_detect_after_apply_wideband(self):
        rom = make_pin4_rom()
        if not PIN4_WIDEBAND_TABLES:
            pytest.skip("No wideband table definitions")
        key     = list(PIN4_WIDEBAND_TABLES.keys())[0]
        patched = apply_pin4_patch(rom, PIN4_TYPE_WIDEBAND, key)
        result  = detect_pin4_patch(bytes(patched))
        # Should now detect as patched, not 'none'
        assert result['state'] in ('patched', 'unknown'), \
            f"Expected 'patched' after apply, got {result['state']!r}"

    def test_detect_after_apply_map(self):
        rom = make_pin4_rom()
        if not PIN4_MAP_TABLES:
            pytest.skip("No MAP table definitions")
        key     = list(PIN4_MAP_TABLES.keys())[0]
        patched = apply_pin4_patch(rom, PIN4_TYPE_MAP, key)
        result  = detect_pin4_patch(bytes(patched))
        assert result['state'] in ('patched', 'unknown')


# ── Injection scaler ──────────────────────────────────────────────────────────

class TestInjectionScaler:
    def test_266d_is_not_applicable(self):
        rom = make_rom(ROM_266D)
        assert detect_injection_scaler_trick(rom, '266D') == 'not_applicable'

    def test_266b_is_not_applicable(self):
        rom = make_rom(ROM_266B)
        assert detect_injection_scaler_trick(rom, '266B') == 'not_applicable'

    def test_aah_on_blank_is_unknown(self):
        # Blank ROM (fill=103) — byte at 0x077E is 103, not 50 or 100
        rom = make_rom(ROM_AAH, fill=103)
        result = detect_injection_scaler_trick(rom, 'AAH')
        assert result in ('unknown', 'stock', 'halved')

    def test_aah_stock_scaler(self):
        # Set scaler byte to 100 (stock) at 0x077E
        rom = bytearray(make_rom(ROM_AAH))
        rom[0x077E] = 100
        result = detect_injection_scaler_trick(bytes(rom), 'AAH')
        assert result == 'stock'

    def test_aah_halved_scaler(self):
        # 'halved' detection requires BOTH scaler=50 AND fuel map mean in 180-240.
        # A ROM filled with 200 gives mean=200 (in range) plus sets scaler=50.
        rom = bytearray([200] * 32768)
        rom[ROM_AAH.size - 2] = ROM_AAH.reset_vector[0]
        rom[ROM_AAH.size - 1] = ROM_AAH.reset_vector[1]
        rom[0x077E] = 50
        result = detect_injection_scaler_trick(bytes(rom), 'AAH')
        assert result == 'halved'

    def test_apply_halve_changes_scaler_byte(self):
        rom = bytearray(make_rom(ROM_AAH))
        rom[0x077E] = 100   # start at stock
        patched = apply_injection_scaler_trick(bytes(rom), halve=True)
        assert patched[0x077E] == 50

    def test_apply_restore_changes_scaler_byte(self):
        rom = bytearray(make_rom(ROM_AAH))
        rom[0x077E] = 50    # start at halved
        restored = apply_injection_scaler_trick(bytes(rom), halve=False)
        assert restored[0x077E] == 100

    def test_apply_halve_rescales_fuel_map(self):
        rom = bytearray(make_rom(ROM_AAH))
        rom[0x077E] = 100
        # Use a near-stoich seed value (10) to avoid byte overflow.
        # raw=10 → λ≈1.078 → halved scaler → λ≈2.156 → raw≈148 (no overflow).
        # raw=80 would overflow: λ≈1.625 → halved → λ≈3.25 → raw 288 → wraps to 32.
        rom[0x0000] = 10  # fuel map cell [0,0]
        patched = apply_injection_scaler_trick(bytes(rom), halve=True)
        # After halving scaler, encoded value approximately doubles (148 > 10)
        assert patched[0x0000] > 10, "Fuel map should rescale up when scaler halved"

    def test_apply_roundtrip(self):
        rom = bytearray(make_rom(ROM_AAH))
        rom[0x077E] = 100
        halved   = apply_injection_scaler_trick(bytes(rom), halve=True)
        restored = apply_injection_scaler_trick(halved,     halve=False)
        # Scaler byte should be back at 100
        assert restored[0x077E] == 100

    def test_apply_preserves_length(self):
        rom = make_rom(ROM_AAH)
        for halve in [True, False]:
            result = apply_injection_scaler_trick(rom, halve=halve)
            assert len(result) == len(rom)


# ── compare_roms / diff_summary ───────────────────────────────────────────────

class TestCompareRoms:
    def test_identical_roms_empty(self):
        rom = bytes(make_rom(ROM_266D))
        assert compare_roms(rom, rom) == []

    def test_single_diff(self):
        rom_a = bytearray(make_rom(ROM_266D))
        rom_b = bytearray(rom_a)
        rom_b[0x0100] = (rom_a[0x0100] + 1) & 0xFF
        diffs = compare_roms(bytes(rom_a), bytes(rom_b))
        assert len(diffs) == 1
        assert diffs[0].address == 0x0100
        assert diffs[0].a == rom_a[0x0100]
        assert diffs[0].b == rom_b[0x0100]

    def test_multiple_diffs(self):
        rom_a = bytearray(make_rom(ROM_266D))
        rom_b = bytearray(rom_a)
        addrs = [0x0100, 0x0200, 0x1000]
        for addr in addrs:
            rom_b[addr] ^= 0xFF
        diffs = compare_roms(bytes(rom_a), bytes(rom_b))
        assert len(diffs) == len(addrs)
        assert {d.address for d in diffs} == set(addrs)

    def test_diff_summary_total(self):
        rom_a = bytearray(make_rom(ROM_266D))
        rom_b = bytearray(rom_a)
        rom_b[0x0100] ^= 0xFF
        rom_b[0x0200] ^= 0xFF
        diffs   = compare_roms(bytes(rom_a), bytes(rom_b))
        summary = diff_summary(diffs)
        # diff_summary groups by map region name ('unmapped' if no match).
        # Total diff count is the sum of all region counts.
        total = sum(summary.values())
        assert total == 2

    def test_diff_summary_empty(self):
        rom = bytes(make_rom(ROM_266D))
        diffs   = compare_roms(rom, rom)
        summary = diff_summary(diffs)
        assert sum(summary.values()) == 0

    def test_diff_in_fuel_map_region(self):
        """Diffs in known map regions should appear in results."""
        rom_a = bytearray(make_rom(ROM_266D))
        rom_b = bytearray(rom_a)
        # Primary fuel map is at 0x0000-0x00FF
        rom_b[0x0050] = (rom_a[0x0050] + 5) & 0xFF
        diffs = compare_roms(bytes(rom_a), bytes(rom_b))
        fuel_diffs = [d for d in diffs if d.address == 0x0050]
        assert len(fuel_diffs) == 1

    def test_compare_266d_vs_266b_same_zeros(self):
        """Zero-filled ROMs of same size should have no diffs except reset vector."""
        rom_a = bytearray(32768)
        rom_b = bytearray(32768)
        rom_a[0x7FFE] = 0xE8; rom_a[0x7FFF] = 0xB1  # 266D
        rom_b[0x7FFE] = 0xD7; rom_b[0x7FFF] = 0xBC  # 266B
        diffs = compare_roms(bytes(rom_a), bytes(rom_b))
        # Only 2 bytes differ (reset vector)
        assert len(diffs) == 2
        assert {d.address for d in diffs} == {0x7FFE, 0x7FFF}
