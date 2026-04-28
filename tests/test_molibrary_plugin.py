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
        
        # Mock result data
        results = [{
            'id': 456,
            'name': 'Manual Test',
            'smiles': 'CCC'
        }]
        dialog._results = results
        dialog._table.setRowCount(1)
        dialog._table.selectRow(0)
        
        # Simulate button click
        qtbot.mouseClick(dialog._btn_open, Qt.MouseButton.LeftButton)
        
        # Assertions
        mock_open.assert_called_once_with("http://127.0.0.1:5000/compound/456")
