import os
import sqlite3
import urllib.parse
from io import BytesIO

from flask import (Flask, abort, jsonify, redirect, render_template,
                   request, send_from_directory, url_for)
from werkzeug.utils import secure_filename

try:
    from rdkit import Chem, DataStructs
    from rdkit.Chem import AllChem, Draw
    from rdkit.Chem.Draw import rdMolDraw2D
    RDKIT = True
except ImportError:
    RDKIT = False

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB max upload

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE_DIR, 'compounds.db')
PDF_DIR  = os.path.join(BASE_DIR, 'pdfs')
os.makedirs(PDF_DIR, exist_ok=True)


# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS compounds (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL,
                smiles      TEXT,
                molblock    TEXT,
                pdf_filename TEXT,
                notes       TEXT,
                created_at  TEXT DEFAULT (datetime('now','localtime'))
            )
        ''')
        conn.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def mol_to_svg(smiles: str, width=300, height=200) -> str | None:
    if not RDKIT or not smiles:
        return None
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
    drawer.drawOptions().addStereoAnnotation = True
    drawer.DrawMolecule(mol)
    drawer.FinishDrawing()
    return drawer.GetDrawingText()


def save_pdf(file_obj) -> str | None:
    if not file_obj or not file_obj.filename:
        return None
    filename = secure_filename(file_obj.filename)
    if not filename.lower().endswith('.pdf'):
        return None
    file_obj.save(os.path.join(PDF_DIR, filename))
    return filename


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    with get_db() as conn:
        compounds = conn.execute(
            'SELECT * FROM compounds ORDER BY created_at DESC'
        ).fetchall()
    return render_template('index.html', compounds=compounds)


@app.route('/add', methods=['GET', 'POST'])
def add():
    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        smiles   = request.form.get('smiles', '').strip()
        molblock = request.form.get('molblock', '').strip()
        notes    = request.form.get('notes', '').strip()
        if not name:
            return render_template('add.html', error='Name is required.')
        pdf_filename = save_pdf(request.files.get('pdf'))
        with get_db() as conn:
            conn.execute(
                'INSERT INTO compounds (name, smiles, molblock, pdf_filename, notes) VALUES (?,?,?,?,?)',
                (name, smiles, molblock, pdf_filename, notes)
            )
            conn.commit()
        return redirect(url_for('index'))
    return render_template('add.html')


@app.route('/compound/<int:cid>')
def view_compound(cid):
    with get_db() as conn:
        c = conn.execute('SELECT * FROM compounds WHERE id=?', (cid,)).fetchone()
    if not c:
        abort(404)
    svg = mol_to_svg(c['smiles'], 400, 300)
    return render_template('compound.html', c=c, svg=svg)


@app.route('/compound/<int:cid>/edit', methods=['GET', 'POST'])
def edit_compound(cid):
    with get_db() as conn:
        c = conn.execute('SELECT * FROM compounds WHERE id=?', (cid,)).fetchone()
    if not c:
        abort(404)
    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        smiles   = request.form.get('smiles', '').strip()
        molblock = request.form.get('molblock', '').strip()
        notes    = request.form.get('notes', '').strip()
        if not name:
            return render_template('edit.html', c=c, error='Name is required.')
        pdf_filename = c['pdf_filename']
        new_pdf = save_pdf(request.files.get('pdf'))
        if new_pdf:
            pdf_filename = new_pdf
        with get_db() as conn:
            conn.execute(
                'UPDATE compounds SET name=?,smiles=?,molblock=?,pdf_filename=?,notes=? WHERE id=?',
                (name, smiles, molblock, pdf_filename, notes, cid)
            )
            conn.commit()
        return redirect(url_for('view_compound', cid=cid))
    return render_template('edit.html', c=c)


@app.route('/compound/<int:cid>/delete', methods=['POST'])
def delete_compound(cid):
    with get_db() as conn:
        conn.execute('DELETE FROM compounds WHERE id=?', (cid,))
        conn.commit()
    return redirect(url_for('index'))


@app.route('/pdf/<path:filename>')
def serve_pdf(filename):
    return send_from_directory(PDF_DIR, filename)


@app.route('/search')
def search():
    return render_template('search.html', rdkit=RDKIT)


# ── API ───────────────────────────────────────────────────────────────────────

@app.route('/api/structure.svg')
def structure_svg():
    smiles = request.args.get('smiles', '')
    w = int(request.args.get('w', 280))
    h = int(request.args.get('h', 180))
    svg = mol_to_svg(smiles, w, h)
    if svg is None:
        abort(400)
    return svg, 200, {'Content-Type': 'image/svg+xml'}


@app.route('/api/search', methods=['POST'])
def api_search():
    if not RDKIT:
        return jsonify({'error': 'RDKit not installed on this server.'}), 503
    data        = request.get_json(force=True)
    query_smi   = (data.get('smiles') or '').strip()
    mode        = data.get('mode', 'substructure')   # substructure | similarity
    threshold   = float(data.get('threshold', 0.5))

    if not query_smi:
        return jsonify({'results': []})

    query_mol = Chem.MolFromSmiles(query_smi)
    if query_mol is None:
        return jsonify({'error': 'Invalid query SMILES'}), 400

    with get_db() as conn:
        rows = conn.execute('SELECT * FROM compounds WHERE smiles IS NOT NULL AND smiles != ""').fetchall()

    results = []
    if mode == 'substructure':
        for row in rows:
            mol = Chem.MolFromSmiles(row['smiles'])
            if mol and mol.HasSubstructMatch(query_mol):
                results.append(dict(row))
    else:  # similarity
        fp_q = AllChem.GetMorganFingerprintAsBitVect(query_mol, 2, 2048)
        for row in rows:
            mol = Chem.MolFromSmiles(row['smiles'])
            if not mol:
                continue
            fp = AllChem.GetMorganFingerprintAsBitVect(mol, 2, 2048)
            sim = DataStructs.TanimotoSimilarity(fp_q, fp)
            if sim >= threshold:
                r = dict(row)
                r['similarity'] = round(sim, 3)
                results.append(r)
        results.sort(key=lambda x: x.get('similarity', 0), reverse=True)

    return jsonify({'results': results})


if __name__ == '__main__':
    init_db()
    print("ChemDBWeb running at http://127.0.0.1:5000")
    app.run(debug=False, port=5000, host='127.0.0.1')
