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
    QGroupBox, QTextEdit, QSplitter, QAction, QHeaderView
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QBrush

sys.path.insert(0, str(Path(__file__).parent.parent))
import hachirom as hr
from hachirom.bridge import get_variant


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def heat_colour(value: int, vmin: int = 0, vmax: int = 255) -> QColor:
    """Blue (cold/low) → green → red (hot/high)."""
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
    """Signed-aware heat colour for timing maps (>128 = retard = blue)."""
    signed = raw_byte if raw_byte < 128 else raw_byte - 256
    lo, hi = -10, 40
    return heat_colour(max(lo, min(hi, signed)), lo, hi)


# ---------------------------------------------------------------------------
# Map tab — heatmap table
# ---------------------------------------------------------------------------

class MapTab(QWidget):
    def __init__(self, map_def, data: bytes, parent=None):
        super().__init__(parent)
        self.map_def = map_def
        self.data = bytearray(data)
        self._is_timing = any(k in map_def.name.lower() for k in ("timing", "knock"))
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        addr_str = f"0x{self.map_def.address:04X}"
        dims = (f"{self.map_def.rows}×{self.map_def.cols}"
                if self.map_def.is_2d else f"1×{self.map_def.cols}")
        info = QLabel(
            f"<b>{self.map_def.name}</b>  ·  "
            f"Address: <code>{addr_str}</code>  ·  {dims}  ·  "
            f"{self.map_def.unit or ''}  —  {self.map_def.description}"
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#aaa; font-size:11px; padding:2px 0;")
        layout.addWidget(info)

        self.table = QTableWidget(self.map_def.rows, self.map_def.cols)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setFont(QFont("Consolas", 9))
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)

        # Axis labels
        if self.map_def.rpm_axis:
            self.table.setVerticalHeaderLabels(
                [str(v) for v in self.map_def.rpm_axis[:self.map_def.rows]])
        if self.map_def.load_axis:
            self.table.setHorizontalHeaderLabels(
                [str(v) for v in self.map_def.load_axis[:self.map_def.cols]])

        self.refresh()

    def refresh(self):
        raw = hr.read_map(bytes(self.data), self.map_def)
        decoded = hr.read_map_decoded(bytes(self.data), self.map_def)

        all_raw = [v for row in raw for v in row]
        vmin, vmax = min(all_raw), max(all_raw)

        for r in range(self.map_def.rows):
            for c in range(self.map_def.cols):
                raw_v  = raw[r][c]
                dec_v  = decoded[r][c]
                text   = f"{dec_v:.3f}" if isinstance(dec_v, float) else str(dec_v)
                item   = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)

                colour = timing_colour(raw_v) if self._is_timing else heat_colour(raw_v, vmin, vmax)
                item.setBackground(QBrush(colour))

                brightness = colour.red()*0.299 + colour.green()*0.587 + colour.blue()*0.114
                item.setForeground(QBrush(QColor("#111") if brightness > 140 else QColor("#eee")))

                if self._is_timing:
                    signed = raw_v if raw_v < 128 else raw_v - 256
                    item.setToolTip(f"raw={raw_v}  →  {signed:+d}° BTDC")

                self.table.setItem(r, c, item)


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
        btn_a = QPushButton("Load ROM A…")
        btn_b = QPushButton("Load ROM B…")
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

    def _load_a(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load ROM A", "", "ROM Files (*.bin *.034);;All Files (*)")
        if not path:
            return
        data = hr.load_bin(path)
        if path.lower().endswith(".034"):
            data = hr.unscramble_034(data)
        self.data_a = data
        r = hr.detect(data)
        name = Path(path).name
        variant = r.variant.name if r.variant else "Unknown"
        self.lbl_a.setText(f"ROM A: {name}  [{variant}  {r.crc32:#010x}]")
        self.lbl_a.setStyleSheet("color:#2dff6e; font-size:11px;")

    def _load_b(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load ROM B", "", "ROM Files (*.bin *.034);;All Files (*)")
        if not path:
            return
        data = hr.load_bin(path)
        if path.lower().endswith(".034"):
            data = hr.unscramble_034(data)
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
        variant  = result_a.variant
        diffs    = hr.compare_roms(self.data_a, self.data_b, variant)
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
        cs_ok  = False
        lines  = ["=== ROM Detection ==="]

        if result.variant:
            v = result.variant
            lines.append(f"Variant      : {v.name}")
            lines.append(f"Part Number  : {v.part_number}")
            lines.append(f"Chip         : {v.chip}")
            lines.append(f"Confidence   : {result.confidence}")
            lines.append(f"Size         : {result.size} bytes")
            lines.append(f"CRC32        : {result.crc32:#010x}")
            lines.append(f"SHA256       : {result.sha256[:32]}…")
            lines.append("")

            # Checksum
            cs_ok  = hr.verify_checksum(data, v)
            cs_sum = hr.compute_sum(data)
            cs_tgt = v.checksum.get("target", 0)
            lines.append("=== Checksum ===")
            lines.append(f"Status       : {'✓ VALID' if cs_ok else '⚠ INVALID'}")
            lines.append(f"Byte sum     : {cs_sum:,}")
            lines.append(f"Target       : {cs_tgt:,}")
            if not cs_ok:
                lines.append(f"Delta        : {cs_sum - cs_tgt:+,}")
            lines.append("")

            # Map address table
            lines.append("=== Map Addresses ===")
            lines.append(f"  {'NAME':<28} {'ADDR':>6}  {'SIZE':>5}  TYPE")
            lines.append("  " + "-" * 52)
            for m in v.maps:
                t = "scalar" if m.is_scalar else (f"{m.rows}×{m.cols}" if m.is_2d else f"1×{m.cols}")
                lines.append(f"  {m.name:<28} 0x{m.address:04X}  {m.size:>4}B  {t}")
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
        self.setWindowTitle("HachiROM")
        self.resize(1280, 820)
        self.current_data: bytearray = bytearray()
        self.current_path: str = ""
        self.current_variant = None
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

        file_menu.addAction(open_act)
        file_menu.addAction(save_act)
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
        self.lbl_file = QLabel("No ROM loaded — File → Open ROM…  (accepts .bin and .034)")
        self.lbl_file.setStyleSheet("color:#666; font-size:11px;")
        btn_open = QPushButton("Open ROM…")
        btn_open.clicked.connect(self.open_rom)
        btn_save = QPushButton("Save ROM…")
        btn_save.clicked.connect(self.save_rom)
        btn_save.setEnabled(False)
        self.btn_save = btn_save
        top.addWidget(self.lbl_file, 1)
        top.addWidget(btn_open)
        top.addWidget(btn_save)
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
            "Open a .bin or .034 ROM file to begin.\n\n"
            "Supported ECUs:\n"
            "  893906266D — 7A Late  (Audi 90 / Coupe Quattro 2.3 20v, 4-connector)\n"
            "  893906266B — 7A Early (Audi 90 / Coupe Quattro 2.3 20v, 2-connector)\n"
            "  4A0906266  — AAH 12v  (Audi 100 / A6 / S4 2.8L V6)"
        )
        welcome.setAlignment(Qt.AlignCenter)
        welcome.setStyleSheet("color:#555; font-size:13px;")
        self.tabs.addTab(welcome, "Welcome")

        # Compare tab always visible
        self.compare_tab = CompareTab()
        self.tabs.addTab(self.compare_tab, "⊕ Compare")

        self.statusBar().showMessage("HachiROM ready")

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

        # Update header label
        variant_name = result.variant.name if result.variant else "Unknown variant"
        cs_ok = hr.verify_checksum(data, result.variant) if result.variant else False
        cs_str = "✓ checksum OK" if cs_ok else "⚠ checksum invalid"
        self.lbl_file.setText(
            f"{Path(path).name}  ·  {variant_name}  ·  "
            f"CRC32 {result.crc32:#010x}  ·  {cs_str}"
        )
        self.lbl_file.setStyleSheet(
            "color:#2dff6e; font-size:11px;" if cs_ok else "color:#ff9900; font-size:11px;")
        self.btn_save.setEnabled(True)

        # Rebuild tabs — keep Compare at end
        while self.tabs.count() > 0:
            self.tabs.removeTab(0)

        if result.variant:
            # Only show the main editable maps (skip raw axis tables)
            editable_maps = [m for m in result.variant.maps if m.is_2d or (m.cols > 1 and not m.name.lower().startswith("rpm") and not m.name.lower().startswith("load"))]
            for m in editable_maps:
                tab = MapTab(m, data)
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

        # Re-add compare tab
        self.compare_tab = CompareTab()
        self.tabs.addTab(self.compare_tab, "⊕ Compare")

        # Update info panel
        self.info_panel.update_rom(data)

        self.statusBar().showMessage(
            f"Loaded {Path(path).name}  —  {variant_name}  —  "
            f"confidence: {result.confidence}"
        )

    def save_rom(self):
        if not self.current_data:
            QMessageBox.warning(self, "HachiROM", "No ROM loaded.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save ROM", self.current_path or "modified.bin",
            "Binary ROM Files (*.bin);;All Files (*)")
        if not path:
            return
        try:
            hr.save_bin(bytes(self.current_data), path)
            self.statusBar().showMessage(f"Saved → {path}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

    def _about(self):
        QMessageBox.about(self, "HachiROM",
            "<b>HachiROM</b><br>"
            "Hitachi ECU ROM editor and analysis tool<br>"
            "Supports: 7A 20v (893906266D/B), AAH 12v (4A0906266)<br><br>"
            "Standalone — no Teensy or serial connection required.<br><br>"
            "<a href='https://github.com/dspl1236/HachiROM'>"
            "github.com/dspl1236/HachiROM</a>"
        )

    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #1e1e1e;
                color: #d4d4d4;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 12px;
            }
            QTabWidget::pane { border: 1px solid #333; background: #1e1e1e; }
            QTabBar::tab {
                background: #2d2d2d; color: #888;
                padding: 6px 14px; border: 1px solid #333;
            }
            QTabBar::tab:selected { background: #1e1e1e; color: #fff; border-bottom: 2px solid #007acc; }
            QTabBar::tab:hover { color: #ccc; background: #333; }
            QPushButton {
                background: #0e639c; color: #fff;
                border: none; padding: 5px 14px; border-radius: 3px;
            }
            QPushButton:hover { background: #1177bb; }
            QPushButton:disabled { background: #2d2d2d; color: #555; }
            QTableWidget { gridline-color: #333; background: #252526; border: none; }
            QHeaderView::section {
                background: #2d2d2d; color: #888;
                border: 1px solid #333; padding: 3px; font-size: 10px;
            }
            QTextEdit {
                background: #1e1e1e; color: #d4d4d4;
                border: 1px solid #333; font-family: 'Consolas', monospace;
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
