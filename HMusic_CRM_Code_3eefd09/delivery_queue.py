"""Transactional outbox deduplication, shared by linked and direct delivery."""
import hashlib
from datetime import datetime


def queue_once(conn, user_role, user_key, channel, destination, title, body,
               link_url, related_type, related_id, *, postgres=False, direct=False):
    # Commit destination/suppression housekeeping before starting the short lock.
    conn.commit()
    cursor = conn.cursor()
    if postgres:
        identity = repr((channel, destination, related_type)).encode()
        key = int.from_bytes(hashlib.sha256(identity).digest()[:8], 'big', signed=True)
        cursor.execute('SELECT pg_advisory_xact_lock(?)', (key,))
    else:
        cursor.execute('BEGIN IMMEDIATE')
    try:
        if related_type in ('lesson_reminder', 'teacher_lesson_reminder'):
            # Imported duplicate guardian profiles/schedule IDs must not cause a
            # second identical reminder to the same physical address/phone.
            where = """channel=? AND destination=? AND title=?
                AND COALESCE(body,'')=COALESCE(?,'')
                AND COALESCE(link_url,'')=COALESCE(?,'') AND related_type=?
                AND status IN ('pending','sending','sent','failed','unconfirmed')"""
            args = (channel, destination, title, body, link_url, related_type)
        elif direct:
            where = """channel=? AND destination=? AND title=?
                AND related_type=? AND related_id=?
                AND status IN ('pending','sending','sent','unconfirmed')"""
            args = (channel, destination, title, related_type, related_id)
        else:
            where = """user_role=? AND user_key=? AND channel=? AND destination=? AND title=?
                AND COALESCE(related_type,'')=COALESCE(?,'')
                AND COALESCE(related_id,-1)=COALESCE(?,-1)
                AND COALESCE(link_url,'')=COALESCE(?,'')
                AND COALESCE(body,'')=COALESCE(?,'')
                AND status IN ('pending','sending','sent','unconfirmed')"""
            args = (user_role, user_key, channel, destination, title,
                    related_type, related_id, link_url, body)
        cursor.execute('SELECT id FROM notification_delivery_queue WHERE '+where+' ORDER BY id LIMIT 1', args)
        existing = cursor.fetchone()
        if existing:
            conn.commit()
            return existing[0]
        cursor.execute('''INSERT INTO notification_delivery_queue
            (user_role,user_key,channel,destination,title,body,link_url,related_type,related_id,status,created_at)
            VALUES (?,?,?,?,?,?,?,?,?,'pending',?)''',
            (user_role,user_key,channel,destination,title,body,link_url,related_type,related_id,
             datetime.now().strftime('%Y-%m-%d %H:%M')))
        ident = cursor.lastrowid
        conn.commit()
        return ident
    except Exception:
        conn.rollback()
        raise
