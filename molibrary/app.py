import hashlib
import os
import re
import sqlite3
import uuid
import urllib.parse
from functools import lru_cache
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

# Project root is one level above this file (chem_db_web/)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__,
            template_folder=os.path.join(_ROOT, 'templates'),
            static_folder=os.path.join(_ROOT, 'static'))
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB max upload

BASE_DIR  = _ROOT
DB_PATH   = os.path.join(BASE_DIR, 'compounds.db')
PDF_DIR   = os.path.join(BASE_DIR, 'pdfs')
os.makedirs(PDF_DIR, exist_ok=True)

JSME_LOCAL = os.path.isfile(os.path.join(BASE_DIR, 'static', 'jsme', 'jsme.nocache.js'))

@app.context_processor
def _inject_globals():
    return {
        'jsme_local': JSME_LOCAL,
        'rdkit': RDKIT
    }


# ── Database ──────────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS compounds (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT NOT NULL,
                author       TEXT,
                smiles       TEXT,
                molblock     TEXT,
                inchi_key    TEXT,
                pdf_filename TEXT,
                notes        TEXT,
                created_at   TEXT DEFAULT (datetime('now','localtime'))
            )
        ''')
        # Migrations: add columns that may be absent in older databases
        existing_cols = [row[1] for row in conn.execute("PRAGMA table_info(compounds)").fetchall()]
        for col, defn in [('inchi_key', 'TEXT'), ('author', 'TEXT')]:
            if col not in existing_cols:
                conn.execute(f'ALTER TABLE compounds ADD COLUMN {col} {defn}')
        conn.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_2d_overlaps(mol, max_iter: int = 10) -> None:
    """Post-process an RDKit 2-D conformer to separate overlapping non-bonded atoms.

    Algorithm (adapted from mol_geometry.resolve_2d_overlaps):
      1. Collect all non-bonded atom pairs whose distance < threshold.
      2. Union-Find groups the overlapping atoms.
      3. BFS within each group splits it into bonded fragments.
      4. The smaller fragment is pushed away from the larger one along the
         centroid-to-centroid direction by move_dist.
      5. Repeat until no overlaps remain or max_iter is reached.

    Threshold and move distance are scaled to the molecule's average bond
    length so the result is correct regardless of RDKit's internal units.
    """
    from math import sqrt
    from collections import deque

    conf = mol.GetConformer()
    n = mol.GetNumAtoms()
    if n < 2:
        return

    # ── adjacency + reference bond length ────────────────────────────────────
    bonded: set = set()
    adj: dict = {i: [] for i in range(n)}
    bond_lengths = []
    for bond in mol.GetBonds():
        i, j = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
        bonded.add((min(i, j), max(i, j)))
        adj[i].append(j)
        adj[j].append(i)
        pi, pj = conf.GetAtomPosition(i), conf.GetAtomPosition(j)
        bl = sqrt((pi.x - pj.x) ** 2 + (pi.y - pj.y) ** 2)
        if bl > 0:
            bond_lengths.append(bl)

    avg_bond  = (sum(bond_lengths) / len(bond_lengths)) if bond_lengths else 1.0
    threshold = avg_bond * 0.35   # closer than 35% of a bond = overlap
    move_dist = avg_bond * 1.2    # push by 1.2× a bond length per iteration

    for _ in range(max_iter):
        # ── snapshot positions ────────────────────────────────────────────────
        pos = {}
        for i in range(n):
            p = conf.GetAtomPosition(i)
            pos[i] = (p.x, p.y)

        # ── collect overlapping non-bonded pairs ──────────────────────────────
        pairs = []
        for i in range(n):
            for j in range(i + 1, n):
                if (min(i, j), max(i, j)) in bonded:
                    continue
                dx = pos[i][0] - pos[j][0]
                dy = pos[i][1] - pos[j][1]
                if sqrt(dx * dx + dy * dy) < threshold:
                    pairs.append((i, j))

        if not pairs:
            break

        # ── Union-Find ────────────────────────────────────────────────────────
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i, j in pairs:
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[rj] = ri

        groups: dict = {}
        for i in range(n):
            groups.setdefault(find(i), []).append(i)

        moved_this_iter = False
        for root, members in groups.items():
            if len(members) < 2:
                continue

            # pick representative overlapping pair in this group
            rep = next(((a, b) for a, b in pairs if find(a) == root), None)
            if rep is None:
                continue

            # ── BFS: split members into bonded fragments ───────────────────
            group_set = set(members)
            visited: set = set()
            fragments = []
            for seed in members:
                if seed in visited:
                    continue
                frag: set = set()
                q = deque([seed])
                visited.add(seed)
                frag.add(seed)
                while q:
                    cur = q.popleft()
                    for nb in adj[cur]:
                        if nb in group_set and nb not in visited:
                            visited.add(nb)
                            frag.add(nb)
                            q.append(nb)
                fragments.append(frag)

            if len(fragments) < 2:
                continue

            a0, b0 = rep
            fa = next((f for f in fragments if a0 in f), None)
            fb = next((f for f in fragments if b0 in f), None)
            if fa is None or fb is None or fa is fb:
                continue

            # move the smaller fragment; direction = other centroid → this centroid
            to_move = fa if len(fa) <= len(fb) else fb
            other   = fb if to_move is fa else fa

            cx_m = sum(pos[k][0] for k in to_move) / len(to_move)
            cy_m = sum(pos[k][1] for k in to_move) / len(to_move)
            cx_o = sum(pos[k][0] for k in other)   / len(other)
            cy_o = sum(pos[k][1] for k in other)   / len(other)

            dx, dy = cx_m - cx_o, cy_m - cy_o
            d = sqrt(dx * dx + dy * dy)
            if d < 1e-9:          # centroids coincide — push horizontally
                dx, dy = move_dist, 0.0
            else:
                dx, dy = dx / d * move_dist, dy / d * move_dist

            for k in to_move:
                p = conf.GetAtomPosition(k)
                conf.SetAtomPosition(k, (p.x + dx, p.y + dy, p.z))

            moved_this_iter = True

        if not moved_this_iter:
            break


@lru_cache(maxsize=512)
def mol_to_svg(smiles: str, width=300, height=200) -> str | None:
    if not RDKIT or not smiles:
        return None
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    AllChem.Compute2DCoords(mol)
    _resolve_2d_overlaps(mol)
    drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
    drawer.drawOptions().addStereoAnnotation = True
    drawer.DrawMolecule(mol)
    drawer.FinishDrawing()
    return drawer.GetDrawingText()


def mol_to_inchi_key(smiles: str) -> str | None:
    if not RDKIT or not smiles:
        return None
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        from rdkit.Chem.inchi import MolToInchi, InchiToInchiKey
        inchi = MolToInchi(mol)
        return InchiToInchiKey(inchi) if inchi else None
    except Exception:
        return None


def save_pdf(file_obj) -> str | None:
    """Save an uploaded PDF file; returns the stored filename or None."""
    if not file_obj or not file_obj.filename:
        return None
    orig = file_obj.filename
    if not orig.lower().endswith('.pdf'):
        return None
    filename = secure_filename(orig)
    # secure_filename strips non-ASCII and leading dots:
    #   "レポート.pdf" → "pdf" (no dot, wrong extension)
    #   ".pdf"        → "" on some platforms
    if not filename or not filename.lower().endswith('.pdf'):
        filename = f"{uuid.uuid4().hex}.pdf"
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
        author   = request.form.get('author', '').strip()
        smiles   = request.form.get('smiles', '').strip()
        molblock = request.form.get('molblock', '').strip()
        notes    = request.form.get('notes', '').strip()
        if not name:
            return render_template('add.html', error='Name is required.')
        inchi_key    = mol_to_inchi_key(smiles)
        pdf_filename = save_pdf(request.files.get('pdf'))
        with get_db() as conn:
            conn.execute(
                'INSERT INTO compounds (name, author, smiles, molblock, inchi_key, pdf_filename, notes)'
                ' VALUES (?,?,?,?,?,?,?)',
                (name, author, smiles, molblock, inchi_key, pdf_filename, notes)
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
        author   = request.form.get('author', '').strip()
        smiles   = request.form.get('smiles', '').strip()
        molblock = request.form.get('molblock', '').strip()
        notes    = request.form.get('notes', '').strip()
        if not name:
            return render_template('edit.html', c=c, error='Name is required.')
        inchi_key    = mol_to_inchi_key(smiles)
        pdf_filename = c['pdf_filename']
        new_pdf = save_pdf(request.files.get('pdf'))
        if new_pdf:
            pdf_filename = new_pdf
        with get_db() as conn:
            conn.execute(
                'UPDATE compounds SET name=?,author=?,smiles=?,molblock=?,inchi_key=?,pdf_filename=?,notes=?'
                ' WHERE id=?',
                (name, author, smiles, molblock, inchi_key, pdf_filename, notes, cid)
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
    return send_from_directory(PDF_DIR, filename, mimetype='application/pdf')


@app.route('/pdf/<path:filename>/download')
def download_pdf(filename):
    return send_from_directory(PDF_DIR, filename, as_attachment=True,
                               mimetype='application/pdf')


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
    etag = f'"{hashlib.md5(svg.encode()).hexdigest()}"'
    if request.headers.get('If-None-Match') == etag:
        return '', 304
    return svg, 200, {
        'Content-Type': 'image/svg+xml',
        'ETag': etag,
        'Cache-Control': 'private, max-age=86400',
    }


@app.route('/api/compounds')
def api_compounds():
    """Text search across name, notes, InChI Key, and SMILES. No query → all compounds."""
    q = request.args.get('q', '').strip()
    with get_db() as conn:
        if q:
            rows = conn.execute(
                '''SELECT * FROM compounds
                   WHERE name LIKE ? OR notes LIKE ? OR inchi_key LIKE ? OR smiles LIKE ?
                   ORDER BY created_at DESC''',
                (f'%{q}%', f'%{q}%', f'%{q}%', f'%{q}%')
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM compounds ORDER BY created_at DESC'
            ).fetchall()
    return jsonify({'results': [dict(r) for r in rows]})


@app.route('/api/compounds', methods=['POST'])
def api_add_compound():
    """Create a new compound via JSON. PDF upload not supported through this endpoint."""
    data  = request.get_json(force=True)
    name  = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    smiles   = (data.get('smiles') or '').strip()
    author   = (data.get('author') or '').strip()
    notes    = (data.get('notes') or '').strip()
    molblock = (data.get('molblock') or '').strip()
    inchi_key = mol_to_inchi_key(smiles)
    with get_db() as conn:
        cur = conn.execute(
            'INSERT INTO compounds (name, author, smiles, molblock, inchi_key, pdf_filename, notes)'
            ' VALUES (?,?,?,?,?,?,?)',
            (name, author, smiles, molblock, inchi_key, None, notes)
        )
        conn.commit()
        new_id = cur.lastrowid
    return jsonify({'id': new_id}), 201


@app.route('/api/search', methods=['POST'])
def api_search():
    if not RDKIT:
        return jsonify({'error': 'RDKit not installed on this server.'}), 503
    data      = request.get_json(force=True)
    query_smi = (data.get('smiles') or '').strip()
    mode      = data.get('mode', 'substructure')
    if mode not in ('exact', 'substructure', 'similarity'):
        return jsonify({'error': 'Invalid search mode'}), 400
    try:
        threshold = float(data.get('threshold', 0.5))
    except (ValueError, TypeError):
        return jsonify({'error': 'Invalid threshold value'}), 400

    if not query_smi:
        return jsonify({'results': []})

    # Exact match via InChI Key — handle both SMILES and direct InChI Key input
    if mode == 'exact':
        if re.match(r'^[A-Z]{14}-[A-Z]{10}-[A-Z]$', query_smi):
            query_inchi_key = query_smi
        else:
            query_inchi_key = mol_to_inchi_key(query_smi)

        if not query_inchi_key:
            return jsonify({'error': 'Could not generate or validate InChI Key from query'}), 400
        with get_db() as conn:
            rows = conn.execute(
                'SELECT * FROM compounds WHERE inchi_key = ?', (query_inchi_key,)
            ).fetchall()
        return jsonify({'results': [dict(r) for r in rows]})

    query_mol = Chem.MolFromSmiles(query_smi)
    if query_mol is None:
        return jsonify({'error': 'Invalid query SMILES'}), 400

    with get_db() as conn:
        rows = conn.execute(
            'SELECT * FROM compounds WHERE smiles IS NOT NULL AND smiles != ""'
        ).fetchall()

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
    import argparse
    parser = argparse.ArgumentParser(description='Molibrary server')
    parser.add_argument('--host', default='0.0.0.0',
                        help='Bind address (default: 0.0.0.0 = all interfaces)')
    parser.add_argument('--port', type=int, default=5000,
                        help='Port (default: 5000)')
    parser.add_argument('--localhost', action='store_true',
                        help='Restrict to localhost only (127.0.0.1)')
    args = parser.parse_args()

    host = '127.0.0.1' if args.localhost else args.host
    init_db()
    print(f"Molibrary running on http://{host}:{args.port}")
    if host == '0.0.0.0':
        import socket
        try:
            lan_ip = socket.gethostbyname(socket.gethostname())
            print(f"  Local access : http://127.0.0.1:{args.port}")
            print(f"  Network      : http://{lan_ip}:{args.port}")
        except Exception:
            pass
    print("  Press Ctrl+C to stop.\n")
    app.run(debug=False, port=args.port, host=host)
