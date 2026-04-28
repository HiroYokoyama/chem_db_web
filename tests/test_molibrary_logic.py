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


def test_resolve_2d_overlaps_separates_forced_overlap():
    """_resolve_2d_overlaps must increase distance between two atoms placed on top of each other."""
    from math import sqrt
    from rdkit import Chem
    from rdkit.Chem import AllChem
    from molibrary_plugin import _resolve_2d_overlaps
    mol = Chem.MolFromSmiles('c1ccc(-c2ccccc2)cc1')
    AllChem.Compute2DCoords(mol)
    conf = mol.GetConformer()
    p0 = conf.GetAtomPosition(0)
    conf.SetAtomPosition(6, (p0.x, p0.y, 0.0))
    dist_before = sqrt((conf.GetAtomPosition(0).x - conf.GetAtomPosition(6).x) ** 2 +
                       (conf.GetAtomPosition(0).y - conf.GetAtomPosition(6).y) ** 2)
    _resolve_2d_overlaps(mol)
    dist_after = sqrt((conf.GetAtomPosition(0).x - conf.GetAtomPosition(6).x) ** 2 +
                      (conf.GetAtomPosition(0).y - conf.GetAtomPosition(6).y) ** 2)
    assert dist_after > dist_before


def test_resolve_2d_overlaps_no_change_when_clean():
    from rdkit import Chem
    from rdkit.Chem import AllChem
    from molibrary_plugin import _resolve_2d_overlaps
    mol = Chem.MolFromSmiles('CCO')
    AllChem.Compute2DCoords(mol)
    conf = mol.GetConformer()
    before = [(conf.GetAtomPosition(i).x, conf.GetAtomPosition(i).y)
              for i in range(mol.GetNumAtoms())]
    _resolve_2d_overlaps(mol)
    after = [(conf.GetAtomPosition(i).x, conf.GetAtomPosition(i).y)
             for i in range(mol.GetNumAtoms())]
    assert before == after


def test_try_local_svg_valid_smiles():
    """_try_local_svg returns an SVG string for a valid SMILES."""
    from molibrary_plugin import _try_local_svg
    svg = _try_local_svg("CCO")
    assert svg != ''
    assert "<svg" in svg


def test_try_local_svg_invalid_smiles():
    """_try_local_svg returns empty string for invalid SMILES."""
    from molibrary_plugin import _try_local_svg
    assert _try_local_svg("NOT_A_SMILES!!!") == ''


def test_try_local_svg_no_rdkit():
    """_try_local_svg returns empty string when RDKit import fails."""
    import sys
    from unittest.mock import patch
    from molibrary_plugin import _try_local_svg
    with patch.dict(sys.modules, {'rdkit': None, 'rdkit.Chem': None,
                                   'rdkit.Chem.Draw': None,
                                   'rdkit.Chem.Draw.rdMolDraw2D': None}):
        result = _try_local_svg("CCO")
    assert result == ''


def test_try_local_svg_custom_dimensions():
    """Width/height are forwarded to the drawer."""
    from molibrary_plugin import _try_local_svg
    svg = _try_local_svg("c1ccccc1", width=400, height=300)
    assert "<svg" in svg


def test_structure_search_worker_exact_mode():
    """Exact mode is stored correctly in the worker."""
    from molibrary_plugin import _StructureSearchWorker
    worker = _StructureSearchWorker("http://localhost:5000", "CCO", "exact", 0.5)
    assert worker._mode == "exact"


def test_structure_search_worker_http_error_emits_server_message():
    """A 400 HTTP error from the server must emit the server's error text, not 'Cannot connect'."""
    import urllib.error
    from unittest.mock import patch, MagicMock
    from molibrary_plugin import _StructureSearchWorker

    worker = _StructureSearchWorker("http://localhost:5000", "INVALID", "exact", 0.5)

    errors = []
    worker.error_occurred.connect(errors.append)

    # Simulate an HTTPError whose body contains a JSON error message
    http_err = urllib.error.HTTPError(
        url="http://localhost:5000/api/search",
        code=400,
        msg="BAD REQUEST",
        hdrs={},
        fp=None,
    )
    http_err.read = lambda: b'{"error": "Invalid query SMILES"}'

    with patch("urllib.request.urlopen", side_effect=http_err):
        worker.run()

    assert len(errors) == 1
    assert "Invalid query SMILES" in errors[0]
    # Must NOT produce the generic "Cannot connect" message
    assert "Cannot connect" not in errors[0]


def test_structure_search_worker_url_error_emits_connect_message():
    """A URLError (server down) must emit the 'Cannot connect' message."""
    import urllib.error
    from unittest.mock import patch
    from molibrary_plugin import _StructureSearchWorker

    worker = _StructureSearchWorker("http://localhost:9999", "CCO", "substructure", 0.5)

    errors = []
    worker.error_occurred.connect(errors.append)

    url_err = urllib.error.URLError(reason="Connection refused")
    with patch("urllib.request.urlopen", side_effect=url_err):
        worker.run()

    assert len(errors) == 1
    assert "Cannot connect" in errors[0]
