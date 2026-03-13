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
    QDialogButtonBox, QFrame
)
from PyQt5.QtCore import Qt
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
    """Draws a green border around cells whose UserRole == 'changed'."""

    BORDER_COLOUR = QColor("#2dff6e")
    BORDER_WIDTH  = 2

    def paint(self, painter: QPainter, option, index):
        super().paint(painter, option, index)
        if index.data(Qt.UserRole) == "changed":
            painter.save()
            pen = QPen(self.BORDER_COLOUR, self.BORDER_WIDTH)
            painter.setPen(pen)
            # Inset rect slightly so border doesn't overlap neighbours
            r = option.rect.adjusted(1, 1, -1, -1)
            painter.drawRect(r)
            painter.restore()


# ---------------------------------------------------------------------------
# Save confirmation dialog
# ---------------------------------------------------------------------------

class SaveConfirmDialog(QDialog):
    def __init__(self, data: bytes, variant, path: str,
                 mode: str = "bin", parent=None):
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

        size_str = ("65,536 bytes (64 KB)" if mode == "27c512"
                    else f"{len(data):,} bytes (32 KB)")
        note_str = ("ROM mirrored into both 32KB halves — burn in 27C512 mode"
                    if mode == "27c512"
                    else "Native 32KB ROM — Teensy SD card / emulator")

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
# Map tab
# ---------------------------------------------------------------------------

class MapTab(QWidget):
    """
    Editable heatmap for one ROM map.

    _baseline[r][c]  — raw byte when ROM was opened (never changes)
    _local[r][c]     — current edited value (written to ROM on flush)

    Green border drawn on any cell where _local != _baseline.
    """

    def __init__(self, map_def, rom_data: bytearray, parent=None):
        super().__init__(parent)
        self.map_def  = map_def
        self.rom_data = rom_data
        self._is_timing = any(k in map_def.name.lower()
                              for k in ("timing", "knock"))

        addr, rows, cols = map_def.address, map_def.rows, map_def.cols

        def _read(r, c):
            off = addr + r * cols + c
            return rom_data[off] if off < len(rom_data) else 0

        # Baseline = snapshot of ROM bytes at open time
        self._baseline = [[_read(r, c) for c in range(cols)] for r in range(rows)]
        # Local copy — edits land here
        self._local    = [[_read(r, c) for c in range(cols)] for r in range(rows)]

        self._build_ui()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        info = QLabel(
            f"<b>{self.map_def.name}</b>  ·  "
            f"Addr: <code>0x{self.map_def.address:04X}</code>  ·  "
            f"{self.map_def.rows}×{self.map_def.cols}  ·  "
            f"{self.map_def.unit or ''}  —  {self.map_def.description}"
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#aaa; font-size:11px; padding:2px 0;")
        hint = QLabel(
            "Double-click to edit  ·  Enter/Tab to confirm  ·  Esc to cancel  ·  "
            "<span style='color:#2dff6e'>■</span> = changed from disk")
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
        self.table.setEditTriggers(
            QTableWidget.DoubleClicked | QTableWidget.SelectedClicked)
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
        self.table.itemChanged.connect(self._on_cell_changed)

    # ── Encode / decode ───────────────────────────────────────────────────────

    def _decode(self, raw: int) -> str:
        if self.map_def.decode:
            v = self.map_def.decode(raw)
            return f"{v:.3f}" if isinstance(v, float) else str(v)
        return str(raw)

    def _encode(self, text: str) -> int | None:
        try:
            if self.map_def.encode:
                return max(0, min(255, int(round(self.map_def.encode(float(text))))))
            v = int(float(text))
            if self._is_timing and v < 0:
                v = v & 0xFF
            return max(0, min(255, v))
        except (ValueError, TypeError):
            return None

    # ── Table population ──────────────────────────────────────────────────────

    def _populate_table(self):
        self.table.blockSignals(True)
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
                    item.setToolTip(f"raw={raw}  →  {signed:+d}° BTDC")
                self.table.setItem(r, c, item)
        self.table.blockSignals(False)

    # ── Cell edit ─────────────────────────────────────────────────────────────

    def _on_cell_changed(self, item: QTableWidgetItem):
        r, c = item.row(), item.column()
        raw  = self._encode(item.text())

        if raw is None:
            # Bad input — revert
            self.table.blockSignals(True)
            item.setText(self._decode(self._local[r][c]))
            self.table.blockSignals(False)
            return

        self._local[r][c] = raw
        changed = raw != self._baseline[r][c]

        # Recolour and mark changed border
        self.table.blockSignals(True)
        all_raw = [self._local[rr][cc]
                   for rr in range(self.map_def.rows)
                   for cc in range(self.map_def.cols)]
        colour = (timing_colour(raw) if self._is_timing
                  else heat_colour(raw, min(all_raw), max(all_raw)))
        _colour_item(item, colour, changed)
        if self._is_timing:
            signed = raw if raw < 128 else raw - 256
            item.setToolTip(f"raw={raw}  →  {signed:+d}° BTDC")
        self.table.blockSignals(False)

    # ── Flush ─────────────────────────────────────────────────────────────────

    def flush_to_rom(self):
        """Write _local into the shared rom_data bytearray."""
        addr, rows, cols = self.map_def.address, self.map_def.rows, self.map_def.cols
        for r in range(rows):
            for c in range(cols):
                off = addr + r * cols + c
                if off < len(self.rom_data):
                    self.rom_data[off] = self._local[r][c]

    def changed_count(self) -> int:
        rows, cols = self.map_def.rows, self.map_def.cols
        return sum(
            1 for r in range(rows) for c in range(cols)
            if self._local[r][c] != self._baseline[r][c]
        )


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
            "Load two ROMs and click Compare  —  or use Commit in the toolbar.")
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
    """Simple read-only hex dump. Shows all 32KB so you can at least inspect
    and save any ROM even if the variant is unrecognised."""

    BYTES_PER_ROW = 16

    def __init__(self, data: bytes, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        note = QLabel(
            "⚠  ROM variant not recognised — showing raw hex dump.  "
            "You can still save this file using Save .bin… or Save 27C512 .bin…")
        note.setStyleSheet("color:#ff9900; font-size:11px; padding:4px 0;")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QFont("Consolas", 9))
        layout.addWidget(self.view)
        self._load(data)

    def _load(self, data: bytes):
        lines = []
        bpr   = self.BYTES_PER_ROW
        for i in range(0, min(len(data), 32768), bpr):
            chunk = data[i:i + bpr]
            hex_s = " ".join(f"{b:02X}" for b in chunk)
            asc_s = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            lines.append(f"{i:04X}:  {hex_s:<{bpr*3}}  {asc_s}")
        self.view.setPlainText("\n".join(lines))


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
        self._original_data:  bytes = b""   # snapshot at open time — never mutated
        self._map_tabs:       list[MapTab] = []
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

        self.btn_commit = QPushButton("⬤  Commit")
        self.btn_commit.setToolTip(
            "Flush all edits, refresh checksum, and view diff vs original in Compare tab")
        self.btn_commit.setStyleSheet(
            "QPushButton{background:#1e4d1e;color:#2dff6e;border:1px solid #2dff6e;"
            "padding:5px 14px;border-radius:3px;}"
            "QPushButton:hover{background:#2a6b2a;}"
            "QPushButton:disabled{background:#2d2d2d;color:#555;border-color:#555;}"
        )
        self.btn_commit.clicked.connect(self.commit_edits)
        self.btn_commit.setEnabled(False)

        self.btn_save = QPushButton("Save .bin…")
        self.btn_save.clicked.connect(self.save_rom)
        self.btn_save.setEnabled(False)

        self.btn_save512 = QPushButton("Save 27C512 .bin…")
        self.btn_save512.setToolTip(
            "64KB image for EPROM programmers\n"
            "Lower 32KB = 0xFF pad  |  Upper 32KB = ROM data")
        self.btn_save512.clicked.connect(self.save_27c512)
        self.btn_save512.setEnabled(False)

        top.addWidget(self.lbl_file, 1)
        top.addWidget(btn_open)
        top.addWidget(self.btn_commit)
        top.addWidget(self.btn_save)
        top.addWidget(self.btn_save512)
        root.addLayout(top)

        splitter = QSplitter(Qt.Horizontal)
        self.tabs = QTabWidget()
        splitter.addWidget(self.tabs)
        self.info_panel = ROMInfoWidget()
        splitter.addWidget(self.info_panel)
        splitter.setSizes([900, 380])
        root.addWidget(splitter, 1)

        welcome = QLabel(
            f"HachiROM  v{APP_VERSION}\n\n"
            "Open a .bin or .034 ROM file to begin.\n\n"
            "Supported ECUs:\n"
            "  893906266D — 7A Late  (Audi 90 / Coupe Quattro 2.3 20v, 4-connector)\n"
            "  893906266B — 7A Early (Audi 90 / Coupe Quattro 2.3 20v, 2-connector)\n"
            "  4A0906266  — AAH 12v  (Audi 100 / A6 / S4 2.8L V6)\n\n"
            "Double-click any map cell to edit.\n"
            "Changed cells get a green border.  Commit to review vs original."
        )
        welcome.setAlignment(Qt.AlignCenter)
        welcome.setStyleSheet("color:#555; font-size:13px;")
        self.tabs.addTab(welcome, "Welcome")

        self.compare_tab = CompareTab()
        self._compare_tab_idx = self.tabs.addTab(self.compare_tab, "⊕ Compare")

        self.statusBar().showMessage(f"HachiROM v{APP_VERSION} ready")

    # ── ROM open ──────────────────────────────────────────────────────────────

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

            self._original_data = bytes(rom32)
            self.current_data   = bytearray(rom32)
            self.current_path   = path
            self._load_rom(path)
        except Exception as e:
            QMessageBox.critical(self, "Open Error", str(e))

    def _load_rom(self, path: str):
        data   = bytes(self.current_data)
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

        self.btn_commit.setEnabled(True)
        self.btn_save.setEnabled(True)
        self.btn_save512.setEnabled(True)

        while self.tabs.count():
            self.tabs.removeTab(0)
        self._map_tabs = []

        if result.variant:
            editable = [m for m in result.variant.maps
                        if m.is_2d or (m.cols > 1
                            and not m.name.lower().startswith("rpm")
                            and not m.name.lower().startswith("load"))]
            for m in editable:
                tab = MapTab(m, self.current_data)
                self._map_tabs.append(tab)
                self.tabs.addTab(tab, m.name)
        else:
            hex_tab = HexViewTab(bytes(self.current_data))
            self.tabs.addTab(hex_tab, "Hex Dump")

        self.compare_tab = CompareTab()
        self._compare_tab_idx = self.tabs.addTab(self.compare_tab, "⊕ Compare")

        self.info_panel.update_rom(data)
        self.statusBar().showMessage(
            f"Loaded {Path(path).name}  ·  {variant_name}  ·  "
            f"confidence: {result.confidence}")

    # ── Commit ────────────────────────────────────────────────────────────────

    def commit_edits(self):
        """Flush all tab edits into current_data and refresh checksum display."""
        self._collect_edits()
        total_changed = sum(t.changed_count() for t in self._map_tabs)
        self.info_panel.update_rom(bytes(self.current_data))
        if self.current_variant:
            cs_ok  = hr.verify_checksum(bytes(self.current_data), self.current_variant)
            result = hr.detect(bytes(self.current_data))
            self.lbl_file.setText(
                f"{Path(self.current_path).name}  ·  {self.current_variant.name}  ·  "
                f"CRC32 {result.crc32:#010x}  ·  "
                f"{'✓ checksum OK' if cs_ok else '⚠ will fix on save'}  ·  "
                f"{total_changed} cell(s) edited")
            self.lbl_file.setStyleSheet(
                "color:#2dff6e; font-size:11px;" if cs_ok
                else "color:#ff9900; font-size:11px;")
        self.statusBar().showMessage(
            f"Committed — {total_changed} cell(s) edited vs original")

    # ── Save helpers ──────────────────────────────────────────────────────────

    def _collect_edits(self):
        for tab in self._map_tabs:
            tab.flush_to_rom()

    def _corrected_32k(self) -> bytearray:
        self._collect_edits()
        raw = bytes(self.current_data[:32768])
        if self.current_variant:
            return hr.apply_checksum(raw, self.current_variant)
        return bytearray(raw)

    def _pre_save(self, mode: str):
        if not self.current_data:
            QMessageBox.warning(self, "HachiROM", "No ROM loaded.")
            return None, None

        base    = Path(self.current_path).stem if self.current_path else "rom"
        parent  = str(Path(self.current_path).parent) if self.current_path else ""
        suffix  = "_27C512.bin" if mode == "27c512" else "_edited.bin"
        default = str(Path(parent) / (base + suffix)) if parent else base + suffix

        path, _ = QFileDialog.getSaveFileName(
            self, "Save ROM", default,
            "Binary ROM Files (*.bin);;All Files (*)")
        if not path:
            return None, None

        self._collect_edits()

        if self.current_variant:
            dlg = SaveConfirmDialog(
                bytes(self.current_data[:32768]),
                self.current_variant, path, mode=mode, parent=self)
            if dlg.exec_() != QDialog.Accepted:
                return None, None

        return path, self._corrected_32k()

    def save_rom(self):
        path, rom32 = self._pre_save("bin")
        if path is None: return
        try:
            hr.save_bin(bytes(rom32), path)
            self.statusBar().showMessage(f"Saved → {Path(path).name}")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

    def save_27c512(self):
        path, rom32 = self._pre_save("27c512")
        if path is None: return
        try:
            # Mirror ROM into both halves.
            # The Hitachi ECU reads from A15=1 (upper 32KB), so either half works
            # electrically, but mirroring is safer:
            #   - Programmer verify passes on both halves
            #   - If accidentally burned in 27C256 mode (32KB only), chip still works
            #   - Matches what OEM 27C256 chips contain (pin-adapted to 27C512 socket)
            image = bytes(rom32) + bytes(rom32)
            hr.save_bin(image, path)
            self.statusBar().showMessage(
                f"Saved 27C512 → {Path(path).name}  (64 KB, mirrored)")
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

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
