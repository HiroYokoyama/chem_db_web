# conftest.py — pytest configuration for Molibrary tests
# Skip all tests gracefully if RDKit is not installed
import pytest
import sys

collect_ignore_glob = []


@pytest.fixture(autouse=True)
def isolated_plugin_settings(request, monkeypatch, tmp_path):
    if request.node.path.name.startswith('test_molibrary_'):
        import molibrary_plugin
        monkeypatch.setattr(molibrary_plugin, '_settings_path',
                            lambda: str(tmp_path / 'molibrary_plugin.json'))

def pytest_collection_modifyitems(config, items):
    try:
        from rdkit import Chem  # noqa: F401
    except ImportError:
        skip_rdkit = pytest.mark.skip(reason="RDKit not installed")
        for item in items:
            item.add_marker(skip_rdkit)
