"""
HachiROM — Desktop GUI
Cross-platform PyQt5 map editor / compare tool for Hitachi ECU ROMs.
"""

import sys
import os
from pathlib import Path
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QTableWidget, QTableWidgetItem, QStatusBar, QMessageBox,
    QGroupBox, QTextEdit, QSplitter, QAction, QMenuBar,
    QSpinBox, QComboBox, QHeaderView, QFrame
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPalette, QBrush

sys.path.insert(0, str(Path(__file__).parent.parent))
import hachirom as hr


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def heat_colour(value: int, vmin: int = 0, vmax: int = 255) -> QColor:
    t = (value - vmin) / max(1, vmax - vmin)
    r = int(255 * min(1, t * 2))
    g = int(255 * min(1, (1 - t) * 2))
    b = 40
    return QColor(r, g, b)


# ---------------------------------------------------------------------------
# Map tab — heatmap table
# ---------------------------------------------------------------------------

class MapTab(QWidget):
    def __init__(self, map_def, data: bytes, parent=None):
        super().__init__(parent)
        self.map_def = map_def
        self.data = bytearray(data)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        info = QLabel(
            f"<b>{self.map_def.name}</b>  ·  "
            f"Address: <code>0x{self.map_def.address:04X}</code>  ·  "
            f"{self.map_def.rows}×{self.map_def.cols}  ·  "
            f"{self.map_def.description}"
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.table = QTableWidget(self.map_def.rows, self.map_def.cols)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setFont(QFont("Consolas", 9))
        layout.addWidget(self.table)

        self.refresh()

    def refresh(self):
        raw = hr.read_map(bytes(self.data), self.map_def)
        decoded = hr.read_map_decoded(bytes(self.data), self.map_def)

        all_raw = [v for row in raw for v in row]
        vmin, vmax = min(all_raw), max(all_raw)

        for r in range(self.map_def.rows):
            for c in range(self.map_def.cols):
                raw_v = raw[r][c]
                dec_v = decoded[r][c]
                text = f"{dec_v}" if isinstance(dec_v, float) else str(dec_v)
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                item.setBackground(QBrush(heat_colour(raw_v, vmin, vmax)))
                item.setForeground(QBrush(QColor(255, 255, 255)))
                self.table.setItem(r, c, item)

    def get_data(self) -> bytearray:
        return self.data


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

        load_row = QHBoxLayout()
        self.lbl_a = QLabel("ROM A: (none)")
        self.lbl_b = QLabel("ROM B: (none)")
        btn_a = QPushButton("Load ROM A…")
        btn_b = QPushButton("Load ROM B…")
        btn_a.clicked.connect(self._load_a)
        btn_b.clicked.connect(self._load_b)
        btn_compare = QPushButton("Compare →")
        btn_compare.clicked.connect(self._run_compare)
        load_row.addWidget(btn_a)
        load_row.addWidget(self.lbl_a)
        load_row.addWidget(btn_b)
        load_row.addWidget(self.lbl_b)
        load_row.addWidget(btn_compare)
        layout.addLayout(load_row)

        self.result = QTextEdit()
        self.result.setReadOnly(True)
        self.result.setFont(QFont("Consolas", 9))
        layout.addWidget(self.result)

    def _load_a(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load ROM A", "", "BIN files (*.bin);;All files (*)")
        if path:
            self.data_a = hr.load_bin(path)
            self.lbl_a.setText(f"ROM A: {Path(path).name} ({len(self.data_a)} bytes)")

    def _load_b(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load ROM B", "", "BIN files (*.bin);;All files (*)")
        if path:
            self.data_b = hr.load_bin(path)
            self.lbl_b.setText(f"ROM B: {Path(path).name} ({len(self.data_b)} bytes)")

    def _run_compare(self):
        if not self.data_a or not self.data_b:
            QMessageBox.warning(self, "HachiROM", "Load both ROMs first.")
            return

        result_a = hr.detect(self.data_a)
        variant = result_a.variant

        diffs = hr.compare_roms(self.data_a, self.data_b, variant)
        summary = hr.diff_summary(diffs)

        lines = []
        lines.append(f"=== ROM Compare ===")
        lines.append(f"Total differences: {len(diffs)} bytes\n")

        if summary:
            lines.append("By region:")
            for region, count in sorted(summary.items(), key=lambda x: -x[1]):
                lines.append(f"  {region or 'unmapped':30s}  {count:4d} bytes changed")
            lines.append("")

        lines.append(f"{'Address':>8}  {'ROM A':>6}  {'ROM B':>6}  {'Delta':>6}  Region")
        lines.append("-" * 60)
        for d in diffs[:500]:
            delta = d.b - d.a
            sign = "+" if delta >= 0 else ""
            lines.append(
                f"  0x{d.address:04X}    0x{d.a:02X}    0x{d.b:02X}   {sign}{delta:4d}  "
                f"{d.map_name or ''}"
            )
        if len(diffs) > 500:
            lines.append(f"  … {len(diffs) - 500} more differences not shown")

        self.result.setPlainText("\n".join(lines))


# ---------------------------------------------------------------------------
# ROM Info panel
# ---------------------------------------------------------------------------

class ROMInfoWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(QFont("Consolas", 9))
        layout.addWidget(self.text)

    def update(self, data: bytes):
        result = hr.detect(data)
        lines = []
        lines.append("=== ROM Detection ===")
        if result.variant:
            v = result.variant
            lines.append(f"Variant      : {v.name}")
            lines.append(f"Part Number  : {v.part_number}")
            lines.append(f"Chip         : {v.chip}")
            lines.append(f"Size         : {result.size} bytes")
            lines.append(f"Confidence   : {result.confidence}")
        else:
            lines.append("Variant      : UNKNOWN")
            lines.append(f"Size         : {result.size} bytes")

        lines.append(f"SHA256       : {result.sha256[:32]}…")
        lines.append(f"Checksum     : 0x{hr.compute_checksum(data):02X}")

        if result.notes:
            lines.append("")
            for n in result.notes:
                lines.append(f"  ⚑ {n}")

        if result.variant:
            patches = hr.detect_patches(data, result.variant)
            if patches:
                lines.append("\n=== Patch Detection ===")
                for name, state in patches.items():
                    st = "PATCHED" if state else ("stock" if state is False else "custom")
                    lines.append(f"  {name:25s}  {st}")

        self.text.setPlainText("\n".join(lines))


# ---------------------------------------------------------------------------
# Main Window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HachiROM")
        self.resize(1200, 800)
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
        main_layout = QVBoxLayout(central)

        # Top bar
        top_bar = QHBoxLayout()
        self.lbl_file = QLabel("No ROM loaded")
        self.lbl_file.setStyleSheet("color: #aaa;")
        btn_open = QPushButton("Open ROM…")
        btn_open.clicked.connect(self.open_rom)
        btn_save = QPushButton("Save ROM…")
        btn_save.clicked.connect(self.save_rom)
        top_bar.addWidget(self.lbl_file, stretch=1)
        top_bar.addWidget(btn_open)
        top_bar.addWidget(btn_save)
        main_layout.addLayout(top_bar)

        # Splitter: tabs left, info right
        splitter = QSplitter(Qt.Horizontal)

        self.tabs = QTabWidget()
        splitter.addWidget(self.tabs)

        self.info_panel = ROMInfoWidget()
        splitter.addWidget(self.info_panel)
        splitter.setSizes([850, 350])

        main_layout.addWidget(splitter)

        # Placeholder tab
        placeholder = QLabel("Open a ROM file to begin.")
        placeholder.setAlignment(Qt.AlignCenter)
        self.tabs.addTab(placeholder, "Welcome")

        self.statusBar().showMessage("HachiROM ready")

    def open_rom(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open ROM", "", "BIN files (*.bin);;All files (*)")
        if not path:
            return
        data = hr.load_bin(path)
        self.current_data = bytearray(data)
        self.current_path = path
        self._load_rom(data, path)

    def _load_rom(self, data: bytes, path: str):
        result = hr.detect(data)
        self.current_variant = result.variant

        self.lbl_file.setText(
            f"{Path(path).name}  ·  "
            f"{result.variant.name if result.variant else 'Unknown variant'}  ·  "
            f"{len(data)} bytes"
        )

        # Clear tabs
        while self.tabs.count():
            self.tabs.removeTab(0)

        if result.variant:
            for m in result.variant.maps:
                tab = MapTab(m, data)
                self.tabs.addTab(tab, m.name)
        else:
            lbl = QLabel(f"Unknown ROM variant.\n\nSHA256: {result.sha256}\nSize: {len(data)} bytes")
            lbl.setAlignment(Qt.AlignCenter)
            self.tabs.addTab(lbl, "Unknown ROM")

        # Compare tab always available
        compare_tab = CompareTab()
        self.tabs.addTab(compare_tab, "⊕ Compare")

        self.info_panel.update(data)
        self.statusBar().showMessage(
            f"Loaded {Path(path).name} — "
            f"{result.confidence} — "
            f"{len(result.notes)} notes"
        )

    def save_rom(self):
        if not self.current_data:
            QMessageBox.warning(self, "HachiROM", "No ROM loaded.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save ROM", self.current_path or "modified.bin",
            "BIN files (*.bin);;All files (*)")
        if path:
            hr.save_bin(bytes(self.current_data), path)
            self.statusBar().showMessage(f"Saved to {path}")

    def _about(self):
        QMessageBox.about(self, "HachiROM",
            "<b>HachiROM</b><br>"
            "Hitachi ECU ROM editor and analysis tool<br>"
            "Supports: 7A 20v, AAH 12v (Audi/VW)<br><br>"
            "Source of truth for the audi90-teensy-ecu project<br>"
            "<a href='https://github.com/dspl1236/HachiROM'>github.com/dspl1236/HachiROM</a>"
        )

    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background-color: #1e1e1e; color: #d4d4d4; }
            QTabWidget::pane { border: 1px solid #333; }
            QTabBar::tab { background: #2d2d2d; color: #aaa; padding: 6px 14px; }
            QTabBar::tab:selected { background: #3c3c3c; color: #fff; }
            QPushButton {
                background: #0e639c; color: #fff; border: none;
                padding: 5px 12px; border-radius: 3px;
            }
            QPushButton:hover { background: #1177bb; }
            QTableWidget { gridline-color: #333; background: #252526; }
            QHeaderView::section { background: #2d2d2d; color: #aaa; }
            QTextEdit { background: #1e1e1e; color: #d4d4d4; border: 1px solid #333; }
            QLabel { color: #d4d4d4; }
            QMenuBar { background: #2d2d2d; color: #d4d4d4; }
            QMenuBar::item:selected { background: #094771; }
            QMenu { background: #2d2d2d; color: #d4d4d4; }
            QMenu::item:selected { background: #094771; }
            QStatusBar { background: #007acc; color: #fff; }
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
