"""Build conversation emails from the exact queued message and durable images."""
import base64
from html import escape
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}


def absolute_url(api, link):
    if not link:
        return ''
    parsed = urlsplit(str(link))
    if parsed.scheme:
        if parsed.scheme not in ('https', 'http') or not parsed.netloc:
            raise ValueError('Invalid email link.')
        return str(link)
    builder = api.get('hmusic_public_app_url')
    if builder:
        return builder(link)
    base = os.environ.get('HMUSIC_PUBLIC_URL','https://hmusic-crm.onrender.com').rstrip('/')
    return base + '/' + str(link).lstrip('/')


def render_content(api, body, link):
    url = absolute_url(api,link)
    plain = str(body or '') + (f'\n\nOpen: {url}' if url else '') + '\n\nH-Music'
    button = f'<p><a href="{escape(url,quote=True)}">Open message in H-Music</a></p><p style="font-size:12px">{escape(url)}</p>' if url else ''
    html = f'''<!doctype html><html><body style="font:16px Arial,sans-serif;color:#172338;line-height:1.5">
    <p><strong>H-Music</strong></p><div style="white-space:pre-wrap">{escape(str(body or ''))}</div>{button}<p>H-Music</p></body></html>'''
    return plain,html


def message_context(api, message_id, destination, link):
    conn = api['sqlite3'].connect('hmusic.db')
    try:
        cursor=conn.cursor()
        row=cursor.execute('''SELECT t.id,t.subject,t.parent_id,t.teacher_name FROM messages m
            JOIN message_threads t ON t.id=m.thread_id WHERE m.id=?''',(message_id,)).fetchone()
        if not row:
            raise ValueError('Original message is missing.')
        path=urlsplit(str(link or '')).path
        linked=re.fullmatch(r'/message_thread/(\d+)',path)
        if not linked or int(linked[1]) != row[0]:
            raise ValueError('Message and email link do not match.')
        # Recheck access at delivery time; never infer attachments from a thread's latest reply.
        emails=cursor.execute('''SELECT p.email FROM parent_profiles p WHERE COALESCE(p.active,1)=1 AND
            (p.id=? OR EXISTS (SELECT 1 FROM message_participants mp WHERE mp.thread_id=? AND mp.active=1
             AND mp.participant_role='parent' AND mp.participant_key=CAST(p.id AS TEXT)))
            UNION ALL SELECT t.email FROM teachers t WHERE COALESCE(t.active,1)=1 AND
            (t.teacher_name=? OR EXISTS (SELECT 1 FROM message_participants mp WHERE mp.thread_id=? AND mp.active=1
             AND mp.participant_role='teacher' AND mp.participant_key=t.teacher_name))''',
            (row[2],row[0],row[3],row[0])).fetchall()
        allowed={str(x[0] or '').strip().casefold() for x in emails}
        if str(destination).strip().casefold() not in allowed:
            owner=cursor.execute("SELECT 1 FROM message_participants WHERE thread_id=? AND participant_role='owner' AND participant_key='owner' AND active=1",(row[0],)).fetchone()
            owner_email=cursor.execute("SELECT value FROM settings WHERE key='owner_email'").fetchone() if owner else None
            if not owner_email or str(owner_email[0] or '').strip().casefold()!=str(destination).strip().casefold():
                raise ValueError('Recipient no longer has access to this message.')
        records=cursor.execute('''SELECT original_filename,stored_filename,mime_type,content_base64
            FROM message_attachments WHERE message_id=? ORDER BY id''',(message_id,)).fetchall()
    finally:
        conn.close()
    images=[];total=0
    for filename,stored,mime,encoded in records:
        if mime not in IMAGE_TYPES:
            continue
        remaining=MAX_IMAGE_BYTES-total
        if encoded is not None:
            if len(encoded)>((remaining+2)//3)*4:
                raise ValueError('Email images exceed the 10 MB limit; original files remain in the app.')
            content=base64.b64decode(encoded,validate=True)
        else:
            if not stored or Path(stored).name!=stored:
                raise ValueError('Invalid image storage name.')
            root=Path(api['HMUSIC_UPLOAD_DIR']).resolve()
            local=(root/stored).resolve()
            if root in local.parents and local.is_file():
                with local.open('rb') as file:
                    content=file.read(remaining+1)
            else:
                config=api['get_message_upload_s3_config']()
                if not config:
                    raise ValueError('A message image is unavailable; original app record is preserved.')
                response=api['message_upload_s3_client'](config).get_object(
                    Bucket=config['bucket'],Key=api['message_upload_s3_key'](config,stored))
                stream=response['Body']
                try:
                    content=stream.read(remaining+1)
                finally:
                    stream.close()
        total+=len(content)
        if not content or total>MAX_IMAGE_BYTES:
            raise ValueError('Email images are empty or exceed the 10 MB limit; original files remain in the app.')
        name=str(filename or 'lesson-image').replace('\r',' ').replace('\n',' ')
        images.append((name,mime,content))
    subject=' '.join(str(row[1] or '').splitlines()).strip()
    return subject,images
