"""
HachiROM — Desktop GUI
Cross-platform PyQt5 map editor / compare tool for Hitachi ECU ROMs.
Standalone — no Teensy or serial connection required.
"""

import sys
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QTableWidget, QTableWidgetItem, QStatusBar, QMessageBox,
    QTextEdit, QSplitter, QAction, QHeaderView, QDialog,
    QDialogButtonBox, QFrame, QLineEdit, QScrollArea
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QBrush

sys.path.insert(0, str(Path(__file__).parent.parent))
import hachirom as hr

APP_VERSION = hr.__version__


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def heat_colour(value: int, vmin: int = 0, vmax: int = 255) -> QColor:
    t = (value - vmin) / max(1, vmax - vmin)
    if t < 0.25:
        u = t / 0.25
        return QColor(0, int(u * 160), int(120 + u * 135))
    elif t < 0.5:
        u = (t - 0.25) / 0.25
        return QColor(0, int(160 + u * 95), int(255 - u * 255))
    elif t < 0.75:
        u = (t - 0.5) / 0.25
        return QColor(int(u * 255), 255, 0)
    else:
        u = (t - 0.75) / 0.25
        return QColor(255, int(255 - u * 255), 0)

def timing_colour(raw_byte: int) -> QColor:
    signed = raw_byte if raw_byte < 128 else raw_byte - 256
    lo, hi = -10, 40
    return heat_colour(max(lo, min(hi, signed + 10)), 0, 50)

def _colour_item(item: QTableWidgetItem, colour: QColor, changed: bool = False):
    item.setBackground(QBrush(colour))
    brightness = colour.red() * 0.299 + colour.green() * 0.587 + colour.blue() * 0.114
    item.setForeground(QBrush(QColor("#111") if brightness > 140 else QColor("#eee")))
    if changed:
        # Green border via font — we use a custom property stored in the item
        item.setData(Qt.UserRole, "changed")
    else:
        item.setData(Qt.UserRole, None)


# ---------------------------------------------------------------------------
# Changed-cell delegate — draws green border on edited cells
# ---------------------------------------------------------------------------

from PyQt5.QtWidgets import QStyledItemDelegate
from PyQt5.QtGui import QPainter, QPen
from PyQt5.QtCore import QRect

class ChangedCellDelegate(QStyledItemDelegate):
    """Draws a green border around cells whose UserRole == 'changed'.
    Also tracks which index is being edited so _on_commit can reliably
    retrieve r,c regardless of where focus moves on Tab/Enter."""

    BORDER_COLOUR = QColor("#2dff6e")
    BORDER_WIDTH  = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.editing_index = None   # set in createEditor, read in _on_commit

    def createEditor(self, parent, option, index):
        self.editing_index = index
        return super().createEditor(parent, option, index)

    def paint(self, painter: QPainter, option, index):
        super().paint(painter, option, index)
        if index.data(Qt.UserRole) == "changed":
            painter.save()
            pen = QPen(self.BORDER_COLOUR, self.BORDER_WIDTH)
            painter.setPen(pen)
            r = option.rect.adjusted(1, 1, -1, -1)
            painter.drawRect(r)
            painter.restore()


# ---------------------------------------------------------------------------
# Save confirmation dialog
# ---------------------------------------------------------------------------

class SaveConfirmDialog(QDialog):
    def __init__(self, data: bytes, variant, path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirm Save")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        cs_sum = hr.compute_sum(data)
        cs_tgt = variant.checksum.get("target", 0)
        cs_ok  = cs_sum == cs_tgt
        delta  = cs_sum - cs_tgt
        cs_colour = "#2dff6e" if cs_ok else "#ff9900"
        cs_text   = "✓  VALID" if cs_ok else f"⚠  INVALID  (delta {delta:+,})"

        cs_box = QFrame()
        cs_box.setStyleSheet(
            f"background:#111; border:1px solid {cs_colour};"
            f"padding:8px; border-radius:3px;")
        cs_lay = QVBoxLayout(cs_box)
        cs_lay.setSpacing(3)

        def rl(label, value, c="#d4d4d4"):
            lbl = QLabel(f"<b style='color:#888'>{label}&nbsp;&nbsp;</b>"
                         f"<span style='color:{c}'>{value}</span>")
            lbl.setTextFormat(Qt.RichText)
            cs_lay.addWidget(lbl)

        rl("Checksum", cs_text, cs_colour)
        rl("Byte sum",  f"{cs_sum:,}")
        rl("Target",    f"{cs_tgt:,}")
        if not cs_ok:
            rl("Delta", f"{delta:+,}", "#ff9900")

        layout.addWidget(QLabel("<b>Checksum</b>", styleSheet="color:#aaa;"))
        layout.addWidget(cs_box)

        if not cs_ok:
            notice = QLabel(
                f"⚙  Checksum will be corrected automatically before writing.\n"
                f"    Correction region: 0x{variant.checksum['cs_from']:04X}–"
                f"0x{variant.checksum['cs_to']:04X}  "
                f"({variant.checksum['cs_to'] - variant.checksum['cs_from'] + 1} bytes)"
            )
            notice.setStyleSheet("color:#ff9900; font-size:11px; padding:4px 0;")
            notice.setWordWrap(True)
            layout.addWidget(notice)

        layout.addWidget(QLabel("<b>Output file</b>", styleSheet="color:#aaa;"))
        file_box = QFrame()
        file_box.setStyleSheet(
            "background:#111; border:1px solid #333; padding:8px; border-radius:3px;")
        fl = QVBoxLayout(file_box)
        fl.setSpacing(3)

        size_str = f"{len(data):,} bytes (32 KB)"
        note_str = "Native 32KB ROM — Teensy SD card / emulator"

        def fl_row(label, value):
            lbl = QLabel(f"<b style='color:#888'>{label}&nbsp;&nbsp;</b>"
                         f"<span style='color:#d4d4d4'>{value}</span>")
            lbl.setTextFormat(Qt.RichText)
            fl.addWidget(lbl)

        fl_row("Path",   Path(path).name)
        fl_row("Size",   size_str)
        fl_row("Format", note_str)
        fl_row("ECU",    f"{variant.name}  ({variant.part_number})")
        layout.addWidget(file_box)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        save_btn = btns.button(QDialogButtonBox.Save)
        save_btn.setText("Save" if cs_ok else "Fix Checksum & Save")
        save_btn.setStyleSheet(
            "QPushButton{background:#0e639c;color:#fff;padding:5px 16px;"
            "border:none;border-radius:3px;}"
            "QPushButton:hover{background:#1177bb;}"
        )
        layout.addWidget(btns)

        self.setStyleSheet("""
            QDialog  { background:#1e1e1e; color:#d4d4d4; }
            QLabel   { color:#d4d4d4; font-size:12px; }
            QDialogButtonBox QPushButton {
                background:#333; color:#d4d4d4; padding:5px 14px;
                border:1px solid #555; border-radius:3px;
            }
            QDialogButtonBox QPushButton:hover { background:#444; }
        """)


# ---------------------------------------------------------------------------
# MAF hardware patch dialog
# ---------------------------------------------------------------------------

class MafPatchDialog(QDialog):
    """
    Dialog for selecting and applying a MAF sensor housing swap patch (266D only).

    Shows the currently detected sensor profile, lets the user pick a target
    profile, explains the hardware changes required, and writes the new MAF
    axis tables into the in-memory ROM snapshot on confirmation.

    The caller is responsible for:
      - Only showing this dialog when current_variant.version_key == "266D"
      - Passing the live rom_snapshot bytes
      - Calling apply_maf_patch() on the returned profile key then reloading
    """

    # Emitted with the chosen profile_key when the user clicks Apply
    patch_requested = pyqtSignal(str)

    def __init__(self, rom_data: bytes, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MAF Sensor Patch — 266D")
        self.setMinimumWidth(560)
        self.setModal(True)

        current_profile = hr.detect_maf_patch(rom_data)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── Current state banner ────────────────────────────────────────────
        profile_info = hr.MAF_PROFILES.get(current_profile, {})
        if current_profile == "unknown":
            banner_colour = "#ff9900"
            banner_text   = "⚠  Unknown MAF axis — ROM may be custom-tuned"
        elif current_profile == "inconsistent":
            banner_colour = "#ff4444"
            banner_text   = "✗  Inconsistent MAF axes — fuel and timing copies differ"
        else:
            banner_colour = "#2dff6e"
            banner_text   = f"✓  {profile_info.get('label', current_profile)}"

        banner = QFrame()
        banner.setStyleSheet(
            f"background:#111; border:1px solid {banner_colour}; "
            f"padding:8px; border-radius:3px;")
        bl = QVBoxLayout(banner)
        bl.setSpacing(3)
        bl.addWidget(QLabel(
            f"<b style='color:#888'>Current sensor&nbsp;&nbsp;</b>"
            f"<span style='color:{banner_colour}'>{banner_text}</span>",
            textFormat=Qt.RichText))
        if current_profile not in ("unknown", "inconsistent"):
            bl.addWidget(QLabel(
                f"<span style='color:#666; font-size:11px;'>"
                f"{profile_info.get('housing', '')} — "
                f"{profile_info.get('hp_note', '')}</span>",
                textFormat=Qt.RichText))
        layout.addWidget(QLabel("<b>Detected in ROM</b>", styleSheet="color:#aaa;"))
        layout.addWidget(banner)

        # ── Sensor selection ────────────────────────────────────────────────
        layout.addWidget(QLabel("<b>Apply sensor patch</b>", styleSheet="color:#aaa;"))

        self._buttons: dict[str, QRadioButton] = {}
        btn_group = QButtonGroup(self)

        last_group = None
        for key, p in hr.MAF_PROFILES.items():
            # Group separator heading
            group = p.get("group", "")
            if group != last_group:
                grp_lbl = QLabel(group)
                grp_lbl.setStyleSheet(
                    "color:#666; font-size:10px; text-transform:uppercase; "
                    "letter-spacing:1px; padding:4px 0 2px 2px;")
                layout.addWidget(grp_lbl)
                last_group = group

            row = QFrame()
            row.setStyleSheet(
                "background:#1a1a1a; border:1px solid #333; "
                "padding:6px; border-radius:3px;")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(4, 2, 4, 2)

            rb = QRadioButton(p["label"])
            rb.setStyleSheet("color:#d4d4d4; font-weight:bold;")
            if key == current_profile:
                rb.setChecked(True)
            btn_group.addButton(rb)
            self._buttons[key] = rb

            detail = QLabel(
                f"<span style='color:#666; font-size:11px;'>"
                f"{p['housing']}<br>"
                f"<b style='color:#888'>{p['hp_note']}</b></span>",
                textFormat=Qt.RichText)
            detail.setWordWrap(True)

            # Badges: plug-and-play indicator + CO pot status
            badges = QHBoxLayout()
            badges.setSpacing(4)
            badges.setContentsMargins(0, 0, 0, 0)

            if p.get("plug_play"):
                pp_lbl = QLabel("✔ plug-and-play wiring")
                pp_lbl.setStyleSheet(
                    "color:#2dff6e; font-size:10px; background:#0a1a0a; "
                    "border:1px solid #1a5c1a; padding:1px 4px; border-radius:2px;")
                pp_lbl.setToolTip("No wiring changes needed — original 4-pin connector fits directly.")
                badges.addWidget(pp_lbl)

            if p["co_pot"]:
                co_lbl = QLabel("CO pot retained")
                co_lbl.setStyleSheet(
                    "color:#888; font-size:10px; background:#222; "
                    "border:1px solid #444; padding:1px 4px; border-radius:2px;")
                co_lbl.setToolTip(
                    "This sensor retains the CO trim pot on pin 4.\n"
                    "Idle mixture adjustment works exactly as standard.")
            else:
                co_lbl = QLabel("4-wire  ⚠ bridge pin 4")
                co_lbl.setStyleSheet(
                    "color:#ff9900; font-size:10px; background:#2a1a00; "
                    "border:1px solid #664400; padding:1px 4px; border-radius:2px;")
                co_lbl.setToolTip(
                    "3-wire sensor — no CO pot (pin 4).\n"
                    "Fault code 00521 will be stored if pin 4 is left open.\n"
                    "Hardware fix: 1kΩ resistor from pot pin 1 to GND,\n"
                    "wiper (pin 2) to ECU pin 4, 20kΩ 10-turn pot.\n"
                    "Covers 1.0–7.5V range — adjustable like original.\n"
                    "(Source: 20v-sauger-tuning.de — Reichelt 534-20K pot)")
            badges.addWidget(co_lbl)
            badges.addStretch()

            badge_widget = QWidget()
            badge_widget.setLayout(badges)

            detail_col = QVBoxLayout()
            detail_col.setSpacing(2)
            detail_col.setContentsMargins(0, 0, 0, 0)
            detail_col.addWidget(detail)
            if p.get("note"):
                note_lbl = QLabel(
                    f"<span style='color:#888; font-size:10px;'>⚠ {p['note']}</span>",
                    textFormat=Qt.RichText)
                note_lbl.setWordWrap(True)
                detail_col.addWidget(note_lbl)
            detail_col.addWidget(badge_widget)
            detail_container = QWidget()
            detail_container.setLayout(detail_col)

            rl.addWidget(rb)
            rl.addWidget(detail_container, 1)
            layout.addWidget(row)

        # If none of the known profiles is selected (unknown/inconsistent), default to stock
        if not any(rb.isChecked() for rb in self._buttons.values()):
            self._buttons["stock_7a"].setChecked(True)

        # ── CO pot warning box (shown for 3-wire sensors only) ───────────────
        co_box = QFrame()
        co_box.setStyleSheet(
            "background:#1a1200; border:1px solid #664400; "
            "padding:8px; border-radius:3px;")
        co_lay = QVBoxLayout(co_box)
        co_lay.setSpacing(2)
        co_lay.addWidget(QLabel(
            "<b style='color:#ff9900'>⚠  CO pot (pin 4) — hardware action required</b>",
            textFormat=Qt.RichText))
        co_lay.addWidget(QLabel(
            "<span style='color:#aaa; font-size:11px;'>"
            "This sensor has no CO pot.  ECU pin 4 must not be left floating or "
            "fault code 00521 will be stored and idle will be affected.<br>"
            "<b>Fix (from 20v-sauger-tuning.de):</b> wire a 1 kΩ resistor from "
            "pot pin 1 to GND, connect the wiper (pin 2) to ECU pin 4.  "
            "Use a 20 kΩ 10-turn pot (Reichelt 534-20K) for fine adjustment "
            "over the 1.0–7.5 V range — identical behaviour to the original CO pot."
            "</span>",
            textFormat=Qt.RichText))
        co_box.setVisible(False)
        layout.addWidget(co_box)
        self._co_box = co_box

        # Update CO warning visibility when selection changes
        for key, rb in self._buttons.items():
            rb.toggled.connect(lambda checked, k=key: self._on_profile_changed(k, checked))

        # Initial state
        for key, rb in self._buttons.items():
            if rb.isChecked():
                self._on_profile_changed(key, True)

        # ── Patch scope note ─────────────────────────────────────────────────
        scope = QLabel(
            "<span style='color:#555; font-size:10px;'>"
            "Patch rewrites MAF axis breakpoints at 0x05D0 (fuel) and 0x05E0 (timing). "
            "Fuel and timing map <i>data</i> is unchanged — only the axis lookup is rescaled "
            "so the ECU interpolates correctly for the new sensor's transfer function."
            "</span>",
            textFormat=Qt.RichText)
        scope.setWordWrap(True)
        layout.addWidget(scope)

        # ── Buttons ──────────────────────────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_btn = btns.button(QDialogButtonBox.Ok)
        ok_btn.setText("Apply Patch")
        ok_btn.setStyleSheet(
            "QPushButton{background:#0e639c;color:#fff;padding:5px 16px;"
            "border:none;border-radius:3px;}"
            "QPushButton:hover{background:#1177bb;}")
        btns.accepted.connect(self._on_apply)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self.setStyleSheet("""
            QDialog { background:#1e1e1e; color:#d4d4d4; }
            QLabel  { color:#d4d4d4; }
            QRadioButton { color:#d4d4d4; }
            QDialogButtonBox QPushButton {
                background:#333; color:#d4d4d4; padding:5px 14px;
                border:1px solid #555; border-radius:3px;
            }
            QDialogButtonBox QPushButton:hover { background:#444; }
        """)

    def _on_profile_changed(self, key: str, checked: bool):
        if not checked:
            return
        # Show CO pot warning for any non-stock sensor
        needs_co_fix = not hr.MAF_PROFILES[key]["co_pot"]
        self._co_box.setVisible(needs_co_fix)

    def _on_apply(self):
        for key, rb in self._buttons.items():
            if rb.isChecked():
                self.patch_requested.emit(key)
                self.accept()
                return
        self.reject()

    def selected_profile(self) -> str:
        for key, rb in self._buttons.items():
            if rb.isChecked():
                return key
        return "stock_7a"


# ---------------------------------------------------------------------------
# Map tab
# ---------------------------------------------------------------------------

class MapTab(QWidget):
    """
    Editable heatmap for one ROM map.

    Architecture:
      _baseline[r][c]  — raw byte snapshot at open time, never mutated
      _local[r][c]     — working copy; edits land here

    Editing uses delegate.commitData signal (fires exactly once when the
    user confirms a cell edit via Enter/Tab/click-away). This avoids the
    itemChanged re-entrancy bug where blockSignals on QTableWidget does not
    suppress signals fired via QAbstractItemModel.dataChanged.

    Green border on cells where _local != _baseline via ChangedCellDelegate.
    """

    rom_changed = pyqtSignal()   # emitted after every successful cell edit

    def __init__(self, map_def, rom_snapshot: bytes, parent=None):
        super().__init__(parent)
        self.map_def  = map_def
        self._is_timing = any(k in map_def.name.lower()
                              for k in ("timing", "knock"))

        addr, rows, cols = map_def.address, map_def.rows, map_def.cols

        def _read(r, c):
            off = addr + r * cols + c
            return rom_snapshot[off] if off < len(rom_snapshot) else 0

        # Both grids are independent in-memory copies — nothing is written back
        # to any shared buffer until the user explicitly saves.
        self._baseline = [[_read(r, c) for c in range(cols)] for r in range(rows)]
        self._local    = [[_read(r, c) for c in range(cols)] for r in range(rows)]

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        info = QLabel(
            f"<b>{self.map_def.name}</b>  ·  "
            f"Addr: <code>0x{self.map_def.address:04X}</code>  ·  "
            f"{self.map_def.rows}\u00d7{self.map_def.cols}  ·  "
            f"{self.map_def.unit or ''}  \u2014  {self.map_def.description}"
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#aaa; font-size:11px; padding:2px 0;")
        hint = QLabel(
            "Double-click to edit  \u00b7  Enter/Tab to confirm  \u00b7  Esc to cancel  \u00b7  "
            "<span style='color:#2dff6e'>\u25a0</span> = changed from disk")
        hint.setTextFormat(Qt.RichText)
        hint.setStyleSheet("color:#555; font-size:10px;")
        hdr = QHBoxLayout()
        hdr.addWidget(info, 1)
        hdr.addWidget(hint)
        layout.addLayout(hdr)

        rows, cols = self.map_def.rows, self.map_def.cols
        self.table = QTableWidget(rows, cols)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setFont(QFont("Consolas", 9))
        self.table.setEditTriggers(QTableWidget.DoubleClicked)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setItemDelegate(ChangedCellDelegate(self.table))
        layout.addWidget(self.table)

        if self.map_def.rpm_axis:
            self.table.setVerticalHeaderLabels(
                [str(v) for v in self.map_def.rpm_axis[:rows]])
        if self.map_def.load_axis:
            self.table.setHorizontalHeaderLabels(
                [str(v) for v in self.map_def.load_axis[:cols]])

        self._populate_table()

        # commitData fires exactly once when user confirms edit — no re-entry,
        # no blockSignals needed, works correctly on every tab.
        self.table.itemDelegate().commitData.connect(self._on_commit)

    def _decode(self, raw: int) -> str:
        if self.map_def.decode:
            v = self.map_def.decode(raw)
            return f"{v:.3f}" if isinstance(v, float) else str(v)
        return str(raw)

    def _encode(self, text: str):
        try:
            v = float(text)
            if self.map_def.encode:
                # Always pass a numeric type the encode function can handle.
                # timing_encode uses & 0xFF so needs int; lambda encodes need float.
                raw = self.map_def.encode(v)
                return max(0, min(255, int(round(raw)) & 0xFF))
            iv = int(v)
            if iv < 0:
                iv = iv & 0xFF   # two's complement for signed maps (e.g. timing trim)
            return max(0, min(255, iv))
        except (ValueError, TypeError):
            return None

    def _populate_table(self):
        rows, cols = self.map_def.rows, self.map_def.cols
        all_raw = [self._local[r][c] for r in range(rows) for c in range(cols)]
        vmin, vmax = min(all_raw), max(all_raw)
        for r in range(rows):
            for c in range(cols):
                raw     = self._local[r][c]
                changed = raw != self._baseline[r][c]
                item    = QTableWidgetItem(self._decode(raw))
                item.setTextAlignment(Qt.AlignCenter)
                colour  = (timing_colour(raw) if self._is_timing
                           else heat_colour(raw, vmin, vmax))
                _colour_item(item, colour, changed)
                if self._is_timing:
                    signed = raw if raw < 128 else raw - 256
                    item.setToolTip(f"raw={raw}  \u2192  {signed:+d}\u00b0 BTDC")
                self.table.setItem(r, c, item)

    def _on_commit(self, editor):
        """Called by the delegate exactly once when user confirms a cell edit."""
        idx = self.table.itemDelegate().editing_index
        if idx is None or not idx.isValid():
            return
        r, c = idx.row(), idx.column()
        text = editor.text()
        raw  = self._encode(text)

        if raw is None:
            # Bad input — restore displayed value from _local
            self.table.item(r, c).setText(self._decode(self._local[r][c]))
            return

        self._local[r][c] = raw
        changed = raw != self._baseline[r][c]
        self.rom_changed.emit()

        # Recolour entire table (heat range may have shifted)
        all_raw = [self._local[rr][cc]
                   for rr in range(self.map_def.rows)
                   for cc in range(self.map_def.cols)]
        vmin, vmax = min(all_raw), max(all_raw)

        for rr in range(self.map_def.rows):
            for cc in range(self.map_def.cols):
                item = self.table.item(rr, cc)
                if item is None:
                    continue
                v = self._local[rr][cc]
                ch = v != self._baseline[rr][cc]
                col = (timing_colour(v) if self._is_timing
                       else heat_colour(v, vmin, vmax))
                _colour_item(item, col, ch)
                if self._is_timing:
                    s = v if v < 128 else v - 256
                    item.setToolTip(f"raw={v}  \u2192  {s:+d}\u00b0 BTDC")

    def build_patch(self) -> dict:
        """Return {rom_offset: byte} for every cell that differs from baseline.
        Nothing is written anywhere — caller assembles the full ROM on save."""
        addr, rows, cols = self.map_def.address, self.map_def.rows, self.map_def.cols
        patch = {}
        for r in range(rows):
            for c in range(cols):
                if self._local[r][c] != self._baseline[r][c]:
                    patch[addr + r * cols + c] = self._local[r][c]
        return patch

    def changed_count(self) -> int:
        rows, cols = self.map_def.rows, self.map_def.cols
        return sum(
            1 for r in range(rows) for c in range(cols)
            if self._local[r][c] != self._baseline[r][c]
        )


# ---------------------------------------------------------------------------
# Overview tab  — single-value edits surfaced as labelled input fields
# ---------------------------------------------------------------------------

class OverviewField(QWidget):
    """One labelled row: name | current value | RPM input | Apply button | status."""

    changed  = pyqtSignal()        # emitted when value is written to _local
    selected = pyqtSignal(object)  # emitted when this field is clicked/focused

    def __init__(self, map_def, rom_snapshot: bytes, parent=None):
        super().__init__(parent)
        self.map_def      = map_def
        self._snapshot    = rom_snapshot
        self._map_tab     = None   # lazily created MapTab for patch access

        addr = map_def.address
        raw  = rom_snapshot[addr] if addr < len(rom_snapshot) else 0
        self._raw = raw

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(12)

        # Name label
        lbl_name = QLabel(map_def.name)
        lbl_name.setFixedWidth(160)
        lbl_name.setStyleSheet("color:#aaa; font-size:12px;")
        layout.addWidget(lbl_name)

        # Current decoded value (read-only display)
        decoded = map_def.decode(raw) if map_def.decode else raw
        cur_txt = (f"{decoded:.0f}" if isinstance(decoded, float) and decoded == int(decoded)
                   else f"{decoded:.3f}" if isinstance(decoded, float) else str(decoded))
        self.lbl_current = QLabel(f"{cur_txt} {map_def.unit or ''}")
        self.lbl_current.setFixedWidth(120)
        self.lbl_current.setStyleSheet("color:#888; font-size:12px;")
        layout.addWidget(self.lbl_current)

        # Editable input
        self.edit = QLineEdit(cur_txt)
        self.edit.setFixedWidth(110)
        self.edit.setStyleSheet(
            "background:#2a2a2a; color:#e8e8e8; border:1px solid #444; "
            "border-radius:3px; padding:3px 6px; font-size:12px;")
        self.edit.returnPressed.connect(self._apply)
        self.edit.installEventFilter(self)
        layout.addWidget(self.edit)

        unit_lbl = QLabel(map_def.unit or "")
        unit_lbl.setFixedWidth(40)
        unit_lbl.setStyleSheet("color:#666; font-size:11px;")
        layout.addWidget(unit_lbl)

        # Apply button
        self.btn = QPushButton("Apply")
        self.btn.setFixedWidth(70)
        self.btn.setStyleSheet(
            "QPushButton { background:#1a6b3a; color:#fff; border:none; "
            "border-radius:3px; padding:4px 10px; font-size:12px; }"
            "QPushButton:hover { background:#22994f; }"
            "QPushButton:pressed { background:#155c30; }")
        self.btn.clicked.connect(self._apply)
        layout.addWidget(self.btn)

        # Status label
        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("font-size:11px; color:#555;")
        layout.addWidget(self.lbl_status)
        layout.addStretch()

    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent
        if event.type() == QEvent.FocusIn:
            self.selected.emit(self)
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event):
        self.selected.emit(self)
        super().mousePressEvent(event)

    def _ensure_tab(self):
        if self._map_tab is None:
            self._map_tab = MapTab(self.map_def, self._snapshot)

    def _apply(self):
        self._ensure_tab()
        text = self.edit.text().strip()
        raw = self._map_tab._encode(text)
        if raw is None:
            self.lbl_status.setText("✗ invalid value")
            self.lbl_status.setStyleSheet("font-size:11px; color:#ff6666;")
            return
        self._map_tab._local[0][0] = raw
        self._raw = raw
        decoded = self.map_def.decode(raw) if self.map_def.decode else raw
        disp = (f"{decoded:.0f}" if isinstance(decoded, float) and decoded == int(decoded)
                else f"{decoded:.3f}" if isinstance(decoded, float) else str(decoded))
        self.edit.setText(disp)
        self.lbl_current.setText(f"{disp} {self.map_def.unit or ''}")
        self.lbl_status.setText("✓ applied")
        self.lbl_status.setStyleSheet("font-size:11px; color:#2dff6e;")
        self.changed.emit()

    def build_patch(self) -> dict:
        if self._map_tab is None:
            return {}
        return self._map_tab.build_patch()

    def changed_count(self) -> int:
        if self._map_tab is None:
            return 0
        return self._map_tab.changed_count()


class OverviewTab(QWidget):
    """First tab — surfaces RPM Limit, Injection Scaler, CL Disable RPM
    as simple labelled input fields. Mirrors the DigiTool overview UX."""

    # Names of maps to surface (in order). Only shown if present in the variant.
    FIELD_NAMES = ["RPM Limit", "Injection Scaler", "CL Disable RPM", "CL RPM Limit"]

    def __init__(self, variant, rom_snapshot: bytes, parent=None):
        super().__init__(parent)
        self._fields: list[OverviewField] = []
        self._build_ui(variant, rom_snapshot)

    def _build_ui(self, variant, rom_snapshot: bytes):
        # Two-column layout: left = input fields, right = tips panel
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left column ───────────────────────────────────────────────────────
        left_widget = QWidget()
        outer = QVBoxLayout(left_widget)
        outer.setContentsMargins(20, 20, 12, 20)
        outer.setSpacing(0)

        # ── REV LIMIT section ────────────────────────────────────────────────
        rpm_maps = [m for m in variant.maps if m.name == "RPM Limit"]
        if rpm_maps:
            outer.addWidget(self._section_header(
                "REV LIMIT",
                "The classic first EPROM edit. Change the value, "
                "click Apply, then Save 27C512 and burn the chip."))
            field = OverviewField(rpm_maps[0], rom_snapshot)
            field.selected.connect(self._on_field_selected)
            self._fields.append(field)
            outer.addWidget(field)
            outer.addSpacing(8)

        # ── ECU PARAMETERS section ───────────────────────────────────────────
        param_names = ["Injection Scaler", "CL Disable RPM", "CL RPM Limit"]
        param_maps  = [m for m in variant.maps if m.name in param_names]
        param_maps.sort(key=lambda m: param_names.index(m.name)
                        if m.name in param_names else 99)
        has_scaler = any(m.name == "Injection Scaler" for m in variant.maps)

        # Section subtitle — variant-aware
        if not has_scaler:
            subtitle = ("Injection Scaler is not present on this ECU variant — "
                        "the injector pulse is fixed in firmware. "
                        "Use the fuel map to adjust fuelling.")
        else:
            subtitle = ("Click a row to see tuning tips →  "
                        "Single-byte scalars that affect the whole fuel system.")

        if param_maps:
            outer.addSpacing(16)
            outer.addWidget(self._section_header("ECU PARAMETERS", subtitle))
            for m in param_maps:
                field = OverviewField(m, rom_snapshot)
                field.selected.connect(self._on_field_selected)
                self._fields.append(field)
                outer.addWidget(field)
                outer.addSpacing(4)
        elif not has_scaler:
            outer.addSpacing(16)
            outer.addWidget(self._section_header("ECU PARAMETERS", subtitle))

        outer.addStretch()

        # ── Workflow hint ────────────────────────────────────────────────────
        hint = QLabel(
            "Workflow:  Open ROM  →  edit values above  →  "
            "Save 27C512 .bin  →  burn with TL866 / T48  →  install  →  test")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#555; font-size:11px; padding:12px 0 0 0;")
        outer.addWidget(hint)

        # ── Right column: tips panel ──────────────────────────────────────────
        self._tips_panel = MapInfoPanel()
        self._tips_panel.setFixedWidth(310)
        self._tips_panel.setStyleSheet(
            "background:#131313; border-left:1px solid #222;")

        root.addWidget(left_widget, stretch=1)
        root.addWidget(self._tips_panel)

    @staticmethod
    def _section_header(title: str, subtitle: str) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 6)
        v.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet(
            "color:#2dff6e; font-size:10px; font-weight:bold; letter-spacing:2px;")
        s = QLabel(subtitle)
        s.setWordWrap(True)
        s.setStyleSheet("color:#555; font-size:11px;")
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#2a2a2a;")
        v.addWidget(t)
        v.addWidget(s)
        v.addWidget(sep)
        return w

    def _on_field_selected(self, field: "OverviewField"):
        """Update the tips panel when a field is clicked or focused."""
        self._tips_panel.update_map(
            field.map_def.name,
            map_def=field.map_def,
            info=_MAP_TIPS.get(field.map_def.name))

    def show_first_tip(self):
        """Pre-populate tips panel with first field on load."""
        if self._fields:
            self._on_field_selected(self._fields[0])

    def build_patches(self) -> dict:
        """Merged patch dict from all fields."""
        patch = {}
        for f in self._fields:
            patch.update(f.build_patch())
        return patch

    def changed_count(self) -> int:
        return sum(f.changed_count() for f in self._fields)


# ---------------------------------------------------------------------------
# Compare tab  — can be pre-loaded programmatically
# ---------------------------------------------------------------------------

class CompareTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data_a: bytes = b""
        self.data_b: bytes = b""
        self.label_a = "ROM A"
        self.label_b = "ROM B"
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        load_row = QHBoxLayout()
        self.lbl_a = QLabel("ROM A: (none)")
        self.lbl_b = QLabel("ROM B: (none)")
        self.lbl_a.setStyleSheet("color:#aaa; font-size:11px;")
        self.lbl_b.setStyleSheet("color:#aaa; font-size:11px;")
        btn_a   = QPushButton("Load ROM A…")
        btn_b   = QPushButton("Load ROM B…")
        btn_cmp = QPushButton("⊕  Compare")
        btn_a.clicked.connect(self._load_a)
        btn_b.clicked.connect(self._load_b)
        btn_cmp.clicked.connect(self.run_compare)
        load_row.addWidget(btn_a)
        load_row.addWidget(self.lbl_a, 1)
        load_row.addWidget(btn_b)
        load_row.addWidget(self.lbl_b, 1)
        load_row.addWidget(btn_cmp)
        layout.addLayout(load_row)
        self.result = QTextEdit()
        self.result.setReadOnly(True)
        self.result.setFont(QFont("Consolas", 9))
        self.result.setPlaceholderText(
            "Load two ROMs and click Compare.")
        layout.addWidget(self.result)

    def load_pair(self, data_a: bytes, label_a: str,
                        data_b: bytes, label_b: str):
        """Pre-load both sides programmatically and run the compare."""
        self.data_a, self.label_a = data_a, label_a
        self.data_b, self.label_b = data_b, label_b
        r_a = hr.detect(data_a)
        r_b = hr.detect(data_b)
        self.lbl_a.setText(
            f"ROM A: {label_a}  "
            f"[{r_a.variant.name if r_a.variant else 'Unknown'}  {r_a.crc32:#010x}]")
        self.lbl_a.setStyleSheet("color:#2dff6e; font-size:11px;")
        self.lbl_b.setText(
            f"ROM B: {label_b}  "
            f"[{r_b.variant.name if r_b.variant else 'Unknown'}  {r_b.crc32:#010x}]")
        self.lbl_b.setStyleSheet("color:#aaa; font-size:11px;")
        self.run_compare()

    def _load_file(self, title):
        path, _ = QFileDialog.getOpenFileName(
            self, title, "", "ROM Files (*.bin *.034);;All Files (*)")
        if not path:
            return None, None
        data = hr.load_bin(path)
        if path.lower().endswith(".034"):
            data = hr.unscramble_034(data)
        return data, path

    def _load_a(self):
        data, path = self._load_file("Load ROM A")
        if data is None: return
        self.data_a  = data
        self.label_a = Path(path).name
        r = hr.detect(data)
        self.lbl_a.setText(
            f"ROM A: {self.label_a}  "
            f"[{r.variant.name if r.variant else 'Unknown'}  {r.crc32:#010x}]")
        self.lbl_a.setStyleSheet("color:#2dff6e; font-size:11px;")

    def _load_b(self):
        data, path = self._load_file("Load ROM B")
        if data is None: return
        self.data_b  = data
        self.label_b = Path(path).name
        r = hr.detect(data)
        self.lbl_b.setText(
            f"ROM B: {self.label_b}  "
            f"[{r.variant.name if r.variant else 'Unknown'}  {r.crc32:#010x}]")
        self.lbl_b.setStyleSheet("color:#aaa; font-size:11px;")

    def run_compare(self):
        if not self.data_a or not self.data_b:
            QMessageBox.warning(self, "HachiROM", "Load both ROMs first.")
            return
        ra    = hr.detect(self.data_a)
        diffs = hr.compare_roms(self.data_a, self.data_b, ra.variant)
        summary = hr.diff_summary(diffs)

        lines = [f"ROM COMPARE — {len(diffs)} byte(s) differ", ""]
        if summary:
            lines += ["CHANGED BYTES BY MAP REGION", "-" * 50]
            for region, count in sorted(summary.items(), key=lambda x: -x[1]):
                lines.append(f"  {region:<34} {count:>4}  {'█' * min(count, 30)}")
            lines.append("")
        lines.append(f"  {'ADDR':>6}  {'A':>3}  {'B':>3}  {'Δ':>4}  MAP REGION")
        lines.append("  " + "-" * 58)
        for d in diffs[:300]:
            lines.append(
                f"  0x{d.address:04X}  {d.a:>3}  {d.b:>3}  "
                f"{d.b - d.a:>+4}  {d.map_name or '—'}")
        if len(diffs) > 300:
            lines.append(f"  … {len(diffs) - 300} more not shown")
        self.result.setPlainText("\n".join(lines))


# ---------------------------------------------------------------------------
# ROM Info panel
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Per-map tuning tips — shown in sidebar when a map tab is active
# Keys match MapDef.name exactly.
# ---------------------------------------------------------------------------

_MAP_TIPS: dict[str, dict] = {
    "Primary Fueling": {
        "what":  "The main fuel delivery table. Each cell sets the injector "
                 "pulse width (or lambda target on B/AAH) at a given RPM and "
                 "engine load (MAP sensor pressure).",
        "tips": [
            "Richer (higher value) = more fuel. Lean (lower) = less fuel.",
            "Work across the load axis first — wide-open throttle is the "
            "bottom rows, idle is the top.",
            "Fix idle and cruise before touching WOT cells.",
            "After any change, the checksum is corrected automatically on save.",
        ],
        "caution": "Lean WOT cells cause knock and piston damage. Always run "
                   "richer than stoichiometric under high load.",
    },
    "Primary Timing": {
        "what":  "Ignition advance in degrees BTDC at each RPM/load point. "
                 "More advance = spark fires earlier. The ECU uses this map "
                 "under normal (no-knock) conditions.",
        "tips": [
            "Advance (higher) improves power but risks knock on poor fuel.",
            "Retard (lower) under high load/low RPM to prevent detonation.",
            "Idle timing affects idle quality — typically 10-15° BTDC.",
            "Changes here are overridden by the Knock Safety map if knock "
            "is detected.",
        ],
        "caution": "Excessive advance causes detonation — start conservative "
                   "and verify with a knock sensor or wideband O2.",
    },
    "Timing Knock Safety": {
        "what":  "Fallback timing map used by the ECU when knock is detected. "
                 "The ECU blends toward this map and recovers gradually. "
                 "Should always be more retarded than Primary Timing.",
        "tips": [
            "Keep this 4-8° retarded vs Primary Timing across the whole map.",
            "Changing this affects how aggressively the ECU responds to knock.",
            "On a stock engine, this rarely needs editing.",
            "On a tuned or high-compression build, verify the retard amount "
            "is enough to stop knock before the engine recovers timing.",
        ],
        "caution": "If this map is more advanced than Primary Timing in any "
                   "cell, knock recovery will be ineffective.",
    },
    "After-start Enrichment": {
        "what":  "Extra fuel added immediately after a cold start, tapering "
                 "off as the engine warms. Indexed by coolant temperature. "
                 "Decoded as lambda — lower = richer.",
        "tips": [
            "Stock taper: λ 1.5 → 1.25 from cold to warm.",
            "If the engine stumbles or stalls in the first 30s after cold "
            "start, richen the cold end (left cells).",
            "If it runs black smoke on cold start, lean the left cells.",
            "The warmup idle speed target works alongside this map.",
        ],
        "caution": None,
    },
    "Idle Speed Target": {
        "what":  "Target idle RPM at each coolant temperature step. The ECU "
                 "drives the idle air control valve toward this speed. "
                 "Raw value × 25 = RPM.",
        "tips": [
            "Stock: ~3600 RPM cold (raw 144), ~800 RPM warm (raw 32).",
            "Raising cold-idle RPM helps warm-up on tight clearance engines.",
            "Lowering warm-idle RPM saves fuel and reduces vibration.",
            "Pairs with Idle Ignition Trim — both affect idle quality.",
        ],
        "caution": "Too low at cold temperatures will cause stalling.",
    },
    "Idle Ignition Trim": {
        "what":  "Timing correction applied at idle vs coolant temperature. "
                 "Signed value in degrees — positive = advance, negative = retard. "
                 "Added on top of the Primary Timing map at idle.",
        "tips": [
            "Stock: +7° warm, -9° cold (retards cold idle to improve warm-up).",
            "Advancing idle timing can raise idle RPM without touching the "
            "idle speed valve.",
            "Retarding improves idle smoothness on high-overlap cams.",
        ],
        "caution": None,
    },
    "Accel Enrichment": {
        "what":  "Extra fuel injected on sudden throttle opening (tip-in). "
                 "Indexed by RPM — the pulse is smaller at high RPM where "
                 "airflow change is faster.",
        "tips": [
            "Stock: 104 at idle, tapering to 48 at 6000 RPM.",
            "If the engine stumbles on quick throttle blips, increase the "
            "low-RPM cells.",
            "If it runs rich momentarily on tip-in (black puff), reduce.",
            "Accel Decay controls how fast this extra fuel fades away.",
        ],
        "caution": None,
    },
    "Accel Decay": {
        "what":  "How quickly the accel enrichment pulse fades after tip-in. "
                 "Higher value = faster decay (shorter enrichment). "
                 "Indexed by RPM.",
        "tips": [
            "Stock: exponential 100 → 2 across RPM range.",
            "Increase (faster decay) if tip-in richness lingers too long.",
            "Decrease (slower decay) if stumble persists after the initial blip.",
            "Works together with Accel Enrichment amount.",
        ],
        "caution": None,
    },
    "CL RPM Limit": {
        "what":  "7A ECUs (266B/D) only. The RPM threshold above which the ECU "
                 "disables closed-loop O2 correction. Works together with "
                 "CL Load Threshold: the ECU goes open-loop if EITHER this RPM "
                 "is exceeded OR the load falls below the per-RPM load threshold. "
                 "Raw × 25 = RPM.",
        "tips": [
            "Stock 7A: raw=244 → 6100 RPM. At this RPM the engine is near "
            "redline — closed-loop is active across almost the full rev range "
            "at cruise and part-throttle.",
            "On a tuned 7A with a remapped fuel map, lower this to 3000–4000 RPM "
            "(raw 120–160) so the ECU follows the fuel map precisely under power. "
            "Pair with CL Load Threshold for full control of the CL boundary.",
            "The CL Load Threshold table handles the load axis — the ECU goes "
            "open-loop if load drops below that table's value for the current "
            "RPM column, regardless of this RPM limit.",
            "CL correction is limited to a few percent trim. It cannot "
            "compensate for a significantly wrong fuel map — fix the map first.",
            "If the car hunts at idle, check idle fuel map cells before "
            "lowering this — the O2 sensor may be masking a lean idle map.",
        ],
        "caution": "Disabling CL at low RPM / light load on an otherwise "
                   "stock engine removes the O2 feedback that corrects for "
                   "injector wear and fuel sensor drift. Only lower this "
                   "once the fuel map is properly tuned.",
    },
    "CL Load Threshold": {
        "what":  "7A ECUs (266B/D) only. A 16-column table giving the MAP sensor "
                 "load level per RPM column below which closed-loop O2 correction "
                 "is active. Above this load the ECU follows the fuel map exactly. "
                 "Works together with CL RPM Limit — the ECU goes open-loop when "
                 "EITHER condition is met.",
        "tips": [
            "Lower threshold values = CL active over a wider load range at "
            "that RPM column.",
            "At WOT columns, set a high threshold so the ECU is always "
            "open-loop at full load — the fuel map should be followed exactly.",
            "On a modified engine, CL at light cruise is fine, but raise "
            "mid-load column thresholds so the fuel map is trusted under power.",
            "Edit this table together with CL RPM Limit for full control "
            "over when the ECU switches between open- and closed-loop.",
        ],
        "caution": None,
    },
    "CL Disable RPM": {
        "what":  "The RPM threshold above which the ECU permanently disables "
                 "closed-loop O2 (lambda) correction for that operating cycle. "
                 "Below this RPM, the ECU trims fuel based on the O2 sensor. "
                 "Above it, the fuel map values are used exactly as written. "
                 "Raw × 25 = RPM.",
        "tips": [
            "Stock AAH: raw=244 → 6100 RPM. The ECU is in open-loop for "
            "almost the entire rev range — the O2 sensor barely matters "
            "at high load.",
            "This value is unchanged between stock and Stage 1 AAH tunes "
            "(both raw=244), which makes sense: the Stage 1 tune remapped "
            "the entire fuel map and wants those values followed precisely.",
            "If you are running a wideband O2 and logging, you can raise "
            "this value to keep CL active higher in the rev range — useful "
            "while iterating on idle and cruise fuelling before a final burn.",
            "On a built engine with a big cam and lumpy idle, lower this to "
            "around 1500 RPM (raw≈60) to prevent the O2 sensor from fighting "
            "your idle enrichment cells.",
            "CL correction range is limited (±a few percent). This value "
            "cannot rescue a badly wrong fuel map — fix the map first.",
        ],
        "caution": "Leaving CL active at high RPM on a tuned engine can cause "
                   "the ECU to trim away your WOT enrichment. Always verify "
                   "your wideband AFRs at full load in open-loop.",
    },
    "RPM Limit": {
        "what":  "The rev limiter — ECU cuts injectors above this RPM. "
                 "Single byte: raw × 25 = RPM. "
                 "This is the classic first EPROM edit: one cell change, "
                 "burn the chip, and you'll feel the result immediately.",
        "tips": [
            "Stock 7A and AAH: raw=254 → 6350 RPM.",
            "Common first edit: raise to raw=255 (6375 RPM) — "
            "matches the factory tachometer redline on most cars.",
            "Stage 1 tunes typically use 245–255 depending on the build.",
            "Workflow: edit this cell → Save 27C512 → burn chip → install → test.",
            "If the engine hits the limiter cleanly and drops off sharply, "
            "the edit worked. No stumble = correct chip orientation and "
            "address decoding.",
        ],
        "caution": "The limiter protects the engine. Only raise it if the "
                   "valvetrain, head studs, and cooling system are in good "
                   "condition. Valve float typically begins around 7000 RPM "
                   "on a stock 7A/AAH.",
    },
    "Decel Cutoff": {
        "what":  "The MAP pressure threshold below which the ECU cuts "
                 "injectors during deceleration (overrun), per RPM. "
                 "Prevents fuel waste and exhaust popping.",
        "tips": [
            "Higher threshold = fuel cut active over a wider decel range.",
            "If the car surges or hunts on decel, lower the relevant RPM cells.",
            "If you want more exhaust pops / anti-lag feel, lower this "
            "to allow fuel on overrun.",
        ],
        "caution": None,
    },
    "Injection Scaler": {
        "what":  "A global multiplier on all injector pulse widths. "
                 "Intended for injector swaps: if you fit larger injectors, "
                 "lower this value so the ECU delivers the same fuel quantity "
                 "per map unit as before. Stock 7A/AAH = 100 (stock injectors). "
                 "Formula: new_scaler = 100 × (stock_cc / new_injector_cc).",
        "tips": [
            "Stock 7A (266B) and AAH injectors are ~205 cc/min. "
            "Example: fitting 410 cc/min injectors → set scaler to 50.",
            "266D (893 906 266 D) does not have an Injection Scaler byte — "
            "the injector pulse is fixed in the ECU firmware on that variant. "
            "Use the fuel map cells to adjust fuelling on a 266D.",
            "The MMS Stage 1 AAH tune uses scaler=50 with the fuel map values "
            "approximately doubled — this is a resolution trick, not a sign "
            "of bigger injectors. Halving the scaler and doubling the map gives "
            "finer 8-bit control over enrichment. Net WOT fuelling is richer "
            "(lambda ~0.69–0.87 vs stock ~1.0), but the scaler change alone "
            "tells you nothing about injector size.",
            "Do not change this value without also rescaling the entire fuel "
            "map. The two must always be changed together.",
            "Do not use this as a coarse richness trim — edit the fuel map "
            "cells directly instead.",
            "After any injector swap: new_scaler × new_cc ≈ 100 × 205. "
            "Start lean and richen the map; never start rich and lean down.",
        ],
        "caution": "Changing the scaler without rescaling the fuel map will "
                   "cause severe over- or under-fuelling across the entire "
                   "rev range. If in doubt, leave it at stock (100) and tune "
                   "using the fuel map only.  "
                   "Note: 266D does not expose this byte — tune via fuel map.",
    },
    "MAF Linearization": {
        "what":  "266B only. Lookup table that converts raw MAF sensor counts "
                 "to airflow. 64 × 16-bit big-endian entries.",
        "tips": [
            "This is a sensor characterisation table, not a tuning map.",
            "Only edit this if fitting a different MAF sensor body.",
            "Incorrect values cause systematic fuelling error across all RPM.",
        ],
        "caution": "Errors here affect every single fuel calculation. "
                   "Only modify if you have airflow bench data for the new sensor.",
    },
    "RPM Axis (Fuel)": {
        "what":  "The 16 RPM breakpoints that define the columns of the fuel map. "
                 "Raw × 25 = RPM.",
        "tips": [
            "Add more breakpoints in the region you care about (e.g. 2500-4000 "
            "for a forced-induction tune).",
            "Values must be strictly ascending.",
            "Changing axes shifts all existing map cells — re-verify the map "
            "after any axis edit.",
        ],
        "caution": None,
    },
    "Load Axis (Fuel)": {
        "what":  "The 16 MAP pressure breakpoints for the fuel map columns. "
                 "Raw × 0.3922 = kPa.",
        "tips": [
            "Higher load values extend the map into boost (for supercharged "
            "or turbocharged builds).",
            "Values must be strictly ascending.",
        ],
        "caution": None,
    },
    "RPM Axis (Timing)": {
        "what":  "The 16 RPM breakpoints for the timing maps. Raw × 25 = RPM. "
                 "Starts at 600 RPM (slightly different to fuel axis).",
        "tips": [
            "Keep timing and fuel axes aligned if possible — mismatched "
            "breakpoints make interpolation harder to reason about.",
        ],
        "caution": None,
    },
    "Load Axis (Timing)": {
        "what":  "The 16 MAP pressure breakpoints for the timing maps. "
                 "Raw × 0.3922 = kPa.",
        "tips": [
            "Same encoding as fuel load axis.",
            "Matching fuel and timing axes simplifies the tuning workflow.",
        ],
        "caution": None,
    },
}

_WELCOME_PANEL = {
    "what":  "Open a ROM file to begin. Supported formats: .bin (32KB), "
             ".034 (scrambled), or 64KB 27C512 image — all auto-detected.",
    "tips": [
        "New to EPROM tuning? Start with the RPM Limit tab — "
        "it's one cell, the result is immediate, and it teaches the "
        "whole edit → save → burn → test workflow.",
        "Double-click any cell to edit. Enter or Tab to confirm, Esc to cancel.",
        "Changed cells get a green border so you can track what moved.",
        "Save 27C512 .bin for EPROM programmers (TL866, T48, etc).",
        "Save .bin for the Teensy SD card. Checksum is corrected automatically.",
    ],
    "caution": None,
}

_COMPARE_PANEL = {
    "what":  "Side-by-side diff of two ROM files. Load a baseline (e.g. stock) "
             "and a modified ROM to see exactly which cells changed and by how much.",
    "tips": [
        "Load the original as ROM A, your edited version as ROM B.",
        "Cells shown in red/green indicate fuel or timing changes.",
        "Use this to document what a tune changed, or to sanity-check "
        "a ROM from an unknown source before flashing.",
    ],
    "caution": None,
}

_HEX_PANEL = {
    "what":  "Raw hex dump of the ROM. Shown when the variant could not be "
             "identified — all 32KB displayed for inspection.",
    "tips": [
        "You can still save an unknown ROM using the save buttons.",
        "Check the detection notes in the ROM Info panel below for clues "
        "about why identification failed.",
        "If this is a known ECU type, consider submitting the CRC32 "
        "to the HachiROM project so it can be added.",
    ],
    "caution": "Do not flash an unidentified ROM — verify the variant first.",
}


class MapInfoPanel(QWidget):
    """Top section of the right sidebar. Updates when the tab changes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Header: map name + address
        self.lbl_name = QLabel("HachiROM")
        self.lbl_name.setStyleSheet(
            "font-size:13px; font-weight:bold; color:#e0e0e0;")
        self.lbl_name.setWordWrap(True)
        layout.addWidget(self.lbl_name)

        self.lbl_addr = QLabel("")
        self.lbl_addr.setStyleSheet("font-size:10px; color:#888;")
        layout.addWidget(self.lbl_addr)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#333;")
        layout.addWidget(sep)

        # Description
        self.lbl_what = QLabel("")
        self.lbl_what.setWordWrap(True)
        self.lbl_what.setStyleSheet("font-size:11px; color:#ccc; padding:2px 0;")
        layout.addWidget(self.lbl_what)

        # Tips
        self.lbl_tips_hdr = QLabel("Tuning tips")
        self.lbl_tips_hdr.setStyleSheet(
            "font-size:10px; font-weight:bold; color:#aaa; margin-top:6px;")
        layout.addWidget(self.lbl_tips_hdr)

        self.lbl_tips = QLabel("")
        self.lbl_tips.setWordWrap(True)
        self.lbl_tips.setStyleSheet("font-size:11px; color:#bbb;")
        layout.addWidget(self.lbl_tips)

        # Caution
        self.lbl_caution = QLabel("")
        self.lbl_caution.setWordWrap(True)
        self.lbl_caution.setStyleSheet(
            "font-size:11px; color:#ff9900; "
            "background:#2a1a00; border-radius:4px; padding:4px 6px;")
        self.lbl_caution.hide()
        layout.addWidget(self.lbl_caution)

        layout.addStretch()

    def update_map(self, name: str, map_def=None, info: dict | None = None):
        """Show description and tips for the given map tab.

        info: one of _MAP_TIPS[name], _WELCOME_PANEL, _COMPARE_PANEL, _HEX_PANEL.
        If not provided, falls back to _MAP_TIPS lookup, then a generic placeholder.
        """
        if info is None:
            info = _MAP_TIPS.get(name, {})

        self.lbl_name.setText(name)

        if map_def is not None:
            shape = (f"0x{map_def.address:04X}  ·  "
                     f"{map_def.rows}×{map_def.cols}  ·  "
                     f"{map_def.size}B  ·  {map_def.unit or 'raw'}")
            self.lbl_addr.setText(shape)
            self.lbl_addr.show()
        else:
            self.lbl_addr.hide()

        what = info.get("what", "")
        self.lbl_what.setText(what)
        self.lbl_what.setVisible(bool(what))

        tips = info.get("tips", [])
        if tips:
            self.lbl_tips.setText("\n".join(f"• {t}" for t in tips))
            self.lbl_tips.show()
            self.lbl_tips_hdr.show()
        else:
            self.lbl_tips.hide()
            self.lbl_tips_hdr.hide()

        caution = info.get("caution")
        if caution:
            self.lbl_caution.setText(f"⚠  {caution}")
            self.lbl_caution.show()
        else:
            self.lbl_caution.hide()


class ROMInfoWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 4)

        hdr = QLabel("ROM Info")
        hdr.setStyleSheet(
            "font-size:10px; font-weight:bold; color:#aaa; padding:2px 0;")
        layout.addWidget(hdr)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(QFont("Consolas", 9))
        layout.addWidget(self.text)

    def update_rom(self, data: bytes):
        result = hr.detect(data)
        lines  = ["=== ROM Detection ==="]
        if result.variant:
            v      = result.variant
            cs_sum = hr.compute_sum(data)
            cs_tgt = v.checksum.get("target", 0)
            cs_ok  = cs_sum == cs_tgt
            lines += [
                f"Variant      : {v.name}",
                f"Part Number  : {v.part_number}",
                f"Chip         : {v.chip}",
                f"Confidence   : {result.confidence}",
                f"Size         : {result.size} bytes",
                f"CRC32        : {result.crc32:#010x}",
                f"SHA256       : {result.sha256[:32]}…",
                "",
                "=== Checksum ===",
                f"Status       : {'✓ VALID' if cs_ok else '⚠ INVALID'}",
                f"Byte sum     : {cs_sum:,}",
                f"Target       : {cs_tgt:,}",
            ]
            if not cs_ok:
                lines.append(f"Delta        : {cs_sum - cs_tgt:+,}")
            lines += ["", "=== Map Addresses ===",
                      f"  {'NAME':<28} {'ADDR':>6}  {'SIZE':>5}  TYPE",
                      "  " + "-" * 52]
            for m in v.maps:
                t = ("scalar" if m.is_scalar else
                     f"{m.rows}×{m.cols}" if m.is_2d else f"1×{m.cols}")
                lines.append(f"  {m.name:<28} 0x{m.address:04X}  {m.size:>4}B  {t}")
        else:
            lines += [
                "Variant      : UNKNOWN",
                f"Size         : {result.size} bytes",
                f"CRC32        : {result.crc32:#010x}",
                f"SHA256       : {result.sha256[:32]}…",
            ]
        if result.notes:
            lines.append("")
            lines += [f"  ⚑ {n}" for n in result.notes]
        self.text.setPlainText("\n".join(lines))


# ---------------------------------------------------------------------------
# Hex viewer — shown for unknown/unrecognised ROMs
# ---------------------------------------------------------------------------

class HexViewTab(QWidget):
    """Live hex view of the assembled working ROM.

    Always present as the last tab (for both recognised and unknown ROMs).
    Shows the result of _build_rom() — snapshot + all current edits +
    checksum correction — so what you see is exactly what will be saved.

    For unrecognised ROMs, falls back to showing the raw snapshot.
    Refreshed lazily: only when the tab is activated, or when refresh()
    is called after an edit.

    Raw hex editing is intentionally not implemented here — edits belong
    in the map tabs where context (axis labels, units, colour scale) makes
    them safe. The hex view is read-only diagnostic output.
    """

    BYTES_PER_ROW = 16

    def __init__(self, get_rom_bytes, unrecognised: bool = False, parent=None):
        """
        get_rom_bytes : callable() -> bytearray | bytes
            Called each time the view needs to refresh. Typically
            MainWindow._build_rom for recognised ROMs, or a lambda returning
            _rom_snapshot for unrecognised ones.
        unrecognised  : if True, show the "variant not recognised" warning.
        """
        super().__init__(parent)
        self._get_rom_bytes  = get_rom_bytes
        self._dirty          = True   # needs a render on next activation
        self._last_hash      = None   # avoid redundant re-renders

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # ── header bar ────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        self._lbl_info = QLabel("32 KB  ·  0x0000 – 0x7FFF  ·  read-only view of working ROM")
        self._lbl_info.setStyleSheet("color:#666; font-size:10px;")
        hdr.addWidget(self._lbl_info)
        hdr.addStretch()
        btn_refresh = QPushButton("↺ Refresh")
        btn_refresh.setFixedWidth(80)
        btn_refresh.setStyleSheet(
            "QPushButton { background:#2a2a2a; color:#888; border:1px solid #333; "
            "border-radius:3px; padding:2px 8px; font-size:11px; }"
            "QPushButton:hover { color:#ccc; border-color:#555; }")
        btn_refresh.clicked.connect(self.refresh)
        hdr.addWidget(btn_refresh)
        layout.addLayout(hdr)

        if unrecognised:
            warn = QLabel(
                "⚠  ROM variant not recognised — showing raw snapshot.  "
                "You can still save this file using Save .bin… or Save 27C512 .bin…")
            warn.setStyleSheet("color:#ff9900; font-size:11px; padding:2px 0 4px 0;")
            warn.setWordWrap(True)
            layout.addWidget(warn)

        # ── hex view ──────────────────────────────────────────────────────
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QFont("Consolas", 9))
        self.view.setStyleSheet(
            "background:#111; color:#ccc; border:1px solid #2a2a2a;")
        layout.addWidget(self.view)

    def refresh(self):
        """Re-render from get_rom_bytes(). Called on tab activation or after edits."""
        self._dirty = False   # clear regardless — we're refreshing now
        data = bytes(self._get_rom_bytes())[:32768]
        h    = hash(data)
        if h == self._last_hash:
            return   # nothing changed, skip expensive re-render
        self._last_hash = h

        bpr   = self.BYTES_PER_ROW
        lines = [
            f"{'ADDR':<6}  {'00 01 02 03 04 05 06 07  08 09 0A 0B 0C 0D 0E 0F':<50}  ASCII"
        ]
        lines.append("─" * 70)
        for i in range(0, len(data), bpr):
            chunk = data[i:i + bpr]
            # split into two groups of 8 with extra space between them
            h1 = " ".join(f"{b:02X}" for b in chunk[:8])
            h2 = " ".join(f"{b:02X}" for b in chunk[8:])
            hex_s = f"{h1:<23}  {h2:<23}"
            asc_s = "".join(chr(b) if 32 <= b < 127 else "·" for b in chunk)
            lines.append(f"{i:04X}:  {hex_s}  {asc_s}")

        self.view.setPlainText("\n".join(lines))
        sz = len(data)
        self._lbl_info.setText(
            f"{sz:,} bytes ({sz//1024} KB)  ·  0x0000 – 0x{sz-1:04X}  ·  "
            f"read-only · shows assembled working ROM (edits + checksum)")

    def mark_dirty(self):
        """Signal that the underlying ROM has changed; refresh on next activation."""
        self._dirty = True


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"HachiROM  v{APP_VERSION}")
        self.resize(1280, 820)
        self.current_path:    str = ""
        self.current_variant  = None
        self._rom_snapshot:   bytes = b""   # original ROM bytes at open time — never mutated
        self._map_tabs:       list[MapTab] = []
        self._overview_tab:  OverviewTab | None = None
        self._hex_tab:       HexViewTab | None = None
        self._compare_tab_idx: int = -1
        self._build_menu()
        self._build_ui()
        self._apply_dark_theme()

    # ── Menu ─────────────────────────────────────────────────────────────────

    def _build_menu(self):
        mb = self.menuBar()
        fm = mb.addMenu("File")
        for label, shortcut, slot in [
            ("Open ROM…",            "Ctrl+O",       self.open_rom),
            ("Save ROM…",            "Ctrl+S",       self.save_rom),
            ("Save as 27C512 .bin…", "Ctrl+Shift+S", self.save_27c512),
        ]:
            act = QAction(label, self)
            act.setShortcut(shortcut)
            act.triggered.connect(slot)
            fm.addAction(act)
        fm.addSeparator()
        fm.addAction("Quit", self.close)
        hm = mb.addMenu("Help")
        hm.addAction("About HachiROM", self._about)

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 4, 8, 4)
        root.setSpacing(4)

        top = QHBoxLayout()
        self.lbl_file = QLabel(
            "No ROM loaded — File → Open ROM…  (accepts .bin and .034)")
        self.lbl_file.setStyleSheet("color:#666; font-size:11px;")

        btn_open = QPushButton("Open ROM…")
        btn_open.clicked.connect(self.open_rom)


        self.btn_save = QPushButton("Save .bin…")
        self.btn_save.clicked.connect(self.save_rom)
        self.btn_save.setEnabled(False)

        self.btn_save512 = QPushButton("Save 27C512 .bin…")
        self.btn_save512.setToolTip(
            "64KB image for EPROM programmers\n"
            "Lower 32KB = 0xFF pad  |  Upper 32KB = ROM data")
        self.btn_save512.clicked.connect(self.save_27c512)
        self.btn_save512.setEnabled(False)

        self.btn_maf = QPushButton("MAF Patch…")
        self.btn_maf.setToolTip(
            "Patch MAF sensor axis tables for a different housing\n"
            "(266D / 7A Late only)")
        self.btn_maf.clicked.connect(self.open_maf_patch)
        self.btn_maf.setEnabled(False)
        self.btn_maf.setStyleSheet(
            "QPushButton { background:#2a1a00; color:#ff9900; border:1px solid #664400; "
            "padding:5px 14px; border-radius:3px; }"
            "QPushButton:hover { background:#3d2700; }"
            "QPushButton:disabled { background:#1e1e1e; color:#444; border-color:#333; }")

        top.addWidget(self.lbl_file, 1)
        top.addWidget(btn_open)
        top.addWidget(self.btn_save)
        top.addWidget(self.btn_save512)
        top.addWidget(self.btn_maf)
        root.addLayout(top)

        splitter = QSplitter(Qt.Horizontal)
        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.currentChanged.connect(self._maybe_refresh_hex)
        splitter.addWidget(self.tabs)

        # Right sidebar: map context panel (top) + ROM info (bottom)
        sidebar        = QWidget()
        sb_layout      = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.setSpacing(0)
        self.map_panel  = MapInfoPanel()
        self.info_panel = ROMInfoWidget()
        sb_splitter     = QSplitter(Qt.Vertical)
        sb_splitter.addWidget(self.map_panel)
        sb_splitter.addWidget(self.info_panel)
        sb_splitter.setSizes([340, 420])
        sb_layout.addWidget(sb_splitter)

        splitter.addWidget(sidebar)
        splitter.setSizes([900, 380])
        root.addWidget(splitter, 1)

        welcome = QLabel(
            f"HachiROM  v{APP_VERSION}\n\n"
            "Open a .bin or .034 ROM file to begin.\n\n"
            "Supported ECUs:\n"
            "  893906266D — 7A Late  (Audi 90 / Coupe Quattro 2.3 20v, 4-connector)\n"
            "  893906266B — 7A Early (Audi 90 / Coupe Quattro 2.3 20v, 2-connector)\n"
            "  4A0906266  — AAH 12v  (Audi 100 C4 2.8 12v)\n\n"
            "Double-click any map cell to edit.\n"
            "Changed cells get a green border.  Save when ready."
        )
        welcome.setAlignment(Qt.AlignCenter)
        welcome.setStyleSheet("color:#555; font-size:13px;")
        self.tabs.addTab(welcome, "Welcome")

        self.compare_tab = CompareTab()
        self._compare_tab_idx = self.tabs.addTab(self.compare_tab, "⊕ Compare")

        self.statusBar().showMessage(f"HachiROM v{APP_VERSION} ready")

    # ── ROM open ──────────────────────────────────────────────────────────────

    # -- Tab change -> update map info panel ------------------------------------

    def _on_rom_changed(self):
        """Called whenever any map tab or overview field commits an edit.
        Marks the hex tab dirty so it refreshes on next activation."""
        if self._hex_tab:
            self._hex_tab.mark_dirty()

    def _maybe_refresh_hex(self, index: int):
        """Refresh the hex tab when the user switches to it."""
        if self._hex_tab and self.tabs.widget(index) is self._hex_tab:
            self._hex_tab.refresh()

    def _on_tab_changed(self, index: int):
        if index < 0:
            return
        widget = self.tabs.widget(index)
        name   = self.tabs.tabText(index)

        if isinstance(widget, MapTab):
            self.map_panel.update_map(
                widget.map_def.name,
                map_def=widget.map_def,
                info=_MAP_TIPS.get(widget.map_def.name),
            )
        elif "Compare" in name:
            self.map_panel.update_map("Compare", info=_COMPARE_PANEL)
        elif "Hex" in name:
            self.map_panel.update_map("Hex Dump", info=_HEX_PANEL)
        else:
            self.map_panel.update_map("HachiROM", info=_WELCOME_PANEL)

    def open_rom(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open ROM", "",
            "ROM Files (*.bin *.034);;Binary (*.bin);;034 (*.034);;All Files (*)")
        if not path:
            return
        try:
            raw_size = Path(path).stat().st_size
            rom32, load_notes = hr.load_bin_normalised(path)

            # If normalisation did something non-trivial, tell the user
            if load_notes:
                msg = "\n".join(f"• {n}" for n in load_notes)
                QMessageBox.information(
                    self, "File Normalised",
                    f"The file was adjusted before loading:\n\n{msg}\n\n"
                    f"Original size: {raw_size:,} bytes  →  working with 32KB ROM.")

            self._rom_snapshot = bytes(rom32)
            self.current_path  = path
            self._load_rom(path)
        except Exception as e:
            QMessageBox.critical(self, "Open Error", str(e))

    def _load_rom(self, path: str):
        data   = self._rom_snapshot
        result = hr.detect(data)
        self.current_variant = result.variant

        variant_name = result.variant.name if result.variant else "Unknown variant"
        cs_ok = hr.verify_checksum(data, result.variant) if result.variant else False
        self.lbl_file.setText(
            f"{Path(path).name}  ·  {variant_name}  ·  "
            f"CRC32 {result.crc32:#010x}  ·  "
            f"{'✓ checksum OK' if cs_ok else '⚠ checksum invalid'}")
        self.lbl_file.setStyleSheet(
            "color:#2dff6e; font-size:11px;" if cs_ok
            else "color:#ff9900; font-size:11px;")

        self.btn_save.setEnabled(True)
        self.btn_save512.setEnabled(True)

        # MAF patch button — 266D only
        is_266d = (result.variant and result.variant.version_key == "266D")
        self.btn_maf.setEnabled(bool(is_266d))
        if is_266d:
            maf_key = hr.detect_maf_patch(data)
            maf_profile = hr.MAF_PROFILES.get(maf_key, {})
            maf_label   = maf_profile.get("label", maf_key)
            self.btn_maf.setText(f"MAF: {maf_label} ▾")
            self.btn_maf.setToolTip(
                f"Current sensor axis: {maf_label}\n"
                f"Click to patch for a different MAF housing.")
        else:
            self.btn_maf.setText("MAF Patch…")

        while self.tabs.count():
            self.tabs.removeTab(0)
        self._map_tabs = []
        self._overview_tab = None
        self._hex_tab = None

        if result.variant:
            # Overview tab — always first
            self._overview_tab = OverviewTab(result.variant, self._rom_snapshot)
            for field in self._overview_tab._fields:
                field.changed.connect(self._on_rom_changed)
            self._overview_tab.show_first_tip()
            self.tabs.insertTab(0, self._overview_tab, "Overview")

            editable = [m for m in result.variant.maps
                        if m.is_2d or (m.cols > 1
                            and not m.name.lower().startswith("rpm")
                            and not m.name.lower().startswith("load"))]
            for m in editable:
                tab = MapTab(m, self._rom_snapshot)
                tab.rom_changed.connect(self._on_rom_changed)
                self._map_tabs.append(tab)
                self.tabs.addTab(tab, m.name)
        else:
            self._overview_tab = None

        self.compare_tab = CompareTab()
        self._compare_tab_idx = self.tabs.addTab(self.compare_tab, "⊕ Compare")

        # Hex tab — always last, shows assembled working ROM (edits + checksum)
        self._hex_tab = HexViewTab(
            self._build_rom if result.variant else (lambda: self._rom_snapshot),
            unrecognised=not bool(result.variant))
        self.tabs.addTab(self._hex_tab, "⬡ Hex")

        self.info_panel.update_rom(self._rom_snapshot)
        self.statusBar().showMessage(
            f"Loaded {Path(path).name}  ·  {variant_name}  ·  "
            f"confidence: {result.confidence}")

    # ── Save helpers ──────────────────────────────────────────────────────────

    def _build_rom(self) -> bytearray:
        """Assemble current ROM from snapshot + in-memory edits, then apply
        checksum correction. Nothing is mutated until this is called."""
        rom = bytearray(self._rom_snapshot[:32768])
        # Overview tab fields take priority — apply first, map tabs may overlap
        if self._overview_tab:
            for offset, byte in self._overview_tab.build_patches().items():
                if offset < len(rom):
                    rom[offset] = byte
        for tab in self._map_tabs:
            for offset, byte in tab.build_patch().items():
                if offset < len(rom):
                    rom[offset] = byte
        if self.current_variant:
            return hr.apply_checksum(bytes(rom), self.current_variant)
        return rom

    def save_rom(self):
        """Save 32KB .bin — assembles from in-memory edits, corrects checksum."""
        if not self._rom_snapshot:
            QMessageBox.warning(self, "HachiROM", "No ROM loaded.")
            return

        base    = Path(self.current_path).stem if self.current_path else "rom"
        parent  = str(Path(self.current_path).parent) if self.current_path else ""
        default = str(Path(parent) / (base + "_edited.bin")) if parent else base + "_edited.bin"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save 32KB ROM", default,
            "Binary ROM Files (*.bin);;All Files (*)")
        if not path:
            return

        try:
            rom32 = self._build_rom()
            if self.current_variant:
                dlg = SaveConfirmDialog(
                    bytes(rom32), self.current_variant, path, parent=self)
                if dlg.exec_() != QDialog.Accepted:
                    return
            hr.save_bin(bytes(rom32), path)
            self.statusBar().showMessage(f"Saved → {Path(path).name}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

    def save_27c512(self):
        """Save 64KB 27C512 image — edits applied, checksum corrected, mirrored."""
        if not self._rom_snapshot:
            QMessageBox.warning(self, "HachiROM", "No ROM loaded.")
            return

        base    = Path(self.current_path).stem if self.current_path else "rom"
        parent  = str(Path(self.current_path).parent) if self.current_path else ""
        default = str(Path(parent) / (base + "_27C512.bin")) if parent else base + "_27C512.bin"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save 27C512 Image", default,
            "Binary ROM Files (*.bin);;All Files (*)")
        if not path:
            return

        try:
            rom32 = bytes(self._build_rom())
            image = rom32 + rom32
            hr.save_bin(image, path)
            self.statusBar().showMessage(
                f"Saved 27C512 \u2192 {Path(path).name}  (64 KB, mirrored, checksum corrected)")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

    # ── MAF patch ─────────────────────────────────────────────────────────────

    def open_maf_patch(self):
        """Open the MAF sensor patch dialog and apply the chosen profile."""
        if not self._rom_snapshot:
            return
        if not (self.current_variant and self.current_variant.version_key == "266D"):
            QMessageBox.information(
                self, "MAF Patch",
                "MAF axis patching is only supported for the 266D (7A Late) ECU.")
            return

        dlg = MafPatchDialog(self._rom_snapshot, parent=self)
        if dlg.exec_() != QDialog.Accepted:
            return

        profile_key = dlg.selected_profile()
        try:
            patched = hr.apply_maf_patch(self._rom_snapshot, profile_key)
        except Exception as e:
            QMessageBox.critical(self, "MAF Patch Error", str(e))
            return

        # Reload the patched data as the new working snapshot.
        # This is a deliberate full reload so all open map tabs, the hex view,
        # and the overview panel reflect the new axis values immediately.
        self._rom_snapshot = patched
        self._load_rom(self.current_path)

        profile = hr.MAF_PROFILES[profile_key]
        msg = (f"MAF axis patched to:\n{profile['label']}\n\n"
               f"{profile['housing']}\n{profile['hp_note']}")
        if not profile["co_pot"]:
            msg += (
                "\n\n⚠  Hardware action required:\n"
                "This sensor has no CO pot (wire 4).\n"
                "Solder a 10 kΩ / 10 kΩ voltage divider from ECU 5 V ref\n"
                "to GND and connect the midpoint (2.5 V) to ECU pin 4.\n"
                "Do NOT leave pin 4 floating.")
        QMessageBox.information(self, "MAF Patch Applied", msg)

    # ── Misc ─────────────────────────────────────────────────────────────────

    def _about(self):
        QMessageBox.about(self, f"HachiROM v{APP_VERSION}",
            f"<b>HachiROM  v{APP_VERSION}</b><br>"
            "Hitachi ECU ROM editor for 7A 20v and AAH 12v<br><br>"
            "Standalone — no Teensy or serial connection required.<br><br>"
            "<a href='https://github.com/dspl1236/HachiROM'>"
            "github.com/dspl1236/HachiROM</a>")

    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color:#1e1e1e; color:#d4d4d4;
                font-family:'Segoe UI',Arial,sans-serif; font-size:12px;
            }
            QTabWidget::pane { border:1px solid #333; background:#1e1e1e; }
            QTabBar::tab {
                background:#2d2d2d; color:#888; padding:6px 14px; border:1px solid #333;
            }
            QTabBar::tab:selected {
                background:#1e1e1e; color:#fff; border-bottom:2px solid #007acc;
            }
            QTabBar::tab:hover { color:#ccc; background:#333; }
            QPushButton {
                background:#0e639c; color:#fff; border:none;
                padding:5px 14px; border-radius:3px;
            }
            QPushButton:hover  { background:#1177bb; }
            QPushButton:disabled { background:#2d2d2d; color:#555; }
            QTableWidget { gridline-color:#333; background:#252526; border:none; }
            QTableWidget QLineEdit {
                background:#3c3c3c; color:#fff; border:1px solid #007acc; padding:1px;
            }
            QHeaderView::section {
                background:#2d2d2d; color:#888;
                border:1px solid #333; padding:3px; font-size:10px;
            }
            QTextEdit {
                background:#1e1e1e; color:#d4d4d4; border:1px solid #333;
                font-family:'Consolas',monospace;
            }
            QSplitter::handle { background:#333; }
            QMenuBar { background:#2d2d2d; color:#d4d4d4; }
            QMenuBar::item:selected { background:#094771; }
            QMenu { background:#2d2d2d; color:#d4d4d4; border:1px solid #333; }
            QMenu::item:selected { background:#094771; }
            QStatusBar { background:#007acc; color:#fff; font-size:11px; }
            QLabel { color:#d4d4d4; }
        """)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("HachiROM")
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()


