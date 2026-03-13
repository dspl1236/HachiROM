"""
HachiROM — Desktop GUI
Cross-platform PyQt5 map editor / compare tool for Hitachi ECU ROMs.
Standalone — no Teensy or serial connection required.
"""

import sys
import os
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QTableWidget, QTableWidgetItem, QStatusBar, QMessageBox,
    QTextEdit, QSplitter, QAction, QHeaderView, QDialog,
    QDialogButtonBox, QFrame
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QBrush

sys.path.insert(0, str(Path(__file__).parent.parent))
import hachirom as hr
from hachirom.bridge import get_variant

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
    return heat_colour(max(lo, min(hi, signed)), lo, hi)


# ---------------------------------------------------------------------------
# Save confirmation dialog
# ---------------------------------------------------------------------------

class SaveConfirmDialog(QDialog):
    """Shows checksum status and what will be written before saving."""

    def __init__(self, data: bytes, variant, path: str,
                 mode: str = "bin", parent=None):
        """
        mode: "bin"   — save 32KB native ROM
              "27c512" — save 64KB image (32KB 0xFF pad + 32KB ROM in upper half)
        """
        super().__init__(parent)
        self.mode = mode
        self.setWindowTitle("Confirm Save")
        self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # ── Checksum status ──────────────────────────────────────────────
        cs_sum = hr.compute_sum(data)
        cs_tgt = variant.checksum.get("target", 0)
        cs_ok  = cs_sum == cs_tgt
        delta  = cs_sum - cs_tgt

        cs_colour = "#2dff6e" if cs_ok else "#ff9900"
        cs_text   = "✓  VALID" if cs_ok else f"⚠  INVALID  (delta {delta:+,})"

        cs_box = QFrame()
        cs_box.setStyleSheet(
            f"background:#111; border:1px solid {cs_colour}; padding:6px; border-radius:3px;")
        cs_lay = QVBoxLayout(cs_box)
        cs_lay.setSpacing(2)

        def row(label, value, colour="#d4d4d4"):
            lbl = QLabel(f"<b style='color:#888'>{label}</b>  "
                         f"<span style='color:{colour}'>{value}</span>")
            lbl.setTextFormat(Qt.RichText)
            cs_lay.addWidget(lbl)

        row("Checksum",    cs_text,                cs_colour)
        row("Byte sum",    f"{cs_sum:,}")
        row("Target",      f"{cs_tgt:,}")
        if not cs_ok:
            row("Delta",   f"{delta:+,}",          "#ff9900")

        layout.addWidget(QLabel("<b>Checksum</b>", styleSheet="color:#aaa;"))
        layout.addWidget(cs_box)

        # ── Auto-fix notice ──────────────────────────────────────────────
        if not cs_ok:
            notice = QLabel(
                "⚙  Checksum will be corrected automatically before writing.\n"
                f"    {abs(delta)} byte(s) adjusted in correction region "
                f"(0x{variant.checksum['cs_from']:04X}–"
                f"0x{variant.checksum['cs_to']:04X})."
            )
            notice.setStyleSheet("color:#ff9900; font-size:11px; padding:4px 0;")
            notice.setWordWrap(True)
            layout.addWidget(notice)

        # ── File info ────────────────────────────────────────────────────
        layout.addWidget(QLabel("<b>Output file</b>", styleSheet="color:#aaa;"))
        file_box = QFrame()
        file_box.setStyleSheet("background:#111; border:1px solid #333; padding:6px; border-radius:3px;")
        file_lay = QVBoxLayout(file_box)
        file_lay.setSpacing(2)

        if mode == "27c512":
            size_str  = "65,536 bytes (64 KB)"
            note_str  = "Lower 32KB: 0xFF (erased)  |  Upper 32KB: ROM data"
        else:
            size_str  = f"{len(data):,} bytes ({len(data)//1024} KB)"
            note_str  = "Native 32KB ROM — ready for Teensy SD card"

        def frow(label, value):
            lbl = QLabel(f"<b style='color:#888'>{label}</b>  "
                         f"<span style='color:#d4d4d4'>{value}</span>")
            lbl.setTextFormat(Qt.RichText)
            file_lay.addWidget(lbl)

        frow("Path",   Path(path).name)
        frow("Size",   size_str)
        frow("Format", note_str)
        frow("ECU",    f"{variant.name}  ({variant.part_number})")
        layout.addWidget(file_box)

        # ── Buttons ──────────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        save_btn = btns.button(QDialogButtonBox.Save)
        save_btn.setText("Save" if cs_ok else "Fix Checksum & Save")
        save_btn.setStyleSheet(
            "QPushButton { background:#0e639c; color:#fff; padding:5px 16px; border:none; border-radius:3px; }"
            "QPushButton:hover { background:#1177bb; }"
        )
        layout.addWidget(btns)

        self.setStyleSheet("""
            QDialog { background:#1e1e1e; color:#d4d4d4; }
            QLabel  { color:#d4d4d4; font-size:12px; }
            QDialogButtonBox QPushButton {
                background:#333; color:#d4d4d4; padding:5px 14px;
                border:1px solid #555; border-radius:3px;
            }
            QDialogButtonBox QPushButton:hover { background:#444; }
        """)


# ---------------------------------------------------------------------------
# Map tab — heatmap table with editable cells
# ---------------------------------------------------------------------------

class MapTab(QWidget):
    def __init__(self, map_def, rom_data: bytearray, parent=None):
        """
        rom_data is the shared bytearray for the whole ROM — edits write
        directly into it so the parent window can collect changes on save.
        """
        super().__init__(parent)
        self.map_def   = map_def
        self.rom_data  = rom_data          # shared reference — edits go here
        self._is_timing = any(k in map_def.name.lower()
                              for k in ("timing", "knock"))
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        addr_str = f"0x{self.map_def.address:04X}"
        dims = (f"{self.map_def.rows}×{self.map_def.cols}"
                if self.map_def.is_2d else f"1×{self.map_def.cols}")
        info = QLabel(
            f"<b>{self.map_def.name}</b>  ·  "
            f"Addr: <code>{addr_str}</code>  ·  {dims}  ·  "
            f"{self.map_def.unit or ''}  —  {self.map_def.description}"
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#aaa; font-size:11px; padding:2px 0;")

        hint = QLabel("Double-click a cell to edit · Enter to confirm · Esc to cancel")
        hint.setStyleSheet("color:#555; font-size:10px;")

        header = QHBoxLayout()
        header.addWidget(info, 1)
        header.addWidget(hint)
        layout.addLayout(header)

        self.table = QTableWidget(self.map_def.rows, self.map_def.cols)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setFont(QFont("Consolas", 9))
        # Editable on double-click
        self.table.setEditTriggers(
            QTableWidget.DoubleClicked | QTableWidget.SelectedClicked)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.itemChanged.connect(self._on_cell_changed)
        layout.addWidget(self.table)

        # Axis labels
        if self.map_def.rpm_axis:
            self.table.setVerticalHeaderLabels(
                [str(v) for v in self.map_def.rpm_axis[:self.map_def.rows]])
        if self.map_def.load_axis:
            self.table.setHorizontalHeaderLabels(
                [str(v) for v in self.map_def.load_axis[:self.map_def.cols]])

        self._refresh()

    def _refresh(self):
        self.table.blockSignals(True)
        raw     = hr.read_map(bytes(self.rom_data), self.map_def)
        decoded = hr.read_map_decoded(bytes(self.rom_data), self.map_def)

        all_raw = [v for row in raw for v in row]
        vmin, vmax = min(all_raw), max(all_raw)

        for r in range(self.map_def.rows):
            for c in range(self.map_def.cols):
                raw_v = raw[r][c]
                dec_v = decoded[r][c]
                text  = f"{dec_v:.3f}" if isinstance(dec_v, float) else str(dec_v)

                item = self.table.item(r, c) or QTableWidgetItem()
                item.setText(text)
                item.setTextAlignment(Qt.AlignCenter)

                colour = (timing_colour(raw_v) if self._is_timing
                          else heat_colour(raw_v, vmin, vmax))
                item.setBackground(QBrush(colour))
                brightness = (colour.red() * 0.299 + colour.green() * 0.587
                              + colour.blue() * 0.114)
                item.setForeground(QBrush(
                    QColor("#111") if brightness > 140 else QColor("#eee")))

                if self._is_timing:
                    signed = raw_v if raw_v < 128 else raw_v - 256
                    item.setToolTip(f"raw={raw_v}  →  {signed:+d}° BTDC")

                self.table.setItem(r, c, item)
        self.table.blockSignals(False)

    def _on_cell_changed(self, item: QTableWidgetItem):
        r, c = item.row(), item.column()
        addr = self.map_def.address + r * self.map_def.cols + c

        # Determine raw byte from text
        m = self.map_def
        try:
            text = item.text().strip()
            if m.encode:
                # Parse as display value then encode
                raw = m.encode(float(text))
            else:
                # Accept negative timing input — wrap to uint8
                v = int(float(text))
                if self._is_timing and v < 0:
                    v = v & 0xFF
                raw = max(0, min(255, v))
        except (ValueError, TypeError):
            # Bad input — revert to ROM value
            self._refresh()
            return

        # Write into shared rom_data
        if 0 <= addr < len(self.rom_data):
            self.rom_data[addr] = raw

        # Recolour this cell only (don't re-read whole map — avoids signal loop)
        self.table.blockSignals(True)
        colour = (timing_colour(raw) if self._is_timing
                  else heat_colour(raw, 0, 255))
        item.setBackground(QBrush(colour))
        brightness = (colour.red() * 0.299 + colour.green() * 0.587
                      + colour.blue() * 0.114)
        item.setForeground(QBrush(
            QColor("#111") if brightness > 140 else QColor("#eee")))
        if self._is_timing:
            signed = raw if raw < 128 else raw - 256
            item.setToolTip(f"raw={raw}  →  {signed:+d}° BTDC")
        self.table.blockSignals(False)


# ---------------------------------------------------------------------------
# Compare tab
# ---------------------------------------------------------------------------

class CompareTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data_a: bytes = b""
        self.data_b: bytes = b""
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
        btn_cmp.clicked.connect(self._run_compare)
        load_row.addWidget(btn_a)
        load_row.addWidget(self.lbl_a, 1)
        load_row.addWidget(btn_b)
        load_row.addWidget(self.lbl_b, 1)
        load_row.addWidget(btn_cmp)
        layout.addLayout(load_row)

        self.result = QTextEdit()
        self.result.setReadOnly(True)
        self.result.setFont(QFont("Consolas", 9))
        self.result.setPlaceholderText("Load two ROMs and click Compare.")
        layout.addWidget(self.result)

    def _load_rom_file(self, title):
        path, _ = QFileDialog.getOpenFileName(
            self, title, "", "ROM Files (*.bin *.034);;All Files (*)")
        if not path:
            return None, None
        data = hr.load_bin(path)
        if path.lower().endswith(".034"):
            data = hr.unscramble_034(data)
        return data, path

    def _load_a(self):
        data, path = self._load_rom_file("Load ROM A")
        if data is None:
            return
        self.data_a = data
        r = hr.detect(data)
        name = Path(path).name
        variant = r.variant.name if r.variant else "Unknown"
        self.lbl_a.setText(f"ROM A: {name}  [{variant}  {r.crc32:#010x}]")
        self.lbl_a.setStyleSheet("color:#2dff6e; font-size:11px;")

    def _load_b(self):
        data, path = self._load_rom_file("Load ROM B")
        if data is None:
            return
        self.data_b = data
        r = hr.detect(data)
        name = Path(path).name
        variant = r.variant.name if r.variant else "Unknown"
        self.lbl_b.setText(f"ROM B: {name}  [{variant}  {r.crc32:#010x}]")
        self.lbl_b.setStyleSheet("color:#00d4ff; font-size:11px;")

    def _run_compare(self):
        if not self.data_a or not self.data_b:
            QMessageBox.warning(self, "HachiROM", "Load both ROMs first.")
            return

        result_a = hr.detect(self.data_a)
        diffs    = hr.compare_roms(self.data_a, self.data_b, result_a.variant)
        summary  = hr.diff_summary(diffs)

        lines = [f"ROM COMPARE — {len(diffs)} byte(s) differ", ""]
        if summary:
            lines.append("CHANGED BYTES BY MAP REGION")
            lines.append("-" * 50)
            for region, count in sorted(summary.items(), key=lambda x: -x[1]):
                bar = "█" * min(count, 30)
                lines.append(f"  {region:<34} {count:>4}  {bar}")
            lines.append("")

        lines.append(f"  {'ADDR':>6}  {'A':>3}  {'B':>3}  {'Δ':>4}  MAP REGION")
        lines.append("  " + "-" * 58)
        for d in diffs[:300]:
            delta = d.b - d.a
            lines.append(
                f"  0x{d.address:04X}  {d.a:>3}  {d.b:>3}  {delta:>+4}  "
                f"{d.map_name or '—'}")
        if len(diffs) > 300:
            lines.append(f"  … {len(diffs) - 300} more not shown")

        self.result.setPlainText("\n".join(lines))


# ---------------------------------------------------------------------------
# ROM Info panel
# ---------------------------------------------------------------------------

class ROMInfoWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
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

            lines.append(f"Variant      : {v.name}")
            lines.append(f"Part Number  : {v.part_number}")
            lines.append(f"Chip         : {v.chip}")
            lines.append(f"Confidence   : {result.confidence}")
            lines.append(f"Size         : {result.size} bytes")
            lines.append(f"CRC32        : {result.crc32:#010x}")
            lines.append(f"SHA256       : {result.sha256[:32]}…")
            lines.append("")
            lines.append("=== Checksum ===")
            lines.append(f"Status       : {'✓ VALID' if cs_ok else '⚠ INVALID'}")
            lines.append(f"Byte sum     : {cs_sum:,}")
            lines.append(f"Target       : {cs_tgt:,}")
            if not cs_ok:
                lines.append(f"Delta        : {cs_sum - cs_tgt:+,}")
            lines.append("")
            lines.append("=== Map Addresses ===")
            lines.append(f"  {'NAME':<28} {'ADDR':>6}  {'SIZE':>5}  TYPE")
            lines.append("  " + "-" * 52)
            for m in v.maps:
                t = "scalar" if m.is_scalar else (
                    f"{m.rows}×{m.cols}" if m.is_2d else f"1×{m.cols}")
                lines.append(
                    f"  {m.name:<28} 0x{m.address:04X}  {m.size:>4}B  {t}")
        else:
            lines.append("Variant      : UNKNOWN")
            lines.append(f"Size         : {result.size} bytes")
            lines.append(f"CRC32        : {result.crc32:#010x}")
            lines.append(f"SHA256       : {result.sha256[:32]}…")

        if result.notes:
            lines.append("")
            for n in result.notes:
                lines.append(f"  ⚑ {n}")

        self.text.setPlainText("\n".join(lines))


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"HachiROM  v{APP_VERSION}")
        self.resize(1280, 820)
        self.current_data:    bytearray = bytearray()
        self.current_path:    str = ""
        self.current_variant  = None
        self._build_menu()
        self._build_ui()
        self._apply_dark_theme()

    def _build_menu(self):
        mb = self.menuBar()
        file_menu = mb.addMenu("File")

        open_act = QAction("Open ROM…", self)
        open_act.setShortcut("Ctrl+O")
        open_act.triggered.connect(self.open_rom)

        save_act = QAction("Save ROM…", self)
        save_act.setShortcut("Ctrl+S")
        save_act.triggered.connect(self.save_rom)

        save512_act = QAction("Save as 27C512 .bin…", self)
        save512_act.setShortcut("Ctrl+Shift+S")
        save512_act.triggered.connect(self.save_27c512)

        file_menu.addAction(open_act)
        file_menu.addAction(save_act)
        file_menu.addAction(save512_act)
        file_menu.addSeparator()
        file_menu.addAction("Quit", self.close)

        help_menu = mb.addMenu("Help")
        help_menu.addAction("About HachiROM", self._about)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 4, 8, 4)
        root.setSpacing(4)

        # Top bar
        top = QHBoxLayout()
        self.lbl_file = QLabel(
            "No ROM loaded — File → Open ROM…  (accepts .bin and .034)")
        self.lbl_file.setStyleSheet("color:#666; font-size:11px;")

        btn_open  = QPushButton("Open ROM…")
        btn_open.clicked.connect(self.open_rom)

        self.btn_save = QPushButton("Save .bin…")
        self.btn_save.clicked.connect(self.save_rom)
        self.btn_save.setEnabled(False)

        self.btn_save512 = QPushButton("Save 27C512 .bin…")
        self.btn_save512.setToolTip(
            "Save a 64KB image for EPROM programmers.\n"
            "Lower 32KB = 0xFF (erased)  |  Upper 32KB = ROM data\n"
            "Compatible with 27C512 chips used in Hitachi ECUs.")
        self.btn_save512.clicked.connect(self.save_27c512)
        self.btn_save512.setEnabled(False)

        top.addWidget(self.lbl_file, 1)
        top.addWidget(btn_open)
        top.addWidget(self.btn_save)
        top.addWidget(self.btn_save512)
        root.addLayout(top)

        # Splitter: map tabs | info panel
        splitter = QSplitter(Qt.Horizontal)
        self.tabs = QTabWidget()
        splitter.addWidget(self.tabs)
        self.info_panel = ROMInfoWidget()
        splitter.addWidget(self.info_panel)
        splitter.setSizes([900, 380])
        root.addWidget(splitter, 1)

        # Welcome tab
        welcome = QLabel(
            f"HachiROM  v{APP_VERSION}\n\n"
            "Open a .bin or .034 ROM file to begin.\n\n"
            "Supported ECUs:\n"
            "  893906266D — 7A Late  (Audi 90 / Coupe Quattro 2.3 20v, 4-connector)\n"
            "  893906266B — 7A Early (Audi 90 / Coupe Quattro 2.3 20v, 2-connector)\n"
            "  4A0906266  — AAH 12v  (Audi 100 / A6 / S4 2.8L V6)\n\n"
            "Double-click any map cell to edit it.\n"
            "Checksum is corrected automatically before saving."
        )
        welcome.setAlignment(Qt.AlignCenter)
        welcome.setStyleSheet("color:#555; font-size:13px; line-height:1.6;")
        self.tabs.addTab(welcome, "Welcome")

        # Compare tab always visible
        self.compare_tab = CompareTab()
        self.tabs.addTab(self.compare_tab, "⊕ Compare")

        self.statusBar().showMessage(f"HachiROM v{APP_VERSION} ready")

    # ── ROM open ─────────────────────────────────────────────────────────────

    def open_rom(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open ROM", "",
            "ROM Files (*.bin *.034);;Binary (*.bin);;034 Files (*.034);;All Files (*)")
        if not path:
            return
        try:
            data = hr.load_bin(path)
            if path.lower().endswith(".034"):
                data = hr.unscramble_034(data)
            self.current_data = bytearray(data)
            self.current_path = path
            self._load_rom(data, path)
        except Exception as e:
            QMessageBox.critical(self, "Open Error", str(e))

    def _load_rom(self, data: bytes, path: str):
        result = hr.detect(data)
        self.current_variant = result.variant

        variant_name = result.variant.name if result.variant else "Unknown variant"
        cs_ok = (hr.verify_checksum(data, result.variant)
                 if result.variant else False)
        cs_str = "✓ checksum OK" if cs_ok else "⚠ checksum invalid"
        self.lbl_file.setText(
            f"{Path(path).name}  ·  {variant_name}  ·  "
            f"CRC32 {result.crc32:#010x}  ·  {cs_str}"
        )
        self.lbl_file.setStyleSheet(
            "color:#2dff6e; font-size:11px;" if cs_ok
            else "color:#ff9900; font-size:11px;")

        self.btn_save.setEnabled(True)
        self.btn_save512.setEnabled(True)

        # Rebuild tabs
        while self.tabs.count():
            self.tabs.removeTab(0)

        if result.variant:
            editable = [m for m in result.variant.maps
                        if m.is_2d or (m.cols > 1
                            and not m.name.lower().startswith("rpm")
                            and not m.name.lower().startswith("load"))]
            for m in editable:
                # Pass shared bytearray so edits persist
                tab = MapTab(m, self.current_data)
                self.tabs.addTab(tab, m.name)
        else:
            lbl = QLabel(
                f"Unknown ROM variant — cannot display maps.\n\n"
                f"CRC32: {result.crc32:#010x}\n"
                f"SHA256: {result.sha256}\n"
                f"Size: {len(data)} bytes"
            )
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("color:#aaa;")
            self.tabs.addTab(lbl, "Unknown")

        self.compare_tab = CompareTab()
        self.tabs.addTab(self.compare_tab, "⊕ Compare")

        self.info_panel.update_rom(data)
        self.statusBar().showMessage(
            f"Loaded {Path(path).name}  ·  {variant_name}  ·  "
            f"confidence: {result.confidence}"
        )

    # ── Save helpers ─────────────────────────────────────────────────────────

    def _get_save_data_32k(self) -> bytearray:
        """Return checksum-corrected 32KB ROM from current_data."""
        raw = bytes(self.current_data[:32768])
        if self.current_variant:
            return hr.apply_checksum(raw, self.current_variant)
        return bytearray(raw)

    def save_rom(self):
        if not self.current_data:
            QMessageBox.warning(self, "HachiROM", "No ROM loaded.")
            return
        if not self.current_variant:
            QMessageBox.warning(self, "HachiROM",
                "ROM variant unknown — cannot verify checksum.\n"
                "Saving raw data without correction.")

        # Default filename
        base = Path(self.current_path).stem if self.current_path else "rom"
        default = str(Path(self.current_path).parent / (base + "_edited.bin"))
        path, _ = QFileDialog.getSaveFileName(
            self, "Save ROM", default,
            "Binary ROM Files (*.bin);;All Files (*)")
        if not path:
            return

        if self.current_variant:
            dlg = SaveConfirmDialog(
                bytes(self.current_data[:32768]),
                self.current_variant, path, mode="bin", parent=self)
            if dlg.exec_() != QDialog.Accepted:
                return

        try:
            rom32 = self._get_save_data_32k()
            hr.save_bin(bytes(rom32), path)
            self.statusBar().showMessage(f"Saved → {Path(path).name}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

    def save_27c512(self):
        """Save a 64KB image for 27C512 EPROM programmers.

        27C512 = 64KB. ECU reads from upper 32KB (A15=1).
        Layout: 0x0000–0x7FFF = 0xFF (erased/pad)
                0x8000–0xFFFF = ROM data
        """
        if not self.current_data:
            QMessageBox.warning(self, "HachiROM", "No ROM loaded.")
            return

        base = Path(self.current_path).stem if self.current_path else "rom"
        default = str(Path(self.current_path).parent / (base + "_27C512.bin"))
        path, _ = QFileDialog.getSaveFileName(
            self, "Save 27C512 Image", default,
            "Binary ROM Files (*.bin);;All Files (*)")
        if not path:
            return

        if self.current_variant:
            dlg = SaveConfirmDialog(
                bytes(self.current_data[:32768]),
                self.current_variant, path, mode="27c512", parent=self)
            if dlg.exec_() != QDialog.Accepted:
                return

        try:
            rom32 = self._get_save_data_32k()
            image = bytes(32768) + bytes(rom32)   # 32KB 0x00 pad + ROM
            # Per 27C512 spec, erased cells are 0xFF not 0x00
            image = bytes([0xFF] * 32768) + bytes(rom32)
            hr.save_bin(image, path)
            self.statusBar().showMessage(
                f"Saved 27C512 image → {Path(path).name}  (64KB)")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

    # ── Misc ─────────────────────────────────────────────────────────────────

    def _about(self):
        QMessageBox.about(self, f"HachiROM v{APP_VERSION}",
            f"<b>HachiROM  v{APP_VERSION}</b><br>"
            "Hitachi ECU ROM editor and analysis tool<br>"
            "Supports: 7A 20v (893906266D/B), AAH 12v (4A0906266)<br><br>"
            "Standalone — no Teensy or serial connection required.<br><br>"
            "<a href='https://github.com/dspl1236/HachiROM'>"
            "github.com/dspl1236/HachiROM</a>"
        )

    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #1e1e1e; color: #d4d4d4;
                font-family: 'Segoe UI', Arial, sans-serif; font-size: 12px;
            }
            QTabWidget::pane { border: 1px solid #333; background: #1e1e1e; }
            QTabBar::tab {
                background: #2d2d2d; color: #888;
                padding: 6px 14px; border: 1px solid #333;
            }
            QTabBar::tab:selected {
                background: #1e1e1e; color: #fff;
                border-bottom: 2px solid #007acc;
            }
            QTabBar::tab:hover { color: #ccc; background: #333; }
            QPushButton {
                background: #0e639c; color: #fff;
                border: none; padding: 5px 14px; border-radius: 3px;
            }
            QPushButton:hover { background: #1177bb; }
            QPushButton:disabled { background: #2d2d2d; color: #555; }
            QTableWidget {
                gridline-color: #333; background: #252526; border: none;
            }
            QTableWidget QLineEdit {
                background: #3c3c3c; color: #fff;
                border: 1px solid #007acc; padding: 1px;
            }
            QHeaderView::section {
                background: #2d2d2d; color: #888;
                border: 1px solid #333; padding: 3px; font-size: 10px;
            }
            QTextEdit {
                background: #1e1e1e; color: #d4d4d4;
                border: 1px solid #333;
                font-family: 'Consolas', monospace;
            }
            QSplitter::handle { background: #333; }
            QMenuBar { background: #2d2d2d; color: #d4d4d4; }
            QMenuBar::item:selected { background: #094771; }
            QMenu { background: #2d2d2d; color: #d4d4d4; border: 1px solid #333; }
            QMenu::item:selected { background: #094771; }
            QStatusBar { background: #007acc; color: #fff; font-size: 11px; }
            QLabel { color: #d4d4d4; }
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
