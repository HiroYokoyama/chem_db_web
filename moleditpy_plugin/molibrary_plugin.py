# -*- coding: utf-8 -*-
"""
Molibrary Browser — MoleditPy Plugin
Search the local Molibrary database and open compound pages in the browser.

Search modes
  • Text         — search by name, SMILES, InChI Key, or notes
  • Substructure — find compounds that contain the query fragment
  • Similarity   — Tanimoto fingerprint similarity (adjustable threshold)

Installation:
  Copy this file to your MoleditPy user plugin directory:
    Windows : C:\\Users\\<you>\\.moleditpy\\plugins\\
    Linux   : ~/.moleditpy/plugins/
  Menu:      Database > Molibrary
  Shortcut:  Ctrl+Shift+D
"""
import json
import os
import urllib.request
import urllib.parse
import urllib.error
import webbrowser

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QLabel, QHeaderView,
    QAbstractItemView, QApplication, QMessageBox, QSplitter,
    QWidget, QFrame, QButtonGroup, QRadioButton, QDoubleSpinBox,
    QGroupBox,
)

PLUGIN_NAME        = "Molibrary Browser"
PLUGIN_VERSION     = "2026.04.28"
PLUGIN_AUTHOR      = "HiroYokoyama"
PLUGIN_DESCRIPTION = "Search Molibrary (text / substructure / similarity) and open compound pages."
PLUGIN_CATEGORY    = "Database"

_DEFAULT_BASE_URL = "http://127.0.0.1:5000"

# ── Settings (companion JSON) ─────────────────────────────────────────────────
# Stored next to this file as molibrary_plugin.json so it survives
# plugin updates and application-wide settings resets.

def _settings_path() -> str:
    base = os.path.splitext(os.path.abspath(__file__))[0]
    return base + ".json"


def _load_settings() -> dict:
    path = _settings_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_settings(data: dict):
    try:
        with open(_settings_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ── Worker threads ────────────────────────────────────────────────────────────

class _TextSearchWorker(QThread):
    results_ready  = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, base_url: str, query: str, parent=None):
        super().__init__(parent)
        self._base_url = base_url.rstrip('/')
        self._query    = query

    def run(self):
        try:
            q   = urllib.parse.quote(self._query, safe='')
            url = f"{self._base_url}/api/compounds?q={q}"
            req = urllib.request.urlopen(url, timeout=6)
            data = json.loads(req.read().decode())
            self.results_ready.emit(data.get('results', []))
        except urllib.error.URLError:
            self.error_occurred.emit(
                f"Cannot connect to Molibrary at {self._base_url}.\n"
                "Make sure the server is running (start.bat / start.sh)."
            )
        except Exception as exc:
            self.error_occurred.emit(str(exc))


class _StructureSearchWorker(QThread):
    results_ready  = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, base_url: str, smiles: str, mode: str,
                 threshold: float, parent=None):
        super().__init__(parent)
        self._base_url  = base_url.rstrip('/')
        self._smiles    = smiles
        self._mode      = mode        # 'substructure' | 'similarity'
        self._threshold = threshold

    def run(self):
        try:
            payload = json.dumps({
                'smiles':    self._smiles,
                'mode':      self._mode,
                'threshold': self._threshold,
            }).encode()
            url = f"{self._base_url}/api/search"
            req = urllib.request.Request(
                url, data=payload,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read().decode())
            if 'error' in data:
                self.error_occurred.emit(data['error'])
            else:
                self.results_ready.emit(data.get('results', []))
        except urllib.error.URLError:
            self.error_occurred.emit(
                f"Cannot connect to Molibrary at {self._base_url}.\n"
                "Make sure the server is running."
            )
        except Exception as exc:
            self.error_occurred.emit(str(exc))


class _SvgFetcher(QThread):
    svg_ready = pyqtSignal(str, str)

    def __init__(self, base_url: str, smiles: str, parent=None):
        super().__init__(parent)
        self._base_url = base_url.rstrip('/')
        self._smiles   = smiles

    def run(self):
        try:
            enc = urllib.parse.quote(self._smiles, safe='')
            url = f"{self._base_url}/api/structure.svg?smiles={enc}&w=300&h=210"
            req = urllib.request.urlopen(url, timeout=5)
            self.svg_ready.emit(self._smiles, req.read().decode())
        except Exception:
            self.svg_ready.emit(self._smiles, '')


# ── Main dialog ───────────────────────────────────────────────────────────────

class MolibraryBrowserDialog(QDialog):
    def __init__(self, context):
        super().__init__(context.get_main_window())
        self.context     = context
        self.context.register_window("molibrary_main", self)
        self._results    = []
        self._worker     = None
        self._svg_worker = None

        # Restore last-used server URL from companion JSON
        saved_url = _load_settings().get("server_url", _DEFAULT_BASE_URL)

        self.setWindowTitle("Molibrary Browser")
        self.resize(980, 640)
        self._build_ui()

        self._le_url.setText(saved_url)
        # Save URL whenever it changes so it survives app restarts
        self._le_url.editingFinished.connect(self._save_url)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 12)

        # ── server + query bar ────────────────────────────────────────────────
        top = QHBoxLayout()

        top.addWidget(QLabel("Server:"))
        self._le_url = QLineEdit(_DEFAULT_BASE_URL)
        self._le_url.setFixedWidth(220)
        self._le_url.setPlaceholderText("http://host:5000")
        self._le_url.setToolTip(
            "Molibrary server URL.\n"
            "Examples:\n"
            "  http://127.0.0.1:5000    (this PC)\n"
            "  http://192.168.1.10:5000 (LAN / intranet)\n"
            "  http://labserver:5000    (hostname)\n\n"
            "The URL is saved automatically between sessions."
        )
        top.addWidget(self._le_url)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color:#444;")
        top.addWidget(sep)

        self._le_query = QLineEdit()
        self._le_query.setPlaceholderText(
            "Name, SMILES, InChI Key, notes…  (Enter to search)"
        )
        self._le_query.returnPressed.connect(self._do_search)
        top.addWidget(self._le_query, stretch=1)

        self._btn_search = QPushButton("Search")
        self._btn_search.setDefault(True)
        self._btn_search.clicked.connect(self._do_search)
        top.addWidget(self._btn_search)

        self._btn_all = QPushButton("All")
        self._btn_all.setToolTip("List all compounds")
        self._btn_all.clicked.connect(self._show_all)
        top.addWidget(self._btn_all)

        self._btn_cur = QPushButton("⬡  Current Molecule")
        self._btn_cur.setToolTip(
            "Search using the molecule currently open in MoleditPy"
        )
        self._btn_cur.clicked.connect(self._search_current_molecule)
        top.addWidget(self._btn_cur)

        root.addLayout(top)

        # ── search mode bar ───────────────────────────────────────────────────
        mode_box = QGroupBox("Search Mode")
        mode_layout = QHBoxLayout(mode_box)
        mode_layout.setSpacing(16)

        self._mode_group = QButtonGroup(self)
        for label, value in [("Text", "text"),
                              ("Substructure / Fragment", "substructure"),
                              ("Similarity", "similarity")]:
            rb = QRadioButton(label)
            rb.setProperty("mode_value", value)
            if value == "text":
                rb.setChecked(True)
            self._mode_group.addButton(rb)
            mode_layout.addWidget(rb)
            rb.toggled.connect(self._on_mode_changed)

        mode_layout.addSpacing(12)
        mode_layout.addWidget(QLabel("Threshold:"))
        self._spin_thr = QDoubleSpinBox()
        self._spin_thr.setRange(0.05, 1.0)
        self._spin_thr.setSingleStep(0.05)
        self._spin_thr.setValue(0.5)
        self._spin_thr.setDecimals(2)
        self._spin_thr.setFixedWidth(68)
        self._spin_thr.setEnabled(False)
        self._spin_thr.setToolTip("Tanimoto similarity threshold (0.05 – 1.00)")
        mode_layout.addWidget(self._spin_thr)

        mode_layout.addStretch()
        root.addWidget(mode_box)

        # ── hint ──────────────────────────────────────────────────────────────
        hint = QLabel(
            "Double-click a row (or press Enter) to open the compound page in your browser."
        )
        hint.setStyleSheet("color:#888; font-size:11px;")
        root.addWidget(hint)

        # ── splitter: table | preview ─────────────────────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Name", "Author", "SMILES", "InChI Key", "PDF"]
        )
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.selectionModel().selectionChanged.connect(self._on_row_selected)
        self._table.doubleClicked.connect(self._open_in_browser)
        self._table.keyPressEvent = self._table_key_press
        splitter.addWidget(self._table)

        # preview pane
        preview = QWidget()
        pv = QVBoxLayout(preview)
        pv.setSpacing(6)
        pv.setContentsMargins(8, 0, 0, 0)

        self._lbl_struct = QLabel("Select a compound\nto preview")
        self._lbl_struct.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_struct.setMinimumSize(320, 230)
        self._lbl_struct.setStyleSheet(
            "background:#fff; border:1px solid #555; border-radius:6px;"
            "color:#aaa; font-size:12px;"
        )
        pv.addWidget(self._lbl_struct)

        self._lbl_name = QLabel()
        self._lbl_name.setWordWrap(True)
        f = QFont(); f.setBold(True); f.setPointSize(11)
        self._lbl_name.setFont(f)
        pv.addWidget(self._lbl_name)

        self._lbl_author = QLabel()
        self._lbl_author.setStyleSheet("font-size:11px; color:#888;")
        pv.addWidget(self._lbl_author)

        self._lbl_sim = QLabel()
        self._lbl_sim.setStyleSheet("font-size:11px; color:#3fb950; font-weight:bold;")
        pv.addWidget(self._lbl_sim)

        self._lbl_inchi = QLabel()
        self._lbl_inchi.setWordWrap(True)
        self._lbl_inchi.setStyleSheet(
            "font-size:10px; color:#6a8; font-family:monospace;"
        )
        pv.addWidget(self._lbl_inchi)

        self._lbl_notes = QLabel()
        self._lbl_notes.setWordWrap(True)
        self._lbl_notes.setStyleSheet("font-size:11px; color:#aaa;")
        pv.addWidget(self._lbl_notes)
        pv.addStretch()

        splitter.addWidget(preview)
        splitter.setSizes([580, 400])
        root.addWidget(splitter, stretch=1)

        # ── status ────────────────────────────────────────────────────────────
        self._lbl_status = QLabel(
            "Enter a query, or click 'All' / 'Current Molecule'."
        )
        self._lbl_status.setStyleSheet("color:#888; font-size:11px;")
        root.addWidget(self._lbl_status)

        # ── action buttons ────────────────────────────────────────────────────
        actions = QHBoxLayout()

        self._btn_open = QPushButton("🌐  Open in Browser")
        self._btn_open.setEnabled(False)
        self._btn_open.setToolTip(
            "Open the Molibrary page for this compound\n"
            "(double-click or Enter also works)"
        )
        self._btn_open.clicked.connect(self._open_in_browser)
        actions.addWidget(self._btn_open)

        self._btn_load = QPushButton("⬇  Load into MoleditPy")
        self._btn_load.setEnabled(False)
        self._btn_load.setToolTip("Import this compound's structure into the 2D editor")
        self._btn_load.clicked.connect(self._load_selected)
        actions.addWidget(self._btn_load)

        actions.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.close)
        actions.addWidget(btn_close)

        root.addLayout(actions)

    # ── URL persistence ───────────────────────────────────────────────────────

    def _save_url(self):
        url = self._le_url.text().strip().rstrip('/')
        if url:
            cfg = _load_settings()
            cfg["server_url"] = url
            _save_settings(cfg)

    # ── Mode helpers ──────────────────────────────────────────────────────────

    def _current_mode(self) -> str:
        for btn in self._mode_group.buttons():
            if btn.isChecked():
                return btn.property("mode_value")
        return "text"

    def _on_mode_changed(self):
        self._spin_thr.setEnabled(self._current_mode() == "similarity")

    # ── Keyboard on table ─────────────────────────────────────────────────────

    def _table_key_press(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._open_in_browser()
        else:
            QTableWidget.keyPressEvent(self._table, event)

    # ── Search ────────────────────────────────────────────────────────────────

    def _current_url(self) -> str:
        return self._le_url.text().strip().rstrip('/') or _DEFAULT_BASE_URL

    def _do_search(self):
        mode  = self._current_mode()
        query = self._le_query.text().strip()
        if mode == "text":
            self._run_text_search(query)
        else:
            if not query:
                QMessageBox.information(
                    self, PLUGIN_NAME,
                    "Enter a SMILES in the query box for structure search,\n"
                    "or click 'Current Molecule' to use the active molecule."
                )
                return
            self._run_structure_search(query, mode)

    def _show_all(self):
        self._le_query.clear()
        self._run_text_search('')

    def _search_current_molecule(self):
        """Use the molecule open in MoleditPy as the search query."""
        try:
            from rdkit import Chem
            mw  = self.context.get_main_window()
            mol = getattr(mw, 'current_mol', None) or self.context.current_molecule
            if mol is None:
                QMessageBox.information(
                    self, PLUGIN_NAME,
                    "No molecule is currently open in MoleditPy."
                )
                return
            smiles = Chem.MolToSmiles(mol)
        except Exception as exc:
            QMessageBox.warning(self, PLUGIN_NAME,
                                f"Could not read current molecule: {exc}")
            return

        self._le_query.setText(smiles)

        mode = self._current_mode()
        if mode == "text":
            # Auto-switch to substructure for a SMILES query from the editor
            for btn in self._mode_group.buttons():
                if btn.property("mode_value") == "substructure":
                    btn.setChecked(True)
                    break
            mode = "substructure"

        self._run_structure_search(smiles, mode)

    # ── Internal search launchers ─────────────────────────────────────────────

    def _run_text_search(self, query: str):
        if self._worker and self._worker.isRunning():
            return
        self._set_busy(True)
        self._worker = _TextSearchWorker(self._current_url(), query, self)
        self._worker.results_ready.connect(self._on_results)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    def _run_structure_search(self, smiles: str, mode: str):
        if self._worker and self._worker.isRunning():
            return
        self._set_busy(True)
        thr = self._spin_thr.value()
        self._worker = _StructureSearchWorker(
            self._current_url(), smiles, mode, thr, self
        )
        self._worker.results_ready.connect(self._on_results)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    def _set_busy(self, busy: bool):
        for w in (self._btn_search, self._btn_all, self._btn_cur):
            w.setEnabled(not busy)
        if busy:
            self._lbl_status.setText("Searching…")
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        else:
            QApplication.restoreOverrideCursor()

    # ── Results ───────────────────────────────────────────────────────────────

    def _on_results(self, results: list):
        self._results = results
        self._table.setRowCount(0)

        for r in results:
            row = self._table.rowCount()
            self._table.insertRow(row)
            name_item = QTableWidgetItem(r.get('name', ''))
            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, QTableWidgetItem(r.get('author', '') or ''))
            self._table.setItem(row, 2, QTableWidgetItem(r.get('smiles', '') or ''))
            self._table.setItem(row, 3, QTableWidgetItem(r.get('inchi_key', '') or ''))
            self._table.setItem(row, 4,
                QTableWidgetItem('✔' if r.get('pdf_filename') else ''))

        count = len(results)
        if count:
            self._lbl_status.setText(
                f"{count} compound(s) found.  "
                "Double-click or press Enter to open in browser."
            )
            # If exactly one hit, auto-select for convenience
            if count == 1:
                self._table.selectRow(0)
        else:
            self._lbl_status.setText("No results found.")

    def _on_error(self, msg: str):
        QMessageBox.critical(self, PLUGIN_NAME, msg)
        self._lbl_status.setText("Error — see dialog.")

    # ── Row selection / preview ───────────────────────────────────────────────

    def _on_row_selected(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            self._btn_open.setEnabled(False)
            self._btn_load.setEnabled(False)
            return
        r = self._results[rows[0].row()]
        self._btn_open.setEnabled(True)
        self._btn_load.setEnabled(bool(r.get('smiles')))

        self._lbl_name.setText(r.get('name', ''))
        author = r.get('author', '') or ''
        self._lbl_author.setText(f"by {author}" if author else '')

        sim = r.get('similarity')
        self._lbl_sim.setText(
            f"Similarity: {sim * 100:.1f}%" if sim is not None else ''
        )

        self._lbl_inchi.setText(r.get('inchi_key', '') or '')
        notes = (r.get('notes') or '').strip()
        self._lbl_notes.setText(notes[:180] + ('…' if len(notes) > 180 else ''))

        smiles = r.get('smiles', '')
        if smiles:
            self._lbl_struct.setText("Loading…")
            if self._svg_worker and self._svg_worker.isRunning():
                self._svg_worker.terminate()
            self._svg_worker = _SvgFetcher(self._current_url(), smiles, self)
            self._svg_worker.svg_ready.connect(self._on_svg_ready)
            self._svg_worker.start()
        else:
            self._lbl_struct.setText("No structure")

    def _on_svg_ready(self, _smiles: str, svg_text: str):
        if not svg_text:
            self._lbl_struct.setText("No preview")
            return
        try:
            from PyQt6.QtSvg import QSvgRenderer
            from PyQt6.QtGui import QPainter
            renderer = QSvgRenderer(svg_text.encode())
            size = renderer.defaultSize()
            if not size.isValid():
                size.setWidth(300); size.setHeight(210)
            px = QPixmap(size)
            px.fill(Qt.GlobalColor.white)
            painter = QPainter(px)
            renderer.render(painter)
            painter.end()
            self._lbl_struct.setPixmap(
                px.scaled(320, 230,
                          Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
            )
        except Exception:
            self._lbl_struct.setText("(Preview unavailable)")

    # ── Actions ───────────────────────────────────────────────────────────────

    def _open_in_browser(self, _index=None):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        r   = self._results[rows[0].row()]
        cid = r.get('id')
        url = f"{self._current_url()}/compound/{cid}"
        webbrowser.open(url)
        self.context.show_status_message(
            f"Molibrary: opened '{r.get('name', '')}' in browser"
        )

    def _load_selected(self):
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        r      = self._results[rows[0].row()]
        smiles = r.get('smiles', '')
        name   = r.get('name', '')
        if not smiles:
            QMessageBox.warning(self, PLUGIN_NAME,
                                "No SMILES available for this compound.")
            return
        try:
            mw = self.context.get_main_window()
            if mw and hasattr(mw, 'string_importer_manager'):
                mw.string_importer_manager.load_from_smiles(smiles)
                self.context.show_status_message(f"Molibrary: loaded '{name}'")
                self.accept()
            else:
                QMessageBox.critical(
                    self, PLUGIN_NAME,
                    "Load failed: string_importer_manager not available."
                )
        except Exception as exc:
            QMessageBox.critical(self, PLUGIN_NAME, f"Load failed: {exc}")


# ── Entry point ───────────────────────────────────────────────────────────────

def initialize(context):
    def _open():
        win = context.get_window("molibrary_main")
        if win is None:
            win = MolibraryBrowserDialog(context)
        if win.isVisible():
            win.raise_()
            win.activateWindow()
        else:
            win.show()
            win.raise_()
            win.activateWindow()

    context.add_menu_action("Database/Molibrary", _open)
