"""Recipient-scoped invoice delivery, using the existing billing PDF renderer."""
import hashlib
import json
import re
from html import escape
from flask import abort, session, has_request_context
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from billing_documents import invoice_document, build_pdf, pdf_response

MAX_AGE = 7 * 24 * 60 * 60


def install_invoice_message_documents(app, api):
    signer = URLSafeTimedSerializer(app.secret_key, salt='invoice-document-delivery-v1')

    def document(cur, iid, pid, owner_preview=False):
        cur.execute('SELECT student_name FROM invoices WHERE id=?', (iid,))
        row = cur.fetchone()
        cur.execute('SELECT email,COALESCE(active,1) FROM parent_profiles WHERE id=?', (pid,))
        parent = cur.fetchone()
        if not row or not parent or not parent[1]:
            abort(403)
        if not api['parent_can_access_student'](pid, row[0]) or not api['parent_has_student_permission'](pid, row[0], 'view_billing'):
            abort(403)
        return invoice_document(cur, iid, pid, owner_preview=owner_preview), parent[0]

    def fingerprint(doc):
        # Settlement can change; the originally shared tuition and recipient cannot.
        value = {k: doc[k] for k in ('number', 'payer', 'issued', 'due', 'share')}
        value['lines'] = [x for x in doc['lines'] if x.get('student') != 'Credit card surcharge']
        return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()

    def token_for(cur, iid, pid):
        doc, _ = document(cur, iid, pid, owner_preview=has_request_context() and bool(api['require_owner']()))
        return signer.dumps(dict(iid=iid, pid=pid, digest=fingerprint(doc)))

    def load_token(token, destination=None):
        try:
            value = signer.loads(token, max_age=MAX_AGE)
        except (BadSignature, SignatureExpired):
            abort(403)
        conn = api['sqlite3'].connect('hmusic.db')
        try:
            doc, email = document(conn.cursor(), value['iid'], value['pid'], owner_preview=destination is None and has_request_context() and bool(api['require_owner']()))
            if value['digest'] != fingerprint(doc):
                abort(403)
            if destination is not None and str(email or '').strip().casefold() != destination.strip().casefold():
                abort(403)
            return doc
        finally:
            conn.close()

    def attachment(destination, body):
        # Only the signed invoice explicitly included in this notification is attached.
        matches = re.findall(r'/invoice-share/([A-Za-z0-9_.-]+)/invoice\.pdf', body or '')
        if not matches:
            return None
        if len(set(matches)) != 1:
            abort(403)
        doc = load_token(matches[0], destination)
        return f"H-Music-invoice-{doc['number']}.pdf", build_pdf(doc, 'invoice')

    @app.route('/invoice-share/<token>/<kind>.pdf')
    def shared_invoice_document(token, kind):
        if kind not in ('invoice', 'receipt'):
            abort(404)
        return pdf_response(load_token(token), kind)

    def preview(iid, pid, message, enrollment_id):
        conn = api['sqlite3'].connect('hmusic.db')
        try:
            token = token_for(conn.cursor(), iid, pid)
        finally:
            conn.close()
        base = api['hmusic_public_app_url'](f'/invoice-share/{token}/invoice.pdf')
        session['invoice_send_preview'] = hashlib.sha256(token.encode()).hexdigest()
        return f'''<main style="max-width:800px;margin:30px auto;font-family:Arial;padding:20px">
        <h1>Preview Invoice #{iid}</h1><p>Nothing has been sent. Email includes the Invoice PDF; the message includes its download link.</p>
        <a href="{escape(base)}" target="_blank" rel="noopener">Download Invoice PDF</a>
        <iframe title="Invoice preview" src="{escape(base)}?inline=1" style="width:100%;height:550px;border:1px solid #ddd"></iframe>
        <form method="post"><input type="hidden" name="action" value="confirm_send">
        <input type="hidden" name="invoice_id" value="{iid}"><input type="hidden" name="document_token" value="{escape(token)}">
        <label for="invoice-message">Message to parent</label><textarea id="invoice-message" name="message_body" required style="width:100%;min-height:200px">{escape(message)}</textarea>
        <p>Included automatically: View / download Invoice<br>{escape(base)}</p>
        <button type="submit">Confirm — Send Invoice + Message</button>
        <a href="/enrollment/{enrollment_id}">Back without sending</a></form></main>'''

    api['invoice_document_token'] = token_for
    api['invoice_document_load_token'] = load_token
    api['invoice_message_attachment'] = attachment
    api['invoice_message_preview'] = preview
