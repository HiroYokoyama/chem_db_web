# -*- coding: utf-8 -*-
"""
Tests for Molibrary (app.py).

Run from chem_db_web/:
    pytest tests/ -v

Requirements: flask, pytest, rdkit
"""
import io
import json
import os
import sys
import tempfile
import pytest

# Make sure app.py is importable regardless of cwd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as _app_module
from app import app, init_db, mol_to_inchi_key, mol_to_svg, save_pdf


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Point the app at a fresh in-memory-like SQLite file for each test."""
    db_file = str(tmp_path / "test_compounds.db")
    pdf_dir = str(tmp_path / "pdfs")
    os.makedirs(pdf_dir, exist_ok=True)
    monkeypatch.setattr(_app_module, "DB_PATH", db_file)
    monkeypatch.setattr(_app_module, "PDF_DIR", pdf_dir)
    init_db()
    return db_file, pdf_dir


@pytest.fixture()
def client(tmp_db):
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── Helper ────────────────────────────────────────────────────────────────────

def _add_compound(client, name="Aspirin", smiles="CC(=O)Oc1ccccc1C(=O)O",
                  notes="", author=""):
    return client.post("/add", data={
        "name": name,
        "author": author,
        "smiles": smiles,
        "molblock": "",
        "notes": notes,
    }, follow_redirects=True)


# ── init_db / migration ───────────────────────────────────────────────────────

class TestInitDb:
    def test_creates_table(self, tmp_db):
        import sqlite3
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
        assert "compounds" in tables

    def test_inchi_key_column_exists(self, tmp_db):
        import sqlite3
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(compounds)"
            ).fetchall()]
        assert "inchi_key" in cols

    def test_author_column_exists(self, tmp_db):
        import sqlite3
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(compounds)"
            ).fetchall()]
        assert "author" in cols

    def test_migration_adds_inchi_key(self, tmp_path, monkeypatch):
        """Simulate a pre-existing DB without inchi_key/author and verify migration adds them."""
        import sqlite3
        db_file = str(tmp_path / "old.db")
        # Create legacy schema without inchi_key or author
        with sqlite3.connect(db_file) as conn:
            conn.execute('''CREATE TABLE compounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, smiles TEXT, molblock TEXT,
                pdf_filename TEXT, notes TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime')))''')
            conn.commit()
        monkeypatch.setattr(_app_module, "DB_PATH", db_file)
        monkeypatch.setattr(_app_module, "PDF_DIR", str(tmp_path / "pdfs"))
        os.makedirs(str(tmp_path / "pdfs"), exist_ok=True)
        init_db()
        with sqlite3.connect(db_file) as conn:
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(compounds)"
            ).fetchall()]
        assert "inchi_key" in cols
        assert "author" in cols


# ── Helpers ───────────────────────────────────────────────────────────────────

class TestHelpers:
    def test_mol_to_svg_valid(self):
        svg = mol_to_svg("CCO")
        assert svg is not None
        assert "<svg" in svg

    def test_mol_to_svg_invalid(self):
        assert mol_to_svg("NOT_A_SMILES!!!") is None

    def test_mol_to_svg_empty(self):
        assert mol_to_svg("") is None

    def test_mol_to_inchi_key_valid(self):
        key = mol_to_inchi_key("CCO")
        assert key is not None
        # InChI Keys are 27 chars: XXXXXXXXXXXXXX-YYYYYYYYYY-Z
        assert len(key) == 27
        assert key.count("-") == 2

    def test_mol_to_inchi_key_invalid(self):
        assert mol_to_inchi_key("NOT_SMILES") is None

    def test_mol_to_inchi_key_empty(self):
        assert mol_to_inchi_key("") is None

    def test_save_pdf_no_file(self):
        assert save_pdf(None) is None

    def test_save_pdf_non_pdf_extension(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_app_module, "PDF_DIR", str(tmp_path))
        fake = type("F", (), {"filename": "doc.docx", "save": lambda s, p: None})()
        assert save_pdf(fake) is None

    def test_save_pdf_non_ascii_filename(self, tmp_path, monkeypatch):
        """Non-ASCII filenames (e.g. Japanese) must not silently fail."""
        monkeypatch.setattr(_app_module, "PDF_DIR", str(tmp_path))
        saved_path = []

        class FakePDF:
            filename = "レポート.pdf"
            def save(self, path):
                saved_path.append(path)
                open(path, 'wb').close()

        result = save_pdf(FakePDF())
        assert result is not None
        assert result.endswith(".pdf")
        assert len(saved_path) == 1

    def test_save_pdf_ascii_filename(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_app_module, "PDF_DIR", str(tmp_path))
        saved_path = []

        class FakePDF:
            filename = "protocol.pdf"
            def save(self, path):
                saved_path.append(path)
                open(path, 'wb').close()

        result = save_pdf(FakePDF())
        assert result == "protocol.pdf"


# ── Routes ────────────────────────────────────────────────────────────────────

class TestIndex:
    def test_empty_library(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"No compounds" in resp.data

    def test_shows_compound_after_add(self, client):
        _add_compound(client, name="Ethanol", smiles="CCO")
        resp = client.get("/")
        assert b"Ethanol" in resp.data


class TestAdd:
    def test_get_add_page(self, client):
        resp = client.get("/add")
        assert resp.status_code == 200

    def test_add_compound_success(self, client):
        resp = _add_compound(client, name="Caffeine", smiles="Cn1cnc2c1c(=O)n(C)c(=O)n2C")
        assert resp.status_code == 200
        assert b"Caffeine" in resp.data

    def test_add_compound_no_name(self, client):
        resp = client.post("/add", data={"name": "", "smiles": "CCO"})
        assert b"Name is required" in resp.data

    def test_add_stores_inchi_key(self, client, tmp_db):
        import sqlite3
        _add_compound(client, name="Aspirin", smiles="CC(=O)Oc1ccccc1C(=O)O")
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT inchi_key FROM compounds WHERE name='Aspirin'"
            ).fetchone()
        assert row is not None
        assert row[0] is not None
        assert len(row[0]) == 27

    def test_add_stores_author(self, client, tmp_db):
        import sqlite3
        _add_compound(client, name="Caffeine", smiles="Cn1cnc2c1c(=O)n(C)c(=O)n2C",
                      author="Test Author")
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT author FROM compounds WHERE name='Caffeine'"
            ).fetchone()
        assert row[0] == "Test Author"

    def test_add_without_smiles(self, client):
        resp = client.post("/add", data={"name": "Unknown", "smiles": "", "molblock": ""},
                           follow_redirects=True)
        assert resp.status_code == 200
        assert b"Unknown" in resp.data

    def test_add_with_pdf(self, client, tmp_db):
        _, pdf_dir = tmp_db
        pdf_data = b"%PDF-1.4 fake content"
        resp = client.post("/add", data={
            "name": "WithPDF",
            "smiles": "CCO",
            "pdf": (io.BytesIO(pdf_data), "protocol.pdf"),
        }, content_type="multipart/form-data", follow_redirects=True)
        assert resp.status_code == 200
        assert os.path.exists(os.path.join(pdf_dir, "protocol.pdf"))


class TestViewCompound:
    def test_view_existing(self, client):
        _add_compound(client, name="Methanol", smiles="CO")
        resp = client.get("/compound/1")
        assert resp.status_code == 200
        assert b"Methanol" in resp.data

    def test_view_404(self, client):
        resp = client.get("/compound/9999")
        assert resp.status_code == 404

    def test_view_shows_inchi_key(self, client):
        _add_compound(client, name="Ethanol", smiles="CCO")
        resp = client.get("/compound/1")
        assert b"InChI Key" in resp.data

    def test_view_shows_smiles(self, client):
        _add_compound(client, name="Ethanol", smiles="CCO")
        resp = client.get("/compound/1")
        assert b"CCO" in resp.data


class TestEditCompound:
    def test_edit_get(self, client):
        _add_compound(client, name="Old Name")
        resp = client.get("/compound/1/edit")
        assert resp.status_code == 200
        assert b"Old Name" in resp.data

    def test_edit_post_success(self, client):
        _add_compound(client, name="Old")
        resp = client.post("/compound/1/edit", data={
            "name": "New Name",
            "smiles": "CCO",
            "molblock": "",
            "notes": "",
        }, follow_redirects=True)
        assert b"New Name" in resp.data

    def test_edit_updates_inchi_key(self, client, tmp_db):
        import sqlite3
        _add_compound(client, name="Test", smiles="CCO")
        client.post("/compound/1/edit", data={
            "name": "Test",
            "smiles": "CC(=O)Oc1ccccc1C(=O)O",  # aspirin
            "molblock": "",
            "notes": "",
        }, follow_redirects=True)
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT inchi_key FROM compounds WHERE id=1"
            ).fetchone()
        aspirin_key = mol_to_inchi_key("CC(=O)Oc1ccccc1C(=O)O")
        assert row[0] == aspirin_key


class TestDeleteCompound:
    def test_delete(self, client):
        _add_compound(client, name="ToDelete")
        resp = client.post("/compound/1/delete", follow_redirects=True)
        assert resp.status_code == 200
        assert b"ToDelete" not in resp.data


class TestSearch:
    def test_search_page(self, client):
        resp = client.get("/search")
        assert resp.status_code == 200


# ── API ───────────────────────────────────────────────────────────────────────

class TestStructureSvgApi:
    def test_valid_smiles(self, client):
        resp = client.get("/api/structure.svg?smiles=CCO")
        assert resp.status_code == 200
        assert b"<svg" in resp.data

    def test_invalid_smiles(self, client):
        resp = client.get("/api/structure.svg?smiles=NOT_VALID!!!")
        assert resp.status_code == 400

    def test_custom_dimensions(self, client):
        resp = client.get("/api/structure.svg?smiles=CCO&w=100&h=80")
        assert resp.status_code == 200


class TestCompoundsApi:
    def test_empty(self, client):
        resp = client.get("/api/compounds")
        data = json.loads(resp.data)
        assert data["results"] == []

    def test_returns_all(self, client):
        _add_compound(client, name="A", smiles="CCO")
        _add_compound(client, name="B", smiles="CC")
        data = json.loads(client.get("/api/compounds").data)
        assert len(data["results"]) == 2

    def test_search_by_name(self, client):
        _add_compound(client, name="Aspirin", smiles="CC(=O)Oc1ccccc1C(=O)O")
        _add_compound(client, name="Caffeine", smiles="Cn1cnc2c1c(=O)n(C)c(=O)n2C")
        data = json.loads(client.get("/api/compounds?q=Aspirin").data)
        assert len(data["results"]) == 1
        assert data["results"][0]["name"] == "Aspirin"

    def test_search_by_inchi_key(self, client):
        _add_compound(client, name="Ethanol", smiles="CCO")
        key = mol_to_inchi_key("CCO")
        data = json.loads(client.get(f"/api/compounds?q={key[:14]}").data)
        assert len(data["results"]) >= 1

    def test_results_have_inchi_key(self, client):
        _add_compound(client, name="Ethanol", smiles="CCO")
        data = json.loads(client.get("/api/compounds").data)
        assert data["results"][0]["inchi_key"] is not None


class TestStructureSearchApi:
    def test_substructure_match(self, client):
        _add_compound(client, name="Aspirin", smiles="CC(=O)Oc1ccccc1C(=O)O")
        _add_compound(client, name="Ethanol", smiles="CCO")
        resp = client.post("/api/search", json={"smiles": "c1ccccc1", "mode": "substructure"})
        data = json.loads(resp.data)
        names = [r["name"] for r in data["results"]]
        assert "Aspirin" in names
        assert "Ethanol" not in names

    def test_similarity_search(self, client):
        _add_compound(client, name="Aspirin", smiles="CC(=O)Oc1ccccc1C(=O)O")
        resp = client.post("/api/search", json={
            "smiles": "CC(=O)Oc1ccccc1C(=O)O",
            "mode": "similarity",
            "threshold": 0.9,
        })
        data = json.loads(resp.data)
        assert len(data["results"]) >= 1
        assert data["results"][0]["name"] == "Aspirin"

    def test_invalid_smiles_query(self, client):
        resp = client.post("/api/search", json={"smiles": "NOT_SMILES"})
        assert resp.status_code == 400

    def test_empty_query(self, client):
        resp = client.post("/api/search", json={"smiles": ""})
        data = json.loads(resp.data)
        assert data["results"] == []


class TestServePdf:
    def test_serve_existing_pdf(self, client, tmp_db):
        _, pdf_dir = tmp_db
        fname = "test_proto.pdf"
        with open(os.path.join(pdf_dir, fname), 'wb') as f:
            f.write(b"%PDF-1.4 fake")
        resp = client.get(f"/pdf/{fname}")
        assert resp.status_code == 200
        assert resp.content_type == "application/pdf"

    def test_download_pdf(self, client, tmp_db):
        _, pdf_dir = tmp_db
        fname = "dl_test.pdf"
        with open(os.path.join(pdf_dir, fname), 'wb') as f:
            f.write(b"%PDF-1.4 fake")
        resp = client.get(f"/pdf/{fname}/download")
        assert resp.status_code == 200
        assert "attachment" in resp.headers.get("Content-Disposition", "")
