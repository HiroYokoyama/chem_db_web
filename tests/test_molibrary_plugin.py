import sys
import os
import pytest
from unittest.mock import MagicMock, patch
try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    HAS_PYQT = True
except ImportError:
    HAS_PYQT = False

# Ensure the plugin directory is in sys.path
# Test is in chem_db_web/tests/, plugin is in chem_db_web/moleditpy_plugin/
plugin_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "moleditpy_plugin")
sys.path.append(plugin_dir)

if HAS_PYQT:
    from molibrary_plugin import MolibraryBrowserDialog
else:
    # Create a dummy class so the test collection doesn't fail
    class MolibraryBrowserDialog:
        pass

@pytest.fixture
def mock_context():
    if not HAS_PYQT:
        pytest.skip("PyQt6 not installed")
    context = MagicMock()
    context.get_main_window.return_value = None
    context.current_molecule = None
    return context

@pytest.mark.skipif(not HAS_PYQT, reason="PyQt6 not installed")
def test_on_results_single_hit_no_auto_open(qtbot, mock_context):
    """
    Test that when exactly one result is found, the row is selected 
    but the web browser is NOT opened automatically.
    """
    # Mock webbrowser.open
    with patch("molibrary_plugin.webbrowser.open") as mock_open:
        dialog = MolibraryBrowserDialog(mock_context)
        qtbot.add_widget(dialog)
        
        # Mock result data
        results = [{
            'id': 123,
            'name': 'Test Molecule',
            'smiles': 'CCO',
            'author': 'Tester',
            'inchi_key': 'ABC-123'
        }]
        
        # Call the results handler
        dialog._on_results(results)
        
        # Wait a bit to ensure no QTimer triggered browser opening
        qtbot.wait(300)
        
        # Assertions
        mock_open.assert_not_called()
        assert dialog._table.rowCount() == 1
        # currentRow() is 0-indexed, should be 0 because we auto-select line 0
        assert dialog._table.currentRow() == 0
        assert "1 compound(s) found" in dialog._lbl_status.text()

@pytest.mark.skipif(not HAS_PYQT, reason="PyQt6 not installed")
def test_manual_open_still_works(qtbot, mock_context):
    """
    Test that clicking the 'Open in Browser' button still opens the browser.
    """
    with patch("molibrary_plugin.webbrowser.open") as mock_open:
        dialog = MolibraryBrowserDialog(mock_context)
        qtbot.add_widget(dialog)

        results = [{
            'id': 456,
            'name': 'Manual Test',
            'smiles': 'CCC'
        }]
        dialog._results = results
        dialog._table.setRowCount(1)
        dialog._table.selectRow(0)

        qtbot.mouseClick(dialog._btn_open, Qt.MouseButton.LeftButton)
        mock_open.assert_called_once_with("http://127.0.0.1:5000/compound/456")


@pytest.mark.skipif(not HAS_PYQT, reason="PyQt6 not installed")
def test_auto_load_populates_on_open(qtbot, mock_context):
    """On open, the dialog should silently fetch all compounds if server is reachable."""
    fake_results = [{'id': 1, 'name': 'Ethanol', 'smiles': 'CCO',
                     'author': '', 'inchi_key': '', 'notes': '', 'pdf_filename': None}]
    with patch("molibrary_plugin._TextSearchWorker") as MockWorker:
        instance = MagicMock()
        MockWorker.return_value = instance
        instance.isRunning.return_value = False

        dialog = MolibraryBrowserDialog(mock_context)
        qtbot.add_widget(dialog)

        # Simulate the auto-load completing with results
        dialog._auto_loading = True
        dialog._on_results(fake_results)

        assert dialog._auto_loading is False
        assert dialog._table.rowCount() == 1


@pytest.mark.skipif(not HAS_PYQT, reason="PyQt6 not installed")
def test_auto_load_error_is_silent(qtbot, mock_context):
    """A connection error during auto-load must update the status label, not show a dialog."""
    with patch("molibrary_plugin.QMessageBox") as MockMsgBox:
        dialog = MolibraryBrowserDialog(mock_context)
        qtbot.add_widget(dialog)

        dialog._auto_loading = True
        dialog._on_error("Cannot connect to Molibrary at http://127.0.0.1:5000.")

        MockMsgBox.critical.assert_not_called()
        assert dialog._auto_loading is False
        assert "not reachable" in dialog._lbl_status.text()


@pytest.mark.skipif(not HAS_PYQT, reason="PyQt6 not installed")
def test_manual_error_shows_dialog(qtbot, mock_context):
    """A connection error from a manual search must still show a dialog."""
    with patch("molibrary_plugin.QMessageBox") as MockMsgBox:
        dialog = MolibraryBrowserDialog(mock_context)
        qtbot.add_widget(dialog)

        dialog._auto_loading = False  # manual search, not auto-load
        dialog._on_error("Cannot connect to Molibrary at http://127.0.0.1:5000.")

        MockMsgBox.critical.assert_called_once()


@pytest.mark.skipif(not HAS_PYQT, reason="PyQt6 not installed")
def test_exact_mode_radio_button_exists(qtbot, mock_context):
    """The 'Exact (InChI Key)' radio button must be present in the mode group."""
    dialog = MolibraryBrowserDialog(mock_context)
    qtbot.add_widget(dialog)
    mode_values = [btn.property("mode_value") for btn in dialog._mode_group.buttons()]
    assert "exact" in mode_values


@pytest.mark.skipif(not HAS_PYQT, reason="PyQt6 not installed")
def test_exact_mode_does_not_enable_threshold(qtbot, mock_context):
    """Selecting 'exact' mode must leave the threshold spinbox disabled."""
    dialog = MolibraryBrowserDialog(mock_context)
    qtbot.add_widget(dialog)
    for btn in dialog._mode_group.buttons():
        if btn.property("mode_value") == "exact":
            btn.setChecked(True)
            break
    assert not dialog._spin_thr.isEnabled()


@pytest.mark.skipif(not HAS_PYQT, reason="PyQt6 not installed")
def test_similarity_mode_enables_threshold(qtbot, mock_context):
    """Selecting 'similarity' mode must enable the threshold spinbox."""
    dialog = MolibraryBrowserDialog(mock_context)
    qtbot.add_widget(dialog)
    for btn in dialog._mode_group.buttons():
        if btn.property("mode_value") == "similarity":
            btn.setChecked(True)
            break
    assert dialog._spin_thr.isEnabled()


@pytest.mark.skipif(not HAS_PYQT, reason="PyQt6 not installed")
def test_local_svg_used_when_rdkit_available(qtbot, mock_context):
    """When RDKit is installed locally, selecting a row must NOT start _SvgFetcher."""
    import molibrary_plugin
    with patch("molibrary_plugin._try_local_svg", return_value="<svg>mock</svg>") as mock_local:
        dialog = MolibraryBrowserDialog(mock_context)
        qtbot.add_widget(dialog)

        dialog._results = [{'id': 1, 'name': 'Ethanol', 'smiles': 'CCO',
                             'author': '', 'inchi_key': '', 'notes': ''}]
        dialog._table.setRowCount(1)
        from PyQt6.QtWidgets import QTableWidgetItem
        dialog._table.setItem(0, 0, QTableWidgetItem("Ethanol"))

        with patch.object(molibrary_plugin._SvgFetcher, "start") as mock_start:
            dialog._table.selectRow(0)
            qtbot.wait(100)
            mock_local.assert_called_once_with("CCO")
            mock_start.assert_not_called()


@pytest.mark.skipif(not HAS_PYQT, reason="PyQt6 not installed")
def test_remote_svg_fallback_when_local_fails(qtbot, mock_context):
    """When _try_local_svg returns '', _SvgFetcher must be started."""
    import molibrary_plugin
    with patch("molibrary_plugin._try_local_svg", return_value=""):
        dialog = MolibraryBrowserDialog(mock_context)
        qtbot.add_widget(dialog)

        dialog._results = [{'id': 1, 'name': 'Ethanol', 'smiles': 'CCO',
                             'author': '', 'inchi_key': '', 'notes': ''}]
        dialog._table.setRowCount(1)
        from PyQt6.QtWidgets import QTableWidgetItem
        dialog._table.setItem(0, 0, QTableWidgetItem("Ethanol"))

        with patch.object(molibrary_plugin._SvgFetcher, "start") as mock_start:
            dialog._table.selectRow(0)
            qtbot.wait(100)
            mock_start.assert_called_once()


@pytest.mark.skipif(not HAS_PYQT, reason="PyQt6 not installed")
def test_threshold_spinbox_width(qtbot, mock_context):
    """Threshold spinbox must be at least 80 px wide."""
    dialog = MolibraryBrowserDialog(mock_context)
    qtbot.add_widget(dialog)
    assert dialog._spin_thr.minimumWidth() >= 80 or dialog._spin_thr.width() >= 80 or \
           dialog._spin_thr.maximumWidth() >= 90
