"""Owner-only website drafts and atomic publishing, stored in the CRM database."""
import json
import re
import sqlite3
from pathlib import Path
from flask import request, redirect, jsonify, send_file

BASE = Path(__file__).with_name('website_cms')
CATEGORIES = {'programs', 'teachers', 'about', 'events', 'resources', 'services', 'careers'}

def register_website_cms(app, connect, is_owner, csrf_token):
    def db():
        conn = connect()
        conn.execute('CREATE TABLE IF NOT EXISTS website_cms (id INTEGER PRIMARY KEY, draft TEXT NOT NULL, published TEXT NOT NULL, revision INTEGER NOT NULL)')
        seed = (BASE / 'seed.json').read_text()
        conn.execute('INSERT OR IGNORE INTO website_cms (id,draft,published,revision) VALUES (1,?,?,0)', (seed, seed))
        conn.commit()
        return conn

    @app.get('/website-admin')
    def website_admin():
        if not is_owner():
            return redirect('/owner_login')
        return (BASE / 'index.html').read_text().replace('__CSRF__', csrf_token())

    @app.get('/api/website/content')
    def website_content():
        conn = db()
        try:
            pages = json.loads(conn.execute('SELECT published FROM website_cms WHERE id=1').fetchone()[0])
        finally:
            conn.close()
        result = jsonify([p for p in pages if not p.get('hidden')])
        result.headers['Access-Control-Allow-Origin'] = '*'
        result.headers['Cache-Control'] = 'public, max-age=30'
        return result

    @app.route('/api/website/admin', methods=['GET', 'POST'])
    def website_edit():
        if not is_owner():
            return {'error': 'Owner access required'}, 403
        conn = db()
        try:
            if request.method == 'GET':
                row = conn.execute('SELECT draft,revision FROM website_cms WHERE id=1').fetchone()
                return {'pages': json.loads(row[0]), 'revision': row[1]}
            data = request.get_json(silent=True) or {}
            pages = data.get('pages')
            if not isinstance(pages, list) or len(pages) > 300 or not isinstance(data.get('revision'), int):
                return {'error': 'Invalid content'}, 400
            ids = set()
            for p in pages:
                if not isinstance(p, dict) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,119}', str(p.get('id',''))) or p['id'] in ids:
                    return {'error': 'Page IDs must be unique lowercase letters, numbers or hyphens'}, 400
                ids.add(p['id'])
                if p.get('category') not in CATEGORIES or not isinstance(p.get('title'), str) or not p['title'].strip():
                    return {'error': 'Every page needs a title and category'}, 400
                # Existing imported HTML is retained. New editor content is plain text,
                # escaped by the public renderer. Image URLs cannot run scripts.
                for key in ('text', 'html', 'editorText', 'titleZh', 'summary', 'summaryZh'):
                    if key in p and not isinstance(p[key], str):
                        return {'error': 'Invalid page text'}, 400
                images = p.get('images', [])
                if not isinstance(images, list) or len(images)>50 or any(not isinstance(i,str) or not (i.startswith('assets/') or i.startswith('https://') or re.match(r'^data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$',i)) for i in images):
                    return {'error': 'Use HTTPS images or PNG/JPEG/WebP uploads'}, 400
            payload = json.dumps(pages, ensure_ascii=False)
            if len(payload.encode()) > 12 * 1024 * 1024:
                return {'error': 'Content exceeds 12 MB; use smaller images'}, 413
            publish = data.get('publish') is True
            sql = 'UPDATE website_cms SET draft=?, revision=revision+1' + (', published=?' if publish else '') + ' WHERE id=1 AND revision=?'
            args = (payload,payload,data['revision']) if publish else (payload,data['revision'])
            cursor = conn.execute(sql,args)
            if cursor.rowcount != 1:
                conn.rollback()
                return {'error': 'Another editor saved changes. Reload before saving.'}, 409
            conn.commit()
            return {'ok': True, 'revision': data['revision']+1, 'published':publish}
        finally:
            conn.close()
