# ChemDBWeb — Local Chemical Structure & Protocol Database

A local web application for depositing, editing, and searching organic chemical structures with linked synthetic protocol PDFs.

---

## Requirements

- Python 3.10 or later
- Internet connection (first load only, for the JSME structure editor)

---

## Quick Start

```
1. Double-click  setup.bat   ← installs dependencies (run once)
2. Double-click  start.bat   ← starts the server
3. Open browser  http://127.0.0.1:5000
```

---

## Features

### Compound Library
- Grid view of all saved compounds with structure thumbnails
- Click any card to open the compound detail page

### Add / Edit Compounds
- **Interactive structure editor** (JSME) — draw molecules directly in the browser
- **SMILES input** — type SMILES manually or sync from/to the editor
- **PDF upload** — drag-and-drop or click to attach a synthetic protocol PDF
- **Notes field** — store reaction conditions, yield, observations, etc.

### Structure Search
| Mode | Description |
|---|---|
| **Substructure** | Find all compounds that contain the drawn query fragment |
| **Similarity** | Tanimoto similarity search (Morgan fingerprints) with adjustable threshold |

Search results show structure images, compound names, and a direct link to the PDF.

### PDF Management
- PDFs are stored locally in the `pdfs/` folder
- Open PDFs directly in the browser from the compound detail or search results page
- Replace a PDF at any time via the Edit page

---

## File Structure

```
chem_db/
├── app.py              # Flask application (backend + API)
├── requirements.txt    # Python dependencies
├── setup.bat           # One-time setup script (Windows)
├── start.bat           # Start the server (Windows)
├── compounds.db        # SQLite database (auto-created on first run)
├── pdfs/               # Uploaded PDF files
├── static/
│   └── style.css       # Dark-theme stylesheet
└── templates/
    ├── base.html        # Shared layout and navbar
    ├── index.html       # Compound library (grid view)
    ├── add.html         # Add compound form
    ├── edit.html        # Edit compound form
    ├── compound.html    # Compound detail page
    ├── search.html      # Structure search page
    └── editor_snippet.html  # Reusable JSME editor block
```

---

## Technology Stack

| Component | Library |
|---|---|
| Backend | [Flask](https://flask.palletsprojects.com/) |
| Chemistry | [RDKit](https://www.rdkit.org/) — structure rendering, substructure & similarity search |
| Structure Editor | [JSME](https://jsme-editor.github.io/) — JavaScript Molecule Editor |
| Database | SQLite (via Python `sqlite3`) |
| PDF Storage | Local filesystem (`pdfs/` directory) |

---

## API Endpoints

| Method | URL | Description |
|---|---|---|
| `GET` | `/api/structure.svg?smiles=<SMILES>` | Returns an SVG image of the structure |
| `POST` | `/api/search` | Structure search (JSON body below) |

**Search request body:**
```json
{
  "smiles": "c1ccccc1",
  "mode": "substructure",
  "threshold": 0.5
}
```
- `mode`: `"substructure"` or `"similarity"`
- `threshold`: Tanimoto cutoff for similarity mode (0.0–1.0)

---

## Notes

- The JSME editor is loaded from `jsme-editor.github.io` and cached by the browser — internet is required on the very first load per browser.
- All structure searching and rendering runs entirely locally via RDKit.
- PDF files are never renamed — the original filename is preserved in the `pdfs/` folder.
- The database file (`compounds.db`) is portable; copy it along with `pdfs/` to back up or migrate your data.
