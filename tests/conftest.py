# conftest.py — pytest configuration for Molibrary tests
# Skip all tests gracefully if RDKit is not installed
import pytest
import sys

collect_ignore_glob = []

def pytest_collection_modifyitems(config, items):
    try:
        from rdkit import Chem  # noqa: F401
    except ImportError:
        skip_rdkit = pytest.mark.skip(reason="RDKit not installed")
        for item in items:
            item.add_marker(skip_rdkit)
