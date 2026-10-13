"""Import authenticated parent email replies into their existing app conversations."""
import base64
from datetime import datetime, timedelta
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
import hashlib
from html import unescape
from html.parser import HTMLParser
import imaplib
import os
import re
import threading
import time

_sync_lock = threading.Lock()
_worker_lock = threading.Lock()
_worker_pid = None


def mailbox_config(env=None):
    env = os.environ if env is None else env
    if env.get('HMUSIC_EMAIL_REPLY_SYNC', '1') == '0':
        return None
    host = env.get('HMUSIC_IMAP_HOST')
    if not host and env.get('HMUSIC_SMTP_HOST') == 'smtp.gmail.com':
        host = 'imap.gmail.com'
    user = env.get('HMUSIC_IMAP_USER') or env.get('HMUSIC_SMTP_USER')
    password = env.get('HMUSIC_IMAP_PASSWORD') or env.get('HMUSIC_SMTP_PASSWORD')
    if not (host and user and password):
        return None
    return dict(host=host, user=user, password=password,
                folder=env.get('HMUSIC_IMAP_FOLDER', 'INBOX'),
                port=int(env.get('HMUSIC_IMAP_PORT', '993')))


def ensure_schema(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS inbound_message_emails (
        message_key TEXT PRIMARY KEY, thread_id BIGINT,
        app_message_id BIGINT, imported_at TEXT
    )''')
    conn.commit()


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.quoted = 0
        self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag == 'blockquote':
            self.quoted += 1
        if tag in ('br', 'p', 'div', 'li'):
            self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.hidden:
            self.hidden -= 1
        if tag == 'blockquote' and self.quoted:
            self.quoted -= 1
        if tag in ('p', 'div', 'li'):
            self.parts.append('\n')
    def handle_data(self, text):
        if not self.hidden and not self.quoted:
            self.parts.append(text)


def text_parts(message):
    plain, html = [], []
    for part in message.walk():
        if part.get_content_disposition() == 'attachment':
            continue
        kind = part.get_content_type()
        if kind not in ('text/plain', 'text/html'):
            continue
        try:
            value = part.get_content()
        except (LookupError, UnicodeError):
            value = (part.get_payload(decode=True) or b'').decode('utf-8', errors='replace')
        (plain if kind == 'text/plain' else html).append(value)
    return plain, html


def reply_text(plain, html):
    if plain:
        text = '\n'.join(plain)
    else:
        parser = PlainHTML()
        parser.feed('\n'.join(html))
        text = unescape(''.join(parser.parts))
    lines = []
    for line in text.splitlines():
        if re.match(r'^\s*(On .{1,300}wrote:|在.{1,300}写道[:：]|-{2,}\s*Original Message|From:\s)', line, re.I):
            break
        if line.lstrip().startswith('>'):
            continue
        lines.append(line)
    return '\n'.join(lines).strip()[:100000]


def authenticated_sender(message):
    """Trust the receiving Gmail server's DMARC decision, not a quoted email header."""
    sender = parseaddr(str(message.get('From', '')))[1].strip().lower()
    auth = str(message.get('Authentication-Results', ''))
    receiver = auth.split(';', 1)[0].strip().lower()
    if not sender or receiver != 'mx.google.com' or not re.search(r'\bdmarc=pass\b', auth, re.I):
        return None
    return sender


def import_reply(conn, raw, api):
    if len(raw) > 55 * 1024 * 1024:
        return dict(imported=False, reason='too_large')
    message = BytesParser(policy=policy.default).parsebytes(raw)
    sender = authenticated_sender(message)
    if not sender or str(message.get('Auto-Submitted', 'no')).lower() != 'no':
        return dict(imported=False, reason='not_authenticated_parent_reply')
    plain, html = text_parts(message)
    references = ' '.join(str(message.get(k, '')) for k in ('In-Reply-To', 'References'))
    thread_ids = set(re.findall(r'hmusic-thread-(\d+)', references))
    if not thread_ids:
        thread_ids = set(re.findall(r'https?://hmusic-crm\.onrender\.com/message_thread/(\d+)', '\n'.join(plain + html)))
        # Legacy emails use a relative Open: link in their footer.
        thread_ids.update(re.findall(r'\bOpen:\s*/message_thread/(\d+)', '\n'.join(plain)))
    if len(thread_ids) != 1:
        return dict(imported=False, reason='missing_or_ambiguous_conversation')
    thread_id = int(next(iter(thread_ids)))
    cursor = conn.cursor()
    cursor.execute('''SELECT p.id, p.parent_name, t.parent_id, t.teacher_name
        FROM message_threads t JOIN parent_profiles p ON LOWER(TRIM(p.email)) = ?
        WHERE t.id = ? AND COALESCE(p.active,1)=1 AND (
            p.id=t.parent_id OR EXISTS (
                SELECT 1 FROM message_participants mp WHERE mp.thread_id=t.id
                AND mp.participant_role='parent' AND mp.participant_key=CAST(p.id AS TEXT)
                AND mp.active=1
            )
        )''', (sender, thread_id))
    parent = cursor.fetchone()
    if not parent:
        return dict(imported=False, reason='parent_not_in_conversation')
    body = reply_text(plain, html)
    attachments = []
    for part in message.iter_attachments():
        if part.get_content_type() not in api['allowed_mime_types'] or not part.get_filename():
            continue
        content = part.get_payload(decode=True) or b''
        if len(content) <= 50 * 1024 * 1024:
            attachments.append((part.get_filename(), part.get_content_type(), content))
    if not body and not attachments:
        return dict(imported=False, reason='empty_reply')
    key = str(message.get('Message-ID') or '').strip() or hashlib.sha256(raw).hexdigest()
    # The primary key reserves the email inside the same transaction as its message.
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    cursor.execute('''INSERT OR IGNORE INTO inbound_message_emails
        (message_key,thread_id,imported_at) VALUES(?,?,?)''', (key, thread_id, now))
    if cursor.rowcount == 0:
        return dict(imported=False, reason='duplicate')
    api['sync_participants'](cursor, thread_id, parent[2], parent[3], owner_observer=1)
    cursor.execute('''INSERT INTO messages
        (thread_id,sender_role,sender_name,recipient_role,body,channel,created_at)
        VALUES(?,'parent',?,'participants',?,'email',?)''',
        (thread_id, parent[1] or 'Parent', body or 'New email attachment', now))
    message_id = cursor.lastrowid
    for index, (filename, mime, content) in enumerate(attachments):
        stored = f'{message_id}_email_{index}_{api["safe_filename"](filename)}'
        cursor.execute('''INSERT INTO message_attachments
            (message_id,original_filename,stored_filename,mime_type,file_size,created_at,content_base64)
            VALUES(?,?,?,?,?,?,?)''',
            (message_id, filename, stored, mime, len(content), now, base64.b64encode(content).decode('ascii')))
    cursor.execute('UPDATE message_threads SET updated_at=? WHERE id=?', (now, thread_id))
    cursor.execute('UPDATE inbound_message_emails SET app_message_id=? WHERE message_key=?', (message_id,key))
    cursor.execute('''SELECT DISTINCT participant_role,participant_key FROM message_participants
        WHERE thread_id=? AND active=1 AND participant_role IN ('teacher','owner')''', (thread_id,))
    for role, user_key in cursor.fetchall():
        title = f'New message from {parent[1] or "Parent"}'
        link = f'/message_thread/{thread_id}'
        cursor.execute('''INSERT INTO notifications
            (user_role,user_key,title,body,link_url,related_type,related_id,created_at)
            VALUES(?,?,?,?,?,'message',?,?)''',
            (role, user_key, title, body or 'New email attachment', link, message_id, now))
        cursor.execute('''INSERT INTO notification_delivery_queue
            (user_role,user_key,channel,destination,title,body,link_url,related_type,related_id,status,created_at)
            VALUES(?,?,'push',?,?,?,?, 'message',?,'pending',?)''',
            (role,user_key,f'{role}:{user_key}',title,body or 'New email attachment',link,message_id,now))
    return dict(imported=True, thread_id=thread_id, message_id=message_id)


def sync_mailbox(api, config=None, imap_factory=imaplib.IMAP4_SSL):
    config = config or mailbox_config()
    if not config:
        return dict(configured=False, imported=0)
    if not _sync_lock.acquire(blocking=False):
        return dict(configured=True, imported=0, busy=True)
    client = conn = None
    imported = 0
    try:
        conn = api['connect']()
        ensure_schema(conn)
        client = imap_factory(config['host'], config['port'], timeout=20)
        client.login(config['user'], config['password'])
        status, _ = client.select(config['folder'], readonly=True)
        if status != 'OK':
            raise RuntimeError('Mailbox unavailable')
        since = (datetime.now() - timedelta(days=14)).strftime('%d-%b-%Y')
        status, data = client.uid('search', None, 'SINCE', since)
        if status != 'OK':
            raise RuntimeError('Mailbox search failed')
        cursor = conn.cursor()
        parent_emails = {str(r[0]).strip().lower() for r in cursor.execute(
            "SELECT email FROM parent_profiles WHERE COALESCE(active,1)=1 AND email IS NOT NULL").fetchall()}
        conn.commit()
        uids = (data[0] or b'').split()[-500:]
        pending_headers = []
        for start in range(0, len(uids), 50):
            group = b','.join(uids[start:start + 50])
            status, headers = client.uid('fetch', group, '(UID BODY.PEEK[HEADER.FIELDS (FROM MESSAGE-ID)])')
            if status != 'OK':
                continue
            for item in headers or []:
                if not isinstance(item, tuple):
                    continue
                uid_match = re.search(rb'UID (\d+)', item[0])
                if uid_match:
                    pending_headers.append((uid_match.group(1), item[1]))
        for uid, header_raw in pending_headers:
            header = BytesParser(policy=policy.default).parsebytes(header_raw)
            if parseaddr(str(header.get('From','')))[1].lower() not in parent_emails:
                continue
            key = str(header.get('Message-ID','')).strip()
            if key and cursor.execute('SELECT 1 FROM inbound_message_emails WHERE message_key=?',(key,)).fetchone():
                continue
            status, data = client.uid('fetch', uid, '(RFC822.SIZE BODY.PEEK[])')
            chunks = [item[1] for item in data or [] if isinstance(item, tuple)]
            if status != 'OK' or not chunks:
                continue
            try:
                result = import_reply(conn, chunks[0], api)
                conn.commit()
                imported += int(result['imported'])
            except Exception:
                conn.rollback()
                api['logger'].exception('Parent email reply import failed for mailbox UID %s', uid.decode())
        return dict(configured=True, imported=imported)
    finally:
        if client:
            try: client.logout()
            except Exception: pass
        if conn:
            conn.close()
        _sync_lock.release()


def start_worker(api):
    """Start after Gunicorn forks; never create a thread in the preloaded parent."""
    global _worker_pid
    if not mailbox_config():
        return
    with _worker_lock:
        if _worker_pid == os.getpid():
            return
        _worker_pid = os.getpid()
        def run():
            while True:
                try:
                    result = sync_mailbox(api)
                    if result.get('imported'):
                        api['logger'].info('Imported %s parent email replies', result['imported'])
                except Exception as exc:
                    api['logger'].warning('Email reply mailbox sync failed (%s)',type(exc).__name__)
                time.sleep(60)
        threading.Thread(target=run, name='parent-email-replies', daemon=True).start()
