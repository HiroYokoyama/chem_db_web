"""Real PySide6 lifetime and selected MoleditPy PluginContext integration."""
import importlib.util
import os
import sys
from pathlib import Path
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QMainWindow

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'moleditpy_plugin'))
import molibrary_plugin as plugin


def make_context():
    context = MagicMock()
    context.get_main_window.return_value = None
    context.current_molecule = None
    return context


def test_close_cancels_pending_startup_request(qtbot, monkeypatch):
    search = MagicMock()
    monkeypatch.setattr(plugin.MolibraryBrowserDialog, '_run_text_search', search)
    dialog = plugin.MolibraryBrowserDialog(make_context())
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.close()
    qtbot.wait(300)
    search.assert_not_called()


def test_close_finishes_active_qthread_and_restores_cursor(qtbot):
    entered = threading.Event()
    release = threading.Event()

    class PendingRequest(QThread):
        def run(self):
            entered.set()
            release.wait(2)

    dialog = plugin.MolibraryBrowserDialog(make_context())
    qtbot.addWidget(dialog)
    dialog._auto_load_timer.stop()
    worker = PendingRequest(dialog)
    dialog._worker = worker
    worker.finished.connect(dialog._on_search_finished)
    dialog._set_busy(True)
    worker.start()
    assert entered.wait(1)
    timer = threading.Timer(0.05, release.set)
    timer.start()
    try:
        dialog.show()
        dialog.close()
        assert not worker.isRunning()
        assert not dialog._busy
    finally:
        release.set()
        worker.wait()
        timer.join()


def test_real_host_context_registers_reuses_and_loads_structure(qtbot, monkeypatch):
    fallback = Path(__file__).resolve().parents[2] / 'python_molecular_editor/moleditpy/src'
    host_src = Path(os.environ.get('CI_MAIN_APP_SRC', str(fallback)))
    interface = host_src / 'moleditpy/plugins/plugin_interface.py'
    if not interface.is_file():
        pytest.fail(f'Selected MoleditPy PluginContext source is unavailable: {interface}')
    spec = importlib.util.spec_from_file_location('selected_moleditpy_plugin_interface', interface)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    main_window = QMainWindow()
    qtbot.addWidget(main_window)
    main_window.string_importer_manager = SimpleNamespace(load_from_smiles=MagicMock())
    manager = MagicMock()
    manager.get_main_window.return_value = main_window
    windows = {}
    manager.register_window.side_effect = lambda name, key, window: windows.__setitem__((name, key), window)
    manager.get_window.side_effect = lambda name, key: windows.get((name, key))
    context = module.PluginContext(manager, plugin.PLUGIN_NAME)
    monkeypatch.setattr(plugin.MolibraryBrowserDialog, '_auto_load', lambda self: None)
    monkeypatch.setattr(plugin.MolibraryBrowserDialog, '_on_row_selected', lambda self, *args: None)
    plugin.initialize(context)
    callback = manager.register_menu_action.call_args.args[2]
    assert manager.register_menu_action.call_args.args[1] == 'Database/Molibrary'
    callback()
    dialog = windows[(plugin.PLUGIN_NAME, 'molibrary_main')]
    qtbot.addWidget(dialog)
    callback()
    assert len(windows) == 1
    dialog._results = [{'id': 1, 'name': 'Ethanol', 'smiles': 'CCO'}]
    dialog._table.setRowCount(1)
    dialog._table.selectRow(0)
    dialog._load_selected()
    main_window.string_importer_manager.load_from_smiles.assert_called_once_with('CCO')
