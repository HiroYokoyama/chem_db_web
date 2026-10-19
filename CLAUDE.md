# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

**Molibrary** — a local compound library web app (Flask + RDKit + SQLite) and a companion MoleditPy plugin. Users store molecular structures with metadata (SMILES, InChI Key, PDF, notes) and search them by name/text, substructure, or Tanimoto similarity.

## Commands

```bash
# Setup (Windows)
setup.bat          # Creates venv, installs requirements.txt, downloads JSME offline assets

# Run server
start.bat          # Windows — activates venv and runs app.py
start.sh           # Linux/macOS
python app.py --localhost          # restrict to 127.0.0.1
python app.py --port 8080          # custom port

# Tests (from chem_db_web/)
pytest tests/ -v
pytest tests/test_app.py -v        # Flask/API tests
pytest tests/test_molibrary_plugin.py -v   # plugin Qt tests (headless)
pytest tests/test_molibrary_logic.py -v    # plugin logic unit tests
pytest tests/test_app.py::TestStructureSearchApi -v   # single class
```

## Architecture

### Server (`app.py`)
Single-file Flask app. Key design decisions:
- **SQLite** (`compounds.db`) with automatic schema migration in `init_db()` — new columns (`inchi_key`, `author`) are added via `ALTER TABLE` if absent
- **RDKit** is optional; `RDKIT` bool flag gates structure features globally; templates receive it via `_inject_globals()`
- **JSME_LOCAL** flag: if `static/jsme/jsme.nocache.js` exists (downloaded by `download_assets.py`), templates use the local copy; otherwise falls back to CDN

**Endpoints:**
- `GET /` — card grid of all compounds
- `GET /search` — structure search page (JSME editor + `/api/search`)
- `GET /api/compounds?q=` — text search (name, notes, SMILES, InChI Key LIKE query)
- `POST /api/search` — structure search: `{smiles, mode: "substructure"|"similarity", threshold}`
- `GET /api/structure.svg?smiles=&w=&h=` — renders SVG via RDKit

### Templates (`templates/`)
- `base.html` — layout, CSS, nav. All pages extend this.
- `editor_snippet.html` — reusable JSME editor widget included in `add.html`, `edit.html`, `search.html`
- `search.html` — structure-only search page. Has inline JS for mode switching, threshold slider, fetch to `/api/search`, result rendering.
- `index.html` — compound card grid. No client-side search; uses server-side `/api/compounds`.

### MoleditPy Plugin (`moleditpy_plugin/molibrary_plugin.py`)
A single-file PySide6 dialog plugin for MoleditPy. Installed by copying into `~/.moleditpy/plugins/`.

Version 2 targets MoleditPy 5 and supports Python 3.9–3.14. The web app remains
Python 3.10+. Install `requirements-plugin.txt` and `pytest-qt` to run the real
PySide6 tests, with `QT_API=pyside6`, `PYTEST_QT_API=pyside6` and
`QT_QPA_PLATFORM=offscreen`. CI accepts `moleditpy_ref` (branch, tag or full SHA)
and validates the real selected `PluginContext` API. The plugin has its own
LGPL-3.0-or-later texts in `moleditpy_plugin/`; the server retains root GPLv3.

**Plugin architecture:**
- `initialize(context)` — entry point; registers `Database/Molibrary` menu action
- `MolibraryBrowserDialog` — main QDialog with three search modes (Text / Substructure / Similarity)
- Worker threads: `_TextSearchWorker` → `GET /api/compounds?q=`, `_StructureSearchWorker` → `POST /api/search`, `_SvgFetcher` → `GET /api/structure.svg`
- Settings persistence: server URL saved to `molibrary_plugin.json` (sibling to the `.py` file)
- `_search_current_molecule()` gets `context.current_molecule` (RDKit mol object), converts to SMILES, auto-switches to substructure mode

### Data Model
```sql
compounds(id, name, author, smiles, molblock, inchi_key, pdf_filename, notes, created_at)
```
- `smiles` — canonical SMILES, used for structure search and SVG rendering
- `inchi_key` — computed on save/edit via `mol_to_inchi_key()`, stored for exact-match lookup
- `molblock` — raw Molfile/SDF block stored but not currently used in search
- `pdf_filename` — stored filename in `pdfs/` directory; non-ASCII filenames get a UUID fallback

## Key Relationships
- The plugin talks to the server only via HTTP (no shared code); the server URL defaults to `http://127.0.0.1:5000` and is user-configurable
- Structure search always goes through the server (RDKit on server side); the plugin itself does not do cheminformatics except to convert `current_molecule` → SMILES for the query
- `inchi_key` is generated server-side at add/edit time and stored; it is not recomputed on every search
