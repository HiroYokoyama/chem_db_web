# -*- coding: utf-8 -*-
"""
Tests for Molibrary (app.py) — v1.1.0

Run from chem_db_web/:
    pytest tests/ -v

Requirements: flask, pytest, rdkit
"""
import io
import json
import os
import sys
import sqlite3
import tempfile
import pytest

# Make sure the project root is on the path so molibrary package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import molibrary.app as _app_module
from molibrary.app import (
    app, init_db, mol_to_inchi_key, mol_to_svg, save_pdf, parse_tags
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Point the app at a fresh SQLite file for each test."""
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
                  notes="", author="", tags=""):
    return client.post("/add", data={
        "name": name,
        "author": author,
        "smiles": smiles,
        "molblock": "",
        "notes": notes,
        "tags": tags,
    }, follow_redirects=True)


# ── init_db / migration ───────────────────────────────────────────────────────

class TestInitDb:
    def test_creates_table(self, tmp_db):
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
        assert "compounds" in tables

    def test_creates_compound_pdfs_table(self, tmp_db):
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
        assert "compound_pdfs" in tables

    def test_inchi_key_column_exists(self, tmp_db):
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(compounds)").fetchall()]
        assert "inchi_key" in cols

    def test_author_column_exists(self, tmp_db):
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(compounds)").fetchall()]
        assert "author" in cols

    def test_tags_column_exists(self, tmp_db):
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(compounds)").fetchall()]
        assert "tags" in cols

    def test_migration_adds_missing_columns(self, tmp_path, monkeypatch):
        """Simulate a pre-existing DB without inchi_key/author/tags and verify migration."""
        db_file = str(tmp_path / "old.db")
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
            cols = [r[1] for r in conn.execute("PRAGMA table_info(compounds)").fetchall()]
        assert "inchi_key" in cols
        assert "author" in cols
        assert "tags" in cols

    def test_migration_moves_pdf_filename_to_compound_pdfs(self, tmp_path, monkeypatch):
        """Old db with pdf_filename entries should be migrated to compound_pdfs."""
        db_file = str(tmp_path / "old.db")
        with sqlite3.connect(db_file) as conn:
            conn.execute('''CREATE TABLE compounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, smiles TEXT, molblock TEXT,
                pdf_filename TEXT, notes TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime')))''')
            conn.execute(
                "INSERT INTO compounds (name, pdf_filename) VALUES (?,?)",
                ("OldComp", "old_protocol.pdf")
            )
            conn.execute(
                "INSERT INTO compounds (name, pdf_filename) VALUES (?,?)",
                ("NoPDF", None)
            )
            conn.commit()
        monkeypatch.setattr(_app_module, "DB_PATH", db_file)
        monkeypatch.setattr(_app_module, "PDF_DIR", str(tmp_path / "pdfs"))
        os.makedirs(str(tmp_path / "pdfs"), exist_ok=True)
        init_db()
        with sqlite3.connect(db_file) as conn:
            rows = conn.execute("SELECT filename, pdf_type FROM compound_pdfs").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "old_protocol.pdf"
        assert rows[0][1] == "Protocol"

    def test_migration_does_not_run_twice(self, tmp_path, monkeypatch):
        """Migration should not duplicate rows on repeated init_db() calls."""
        db_file = str(tmp_path / "old.db")
        with sqlite3.connect(db_file) as conn:
            conn.execute('''CREATE TABLE compounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL, smiles TEXT, molblock TEXT,
                pdf_filename TEXT, notes TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime')))''')
            conn.execute(
                "INSERT INTO compounds (name, pdf_filename) VALUES (?,?)",
                ("OldComp", "file.pdf")
            )
            conn.commit()
        monkeypatch.setattr(_app_module, "DB_PATH", db_file)
        monkeypatch.setattr(_app_module, "PDF_DIR", str(tmp_path / "pdfs"))
        os.makedirs(str(tmp_path / "pdfs"), exist_ok=True)
        init_db()
        init_db()  # second call
        with sqlite3.connect(db_file) as conn:
            count = conn.execute("SELECT COUNT(*) FROM compound_pdfs").fetchone()[0]
        assert count == 1  # not duplicated


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


# ── Tags ──────────────────────────────────────────────────────────────────────

class TestTags:
    def test_parse_tags_hash_prefix(self):
        assert parse_tags('#NMR #MS') == 'NMR,MS'

    def test_parse_tags_comma_separated(self):
        assert parse_tags('NMR, MS, synthesis') == 'NMR,MS,synthesis'

    def test_parse_tags_mixed(self):
        assert parse_tags('#NMR MS, synthesis') == 'NMR,MS,synthesis'

    def test_parse_tags_empty(self):
        assert parse_tags('') == ''

    def test_parse_tags_whitespace_only(self):
        assert parse_tags('   ') == ''

    def test_parse_tags_deduplication(self):
        assert parse_tags('#NMR #NMR #MS') == 'NMR,MS'

    def test_parse_tags_preserves_order(self):
        result = parse_tags('#NMR #MS #X-ray')
        assert result == 'NMR,MS,X-ray'

    def test_add_compound_with_tags(self, client, tmp_db):
        _add_compound(client, name="Tagged", smiles="CCO", tags="#NMR #MS")
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("SELECT tags FROM compounds WHERE name='Tagged'").fetchone()
        assert row[0] == 'NMR,MS'

    def test_tags_in_view(self, client):
        _add_compound(client, name="Tagged", smiles="CCO", tags="#NMR")
        resp = client.get("/compound/1")
        assert b"NMR" in resp.data

    def test_search_by_hash_tag(self, client):
        _add_compound(client, name="Tagged", smiles="CCO", tags="#NMR")
        _add_compound(client, name="Untagged", smiles="CC")
        data = json.loads(client.get('/api/compounds?q=%23NMR').data)
        names = [r['name'] for r in data['results']]
        assert 'Tagged' in names
        assert 'Untagged' not in names

    def test_general_search_includes_tags(self, client):
        _add_compound(client, name="Compound", smiles="CCO", tags="#synthesis")
        data = json.loads(client.get('/api/compounds?q=synthesis').data)
        assert len(data['results']) >= 1
        assert data['results'][0]['name'] == 'Compound'

    def test_tags_in_api_response(self, client):
        _add_compound(client, name="Test", smiles="CCO", tags="#X-ray")
        data = json.loads(client.get('/api/compounds').data)
        assert data['results'][0]['tags'] == 'X-ray'

    def test_edit_updates_tags(self, client, tmp_db):
        _add_compound(client, name="Test", smiles="CCO", tags="#NMR")
        client.post("/compound/1/edit", data={
            "name": "Test", "smiles": "CCO", "molblock": "", "notes": "", "tags": "#NMR #MS"
        }, follow_redirects=True)
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("SELECT tags FROM compounds WHERE id=1").fetchone()
        assert row[0] == 'NMR,MS'

    def test_api_add_stores_tags(self, client):
        client.post("/api/compounds", json={"name": "Test", "smiles": "CCO", "tags": "#NMR #MS"})
        data = json.loads(client.get('/api/compounds?q=Test').data)
        assert data['results'][0]['tags'] == 'NMR,MS'

    def test_index_tag_route_prefills_search(self, client):
        resp = client.get("/?tag=NMR")
        assert resp.status_code == 200


# ── Multiple PDFs ─────────────────────────────────────────────────────────────

class TestMultiplePdfs:
    def test_add_single_pdf(self, client, tmp_db):
        client.post('/add', data={
            'name': 'WithPDF', 'smiles': 'CCO',
            'pdf_file': (io.BytesIO(b'%PDF-1.4 fake'), 'nmr.pdf'),
            'pdf_type': 'NMR',
        }, content_type='multipart/form-data', follow_redirects=True)
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("SELECT filename, pdf_type FROM compound_pdfs").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 'nmr.pdf'
        assert rows[0][1] == 'NMR'

    def test_add_multiple_pdfs(self, client, tmp_db):
        client.post('/add', data={
            'name': 'MultiPDF', 'smiles': 'CCO',
            'pdf_file': [
                (io.BytesIO(b'%PDF-1.4 nmr'), 'nmr_spec.pdf'),
                (io.BytesIO(b'%PDF-1.4 ms'),  'ms_spec.pdf'),
            ],
            'pdf_type': ['NMR', 'MS'],
        }, content_type='multipart/form-data', follow_redirects=True)
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT pdf_type FROM compound_pdfs ORDER BY id"
            ).fetchall()
        assert [r[0] for r in rows] == ['NMR', 'MS']

    def test_pdf_count_in_api_response(self, client, tmp_db):
        client.post('/add', data={
            'name': 'WithPDF', 'smiles': 'CCO',
            'pdf_file': [(io.BytesIO(b'%PDF-1.4'), 'a.pdf'),
                         (io.BytesIO(b'%PDF-1.4'), 'b.pdf')],
            'pdf_type': ['NMR', 'MS'],
        }, content_type='multipart/form-data', follow_redirects=True)
        data = json.loads(client.get('/api/compounds').data)
        assert data['results'][0]['pdf_count'] == 2

    def test_pdf_count_in_search_api(self, client, tmp_db):
        client.post('/add', data={
            'name': 'WithPDF', 'smiles': 'CCO',
            'pdf_file': (io.BytesIO(b'%PDF-1.4'), 'nmr.pdf'),
            'pdf_type': 'NMR',
        }, content_type='multipart/form-data', follow_redirects=True)
        resp = client.post('/api/search', json={"smiles": "CCO", "mode": "exact"})
        data = json.loads(resp.data)
        assert data['results'][0]['pdf_count'] == 1

    def test_legacy_pdf_field_still_works(self, client, tmp_db):
        """Old 'pdf' field (single upload) must still be accepted."""
        client.post('/add', data={
            'name': 'LegacyPDF', 'smiles': 'CCO',
            'pdf': (io.BytesIO(b'%PDF-1.4'), 'legacy.pdf'),
        }, content_type='multipart/form-data', follow_redirects=True)
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("SELECT * FROM compound_pdfs").fetchall()
        assert len(rows) == 1

    def test_pdfs_shown_in_compound_view(self, client, tmp_db):
        client.post('/add', data={
            'name': 'View', 'smiles': 'CCO',
            'pdf_file': (io.BytesIO(b'%PDF-1.4'), 'nmr.pdf'),
            'pdf_type': 'NMR',
        }, content_type='multipart/form-data', follow_redirects=True)
        resp = client.get('/compound/1')
        assert b'NMR' in resp.data
        assert b'nmr.pdf' in resp.data

    def test_delete_compound_pdf(self, client, tmp_db):
        client.post('/add', data={
            'name': 'ToDelete', 'smiles': 'CCO',
            'pdf_file': (io.BytesIO(b'%PDF-1.4'), 'delete_me.pdf'),
            'pdf_type': 'NMR',
        }, content_type='multipart/form-data', follow_redirects=True)
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            pdf_id = conn.execute("SELECT id FROM compound_pdfs LIMIT 1").fetchone()[0]
        resp = client.post(f'/compound/1/pdf/{pdf_id}/delete', follow_redirects=True)
        assert resp.status_code == 200
        with sqlite3.connect(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM compound_pdfs").fetchone()[0]
        assert count == 0

    def test_delete_pdf_wrong_compound_is_noop(self, client, tmp_db):
        """Deleting a pdf with wrong cid must not delete it."""
        _add_compound(client, name="C1", smiles="CCO")
        _add_compound(client, name="C2", smiles="CC")
        client.post('/add', data={
            'name': 'C3', 'smiles': 'CCCO',
            'pdf_file': (io.BytesIO(b'%PDF-1.4'), 'real.pdf'),
            'pdf_type': 'NMR',
        }, content_type='multipart/form-data', follow_redirects=True)
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            pdf_id = conn.execute("SELECT id FROM compound_pdfs LIMIT 1").fetchone()[0]
        # Try to delete pdf of compound 3 via compound 1's route
        client.post(f'/compound/1/pdf/{pdf_id}/delete', follow_redirects=True)
        with sqlite3.connect(db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM compound_pdfs").fetchone()[0]
        assert count == 1  # untouched

    def test_add_pdf_in_edit(self, client, tmp_db):
        _add_compound(client, name="Test", smiles="CCO")
        client.post('/compound/1/edit', data={
            'name': 'Test', 'smiles': 'CCO', 'molblock': '', 'notes': '', 'tags': '',
            'pdf_file': (io.BytesIO(b'%PDF-1.4'), 'new.pdf'),
            'pdf_type': 'MS',
        }, content_type='multipart/form-data', follow_redirects=True)
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute("SELECT pdf_type FROM compound_pdfs").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 'MS'

    def test_no_pdf_count_zero(self, client):
        _add_compound(client, name="NoPDF", smiles="CCO")
        data = json.loads(client.get('/api/compounds').data)
        assert data['results'][0]['pdf_count'] == 0

    def test_invalid_pdf_type_defaults_to_other(self, client, tmp_db):
        """An unknown pdf_type value should be stored as 'Other'."""
        client.post('/add', data={
            'name': 'Test', 'smiles': 'CCO',
            'pdf_file': (io.BytesIO(b'%PDF-1.4'), 'f.pdf'),
            'pdf_type': 'UNKNOWNTYPE',
        }, content_type='multipart/form-data', follow_redirects=True)
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("SELECT pdf_type FROM compound_pdfs").fetchone()
        assert row[0] == 'Other'


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

    def test_tag_query_param_accepted(self, client):
        resp = client.get("/?tag=NMR")
        assert resp.status_code == 200


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
        """Legacy 'pdf' field must still save the file to pdf_dir."""
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
            "tags": "",
        }, follow_redirects=True)
        assert b"New Name" in resp.data

    def test_edit_updates_inchi_key(self, client, tmp_db):
        _add_compound(client, name="Test", smiles="CCO")
        client.post("/compound/1/edit", data={
            "name": "Test",
            "smiles": "CC(=O)Oc1ccccc1C(=O)O",  # aspirin
            "molblock": "",
            "notes": "",
            "tags": "",
        }, follow_redirects=True)
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            row = conn.execute("SELECT inchi_key FROM compounds WHERE id=1").fetchone()
        aspirin_key = mol_to_inchi_key("CC(=O)Oc1ccccc1C(=O)O")
        assert row[0] == aspirin_key


class TestDeleteCompound:
    def test_delete(self, client):
        _add_compound(client, name="ToDelete")
        resp = client.post("/compound/1/delete", follow_redirects=True)
        assert resp.status_code == 200
        assert b"ToDelete" not in resp.data

    def test_delete_also_removes_pdfs(self, client, tmp_db):
        client.post('/add', data={
            'name': 'WithPDF', 'smiles': 'CCO',
            'pdf_file': (io.BytesIO(b'%PDF-1.4'), 'todelete.pdf'),
            'pdf_type': 'NMR',
        }, content_type='multipart/form-data', follow_redirects=True)
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            count_before = conn.execute("SELECT COUNT(*) FROM compound_pdfs").fetchone()[0]
        assert count_before == 1
        client.post("/compound/1/delete", follow_redirects=True)
        with sqlite3.connect(db_path) as conn:
            count_after = conn.execute("SELECT COUNT(*) FROM compound_pdfs").fetchone()[0]
        assert count_after == 0


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
        data = json.loads(client.get("/api/compounds").data)
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

    def test_results_have_pdf_count(self, client):
        _add_compound(client, name="NoPDF", smiles="CCO")
        data = json.loads(client.get("/api/compounds").data)
        assert "pdf_count" in data["results"][0]
        assert data["results"][0]["pdf_count"] == 0

    def test_tag_hash_search_only_tags_column(self, client):
        """#NMR query should only match compounds tagged NMR, not name/notes."""
        _add_compound(client, name="NMR Compound", smiles="CCO")  # name has NMR but no tag
        _add_compound(client, name="Tagged", smiles="CC", tags="#NMR")
        data = json.loads(client.get('/api/compounds?q=%23NMR').data)
        names = [r['name'] for r in data['results']]
        assert 'Tagged' in names
        assert 'NMR Compound' not in names


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

    def test_search_results_have_pdf_count(self, client):
        _add_compound(client, name="Aspirin", smiles="CC(=O)Oc1ccccc1C(=O)O")
        resp = client.post("/api/search", json={"smiles": "c1ccccc1", "mode": "substructure"})
        data = json.loads(resp.data)
        assert "pdf_count" in data["results"][0]

    def test_invalid_smiles_query(self, client):
        resp = client.post("/api/search", json={"smiles": "NOT_SMILES"})
        assert resp.status_code == 400

    def test_empty_query(self, client):
        resp = client.post("/api/search", json={"smiles": ""})
        data = json.loads(resp.data)
        assert data["results"] == []


class TestExactSearchApi:
    def test_exact_match_found(self, client):
        _add_compound(client, name="Ethanol", smiles="CCO")
        resp = client.post("/api/search", json={"smiles": "CCO", "mode": "exact"})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data["results"]) == 1
        assert data["results"][0]["name"] == "Ethanol"

    def test_exact_match_not_found(self, client):
        _add_compound(client, name="Ethanol", smiles="CCO")
        resp = client.post("/api/search", json={"smiles": "CCCO", "mode": "exact"})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["results"] == []

    def test_exact_match_excludes_superstructure(self, client):
        _add_compound(client, name="Aspirin", smiles="CC(=O)Oc1ccccc1C(=O)O")
        _add_compound(client, name="Benzene", smiles="c1ccccc1")
        resp = client.post("/api/search", json={
            "smiles": "CC(=O)Oc1ccccc1C(=O)O", "mode": "exact"
        })
        data = json.loads(resp.data)
        names = [r["name"] for r in data["results"]]
        assert "Aspirin" in names
        assert "Benzene" not in names

    def test_exact_match_canonical_smiles_variant(self, client):
        _add_compound(client, name="Ethanol", smiles="CCO")
        resp = client.post("/api/search", json={"smiles": "OCC", "mode": "exact"})
        data = json.loads(resp.data)
        assert len(data["results"]) == 1
        assert data["results"][0]["name"] == "Ethanol"

    def test_exact_match_multiple_compounds(self, client):
        _add_compound(client, name="Ethanol", smiles="CCO")
        _add_compound(client, name="Methanol", smiles="CO")
        resp = client.post("/api/search", json={"smiles": "CO", "mode": "exact"})
        data = json.loads(resp.data)
        names = [r["name"] for r in data["results"]]
        assert "Methanol" in names
        assert "Ethanol" not in names

    def test_exact_match_invalid_smiles(self, client):
        resp = client.post("/api/search", json={"smiles": "NOTSMILES", "mode": "exact"})
        assert resp.status_code == 400

    def test_exact_match_empty_smiles(self, client):
        resp = client.post("/api/search", json={"smiles": "", "mode": "exact"})
        data = json.loads(resp.data)
        assert data["results"] == []

    def test_exact_match_by_inchi_key_directly(self, client):
        _add_compound(client, name="Ethanol", smiles="CCO")
        key = mol_to_inchi_key("CCO")
        resp = client.post("/api/search", json={"smiles": key, "mode": "exact"})
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert len(data["results"]) == 1
        assert data["results"][0]["name"] == "Ethanol"

    def test_exact_match_compound_without_inchi_key_not_returned(self, client, tmp_db):
        db_path, _ = tmp_db
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO compounds (name, smiles, inchi_key) VALUES (?,?,?)",
                ("NullKey", "CCO", None)
            )
            conn.commit()
        resp = client.post("/api/search", json={"smiles": "CCO", "mode": "exact"})
        data = json.loads(resp.data)
        names = [r["name"] for r in data["results"]]
        assert "NullKey" not in names

    def test_exact_search_results_have_pdf_count(self, client):
        _add_compound(client, name="Ethanol", smiles="CCO")
        resp = client.post("/api/search", json={"smiles": "CCO", "mode": "exact"})
        data = json.loads(resp.data)
        assert "pdf_count" in data["results"][0]


class TestOverlapResolution:
    """Tests for _resolve_2d_overlaps applied via mol_to_svg."""

    def _make_overlapping_mol(self):
        from rdkit import Chem
        from rdkit.Chem import AllChem
        mol = Chem.MolFromSmiles('c1ccc(-c2ccccc2)cc1')
        AllChem.Compute2DCoords(mol)
        conf = mol.GetConformer()
        p0 = conf.GetAtomPosition(0)
        conf.SetAtomPosition(6, (p0.x, p0.y, 0.0))
        return mol

    def test_resolve_moves_overlapping_atoms_apart(self):
        from math import sqrt
        from rdkit import Chem
        from rdkit.Chem import AllChem
        from molibrary.app import _resolve_2d_overlaps
        mol = self._make_overlapping_mol()
        conf = mol.GetConformer()
        p0 = conf.GetAtomPosition(0)
        p6 = conf.GetAtomPosition(6)
        dist_before = sqrt((p0.x - p6.x) ** 2 + (p0.y - p6.y) ** 2)
        assert dist_before < 0.01
        _resolve_2d_overlaps(mol)
        p0 = conf.GetAtomPosition(0)
        p6 = conf.GetAtomPosition(6)
        dist_after = sqrt((p0.x - p6.x) ** 2 + (p0.y - p6.y) ** 2)
        assert dist_after > dist_before

    def test_resolve_no_change_when_no_overlap(self):
        from rdkit import Chem
        from rdkit.Chem import AllChem
        from molibrary.app import _resolve_2d_overlaps
        mol = Chem.MolFromSmiles('CCO')
        AllChem.Compute2DCoords(mol)
        conf = mol.GetConformer()
        before = [(conf.GetAtomPosition(i).x, conf.GetAtomPosition(i).y)
                  for i in range(mol.GetNumAtoms())]
        _resolve_2d_overlaps(mol)
        after = [(conf.GetAtomPosition(i).x, conf.GetAtomPosition(i).y)
                 for i in range(mol.GetNumAtoms())]
        assert before == after

    def test_resolve_single_atom_no_crash(self):
        from rdkit import Chem
        from rdkit.Chem import AllChem
        from molibrary.app import _resolve_2d_overlaps
        mol = Chem.MolFromSmiles('[He]')
        AllChem.Compute2DCoords(mol)
        _resolve_2d_overlaps(mol)

    def test_mol_to_svg_produces_valid_svg_after_overlap_fix(self, client):
        from molibrary.app import mol_to_svg
        mol_to_svg.cache_clear()
        svg = mol_to_svg('c1ccc(-c2ccccc2)cc1', 400, 400)
        assert svg is not None
        assert '<svg' in svg

    def test_bonded_atoms_not_considered_overlapping(self):
        from rdkit import Chem
        from rdkit.Chem import AllChem
        from molibrary.app import _resolve_2d_overlaps
        mol = Chem.MolFromSmiles('CC')
        AllChem.Compute2DCoords(mol)
        conf = mol.GetConformer()
        before = [(conf.GetAtomPosition(i).x, conf.GetAtomPosition(i).y)
                  for i in range(mol.GetNumAtoms())]
        _resolve_2d_overlaps(mol)
        after = [(conf.GetAtomPosition(i).x, conf.GetAtomPosition(i).y)
                 for i in range(mol.GetNumAtoms())]
        assert before == after


class TestSvgCache:
    def test_same_smiles_returns_cached_result(self, client):
        from molibrary.app import mol_to_svg
        mol_to_svg.cache_clear()
        r1 = mol_to_svg("CCO", 300, 200)
        r2 = mol_to_svg("CCO", 300, 200)
        assert r1 is r2
        assert mol_to_svg.cache_info().hits >= 1

    def test_different_smiles_are_cached_separately(self, client):
        from molibrary.app import mol_to_svg
        mol_to_svg.cache_clear()
        svg1 = mol_to_svg("CCO", 300, 200)
        svg2 = mol_to_svg("c1ccccc1", 300, 200)
        assert svg1 != svg2
        assert mol_to_svg.cache_info().currsize == 2

    def test_different_dimensions_cached_separately(self, client):
        from molibrary.app import mol_to_svg
        mol_to_svg.cache_clear()
        mol_to_svg("CCO", 100, 80)
        mol_to_svg("CCO", 400, 300)
        assert mol_to_svg.cache_info().currsize == 2

    def test_svg_endpoint_returns_etag(self, client):
        resp = client.get("/api/structure.svg?smiles=CCO&w=300&h=200")
        assert resp.status_code == 200
        assert 'ETag' in resp.headers
        assert resp.headers['ETag'].startswith('"')

    def test_svg_endpoint_304_on_matching_etag(self, client):
        r1 = client.get("/api/structure.svg?smiles=CCO&w=300&h=200")
        etag = r1.headers['ETag']
        r2 = client.get("/api/structure.svg?smiles=CCO&w=300&h=200",
                        headers={'If-None-Match': etag})
        assert r2.status_code == 304

    def test_svg_endpoint_200_after_smiles_change(self, client):
        r1 = client.get("/api/structure.svg?smiles=CCO&w=300&h=200")
        r2 = client.get("/api/structure.svg?smiles=CCCO&w=300&h=200")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.headers['ETag'] != r2.headers['ETag']

    def test_svg_cache_control_header(self, client):
        resp = client.get("/api/structure.svg?smiles=CCO&w=300&h=200")
        assert 'Cache-Control' in resp.headers
        assert 'max-age' in resp.headers['Cache-Control']

    def test_edited_compound_serves_fresh_svg(self, client):
        _add_compound(client, name="Ethanol", smiles="CCO")
        r_before = client.get("/api/structure.svg?smiles=CCO&w=240&h=160")
        client.post("/compound/1/edit", data={
            "name": "Propanol", "smiles": "CCCO", "molblock": "", "notes": "", "tags": ""
        }, follow_redirects=True)
        r_after = client.get("/api/structure.svg?smiles=CCCO&w=240&h=160")
        assert r_before.status_code == 200
        assert r_after.status_code == 200
        assert r_before.headers['ETag'] != r_after.headers['ETag']


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


class TestApiAddCompound:
    def test_add_returns_201_with_id(self, client):
        resp = client.post("/api/compounds", json={"name": "Aspirin", "smiles": "CC(=O)Oc1ccccc1C(=O)O"})
        assert resp.status_code == 201
        data = json.loads(resp.data)
        assert "id" in data
        assert isinstance(data["id"], int)

    def test_add_persists_compound(self, client):
        client.post("/api/compounds", json={"name": "Caffeine", "smiles": "Cn1cnc2c1c(=O)n(c(=O)n2C)C"})
        resp = client.get("/api/compounds?q=Caffeine")
        data = json.loads(resp.data)
        assert any(r["name"] == "Caffeine" for r in data["results"])

    def test_add_missing_name_returns_400(self, client):
        resp = client.post("/api/compounds", json={"smiles": "CCO"})
        assert resp.status_code == 400
        assert "error" in json.loads(resp.data)

    def test_add_no_smiles_is_allowed(self, client):
        resp = client.post("/api/compounds", json={"name": "Unknown"})
        assert resp.status_code == 201

    def test_add_stores_inchi_key(self, client):
        client.post("/api/compounds", json={"name": "Ethanol", "smiles": "CCO"})
        resp = client.get("/api/compounds?q=Ethanol")
        data = json.loads(resp.data)
        assert data["results"][0]["inchi_key"] is not None

    def test_add_stores_author_and_notes(self, client):
        client.post("/api/compounds", json={
            "name": "Test", "smiles": "C", "author": "Alice", "notes": "test notes"
        })
        resp = client.get("/api/compounds?q=Test")
        r = json.loads(resp.data)["results"][0]
        assert r["author"] == "Alice"
        assert r["notes"] == "test notes"

    def test_add_stores_tags(self, client):
        client.post("/api/compounds", json={
            "name": "Test", "smiles": "C", "tags": "#NMR #MS"
        })
        resp = client.get("/api/compounds?q=Test")
        r = json.loads(resp.data)["results"][0]
        assert r["tags"] == "NMR,MS"

    def test_search_mode_validation(self, client):
        resp = client.post("/api/search", json={"smiles": "CCO", "mode": "badmode"})
        assert resp.status_code == 400

    def test_threshold_validation(self, client):
        resp = client.post("/api/search", json={
            "smiles": "CCO", "mode": "similarity", "threshold": "notanumber"
        })
        assert resp.status_code == 400


class TestVersionInfo:
    def test_version_constant_exists(self):
        from molibrary.app import VERSION
        assert VERSION == "1.1.0"

    def test_version_shown_in_footer(self, client):
        resp = client.get("/")
        assert b"1.1.0" in resp.data
