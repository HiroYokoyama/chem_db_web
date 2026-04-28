import sys
import os
import json
import pytest
from unittest.mock import MagicMock, patch, mock_open

# Ensure the plugin directory is in sys.path
plugin_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "moleditpy_plugin")
sys.path.append(plugin_dir)

try:
    import molibrary_plugin
    HAS_PYQT = True
except ImportError:
    HAS_PYQT = False

if not HAS_PYQT:
    pytest.skip("PyQt6 not installed", allow_module_level=True)

def test_settings_path():
    """Verify the settings JSON path construction."""
    path = molibrary_plugin._settings_path()
    assert path.endswith("molibrary_plugin.json")
    assert os.path.isabs(path)

def test_load_settings_missing_file():
    """Verify settings loading when the file doesn't exist."""
    with patch("os.path.isfile", return_value=False):
        settings = molibrary_plugin._load_settings()
        assert settings == {}

def test_load_settings_existing_file():
    """Verify settings loading from a mock JSON file."""
    mock_data = {"server_url": "http://test-server:5000"}
    with patch("os.path.isfile", return_value=True):
        with patch("builtins.open", mock_open(read_data=json.dumps(mock_data))):
            settings = molibrary_plugin._load_settings()
            assert settings == mock_data

def test_save_settings():
    """Verify settings saving logic."""
    data = {"key": "value"}
    with patch("builtins.open", mock_open()) as m_open:
        molibrary_plugin._save_settings(data)
        m_open.assert_called_once()
        # Verify that json.dump was called (roughly)
        handle = m_open()
        # Check if any write call contained the expected data
        written = "".join(call.args[0] for call in handle.write.call_args_list)
        assert '"key": "value"' in written

def test_text_search_worker_init():
    """Verify worker initialization and URL cleaning."""
    from molibrary_plugin import _TextSearchWorker
    worker = _TextSearchWorker("http://localhost:5000/", "aspirin")
    assert worker._base_url == "http://localhost:5000"
    assert worker._query == "aspirin"

def test_structure_search_worker_init():
    """Verify structure search worker initialization."""
    from molibrary_plugin import _StructureSearchWorker
    worker = _StructureSearchWorker("http://localhost:5000", "CCO", "substructure", 0.7)
    assert worker._base_url == "http://localhost:5000"
    assert worker._smiles == "CCO"
    assert worker._mode == "substructure"
    assert worker._threshold == 0.7
