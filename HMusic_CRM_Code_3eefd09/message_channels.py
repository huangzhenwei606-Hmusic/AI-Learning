"""Explicit delivery choices for staff messages; preserve legacy notification defaults."""
from html import escape
from flask import abort

CHANNELS = ('email', 'sms')


def selected_channels(form):
    if form.get('delivery_selection') != '1':
        return None
    channels = form.getlist('delivery_channels')
    if any(channel not in CHANNELS for channel in channels):
        abort(400, 'Choose Email and/or Mobile SMS.')
    return [channel for channel in CHANNELS if channel in channels]


def controls(api):
    email_ready = api['smtp_config_status']()[0]
    sms_ready = api['sms_config_status']()[0]
    return f'''<fieldset style="border:1px solid #dce1eb;border-radius:10px;padding:16px;margin:18px 0">
    <legend>Send notification by</legend><input type="hidden" name="delivery_selection" value="1">
    <label style="display:inline-block;margin-right:22px"><input type="checkbox" style="width:auto;min-height:0;margin:0 6px 0 0;padding:0" name="delivery_channels" value="email" {'checked' if email_ready else 'disabled'}> Email</label>
    <label style="display:inline-block"><input type="checkbox" style="width:auto;min-height:0;margin:0 6px 0 0;padding:0" name="delivery_channels" value="sms" {'' if sms_ready else 'disabled'}> Mobile SMS</label>
    <p style="font-size:13px;color:#64748b;margin-bottom:0">Choose either or both. The message is always saved in the app. SMS includes a short preview and a link to the full message and attachments.</p>
    {'' if email_ready else '<p>Email service is not configured.</p>'}
    {'' if sms_ready else '<p>Mobile SMS service is not configured.</p>'}
    </fieldset>'''


def validate(api, role, key, channels):
    if channels is None:
        return
    conn = api['sqlite3'].connect('hmusic.db')
    try:
        if role == 'parent':
            row = conn.execute('SELECT email,phone FROM parent_profiles WHERE id=? AND COALESCE(active,1)=1',(key,)).fetchone()
        elif role == 'teacher':
            row = conn.execute('SELECT email,phone FROM teachers WHERE teacher_name=? AND COALESCE(active,1)=1',(key,)).fetchone()
        else:
            abort(400, 'Delivery is supported for parent and teacher recipients.')
        if not row:
            abort(400, 'Recipient is inactive or missing.')
        if 'email' in channels:
            if not api['smtp_config_status']()[0]:
                abort(400, 'Email service is not configured. Your message was not sent.')
            if not api['hmusic_is_real_email'](row[0]):
                abort(400, 'Recipient needs a valid email address. Go back to keep your draft.')
            if api['hmusic_is_email_suppressed'](conn.cursor(),row[0]):
                abort(400, 'Email delivery to this address is suspended. Correct the address or choose Mobile SMS.')
        if 'sms' in channels:
            if not api['sms_config_status']()[0]:
                abort(400, 'Mobile SMS service is not configured. Your message was not sent.')
            if not api['hmusic_normalize_sms_phone'](row[1]):
                abort(400, 'Recipient needs a valid mobile number. Go back to keep your draft.')
    finally:
        conn.close()


def deliver(api, role, key, title, body, link, related_type, related_id, channels):
    # Only selected channels enter the queue. Existing atomic queue claims prevent resends.
    for channel in channels:
        preview = str(body or '')[:700] + ('…' if len(str(body or '')) > 700 else '') if channel == 'sms' else body
        queue_id = api['queue_notification_delivery'](role,str(key),title,preview,link,channel,
            related_type=related_type,related_id=related_id)
        if queue_id:
            sender = api['send_queued_email_now'] if channel == 'email' else api['send_queued_sms_now']
            sender(queue_id)


def summary(api, thread_id):
    api['ensure_v33_schema']()
    conn = api['sqlite3'].connect('hmusic.db')
    try:
        message = conn.execute("SELECT id FROM messages WHERE thread_id=? AND sender_role='owner' ORDER BY id DESC LIMIT 1",(thread_id,)).fetchone()
        if not message:
            return ''
        rows = conn.execute('''SELECT channel,status FROM notification_delivery_queue
            WHERE related_type='message' AND related_id=? AND channel IN ('email','sms')
            AND user_role IN ('parent','teacher') ORDER BY id''',(message[0],)).fetchall()
    finally:
        conn.close()
    labels = {'sent':'Accepted by provider', 'pending':'Queued; not sent yet',
        'sending':'Submitting', 'failed':'Failed', 'unconfirmed':'Outcome unknown; review before retrying'}
    statuses = ''.join(f'<li>{"Email" if channel=="email" else "Mobile SMS"}: {escape(labels.get(status,status or "Unknown"))}</li>' for channel,status in rows)
    statuses = statuses or '<li>No Email/SMS delivery record.</li>'
    return f'''<section style="padding:14px;border:1px solid #dce1eb;border-radius:10px;margin:16px 0" role="status">
    <strong>Latest outgoing message</strong><p>Saved in the app.</p><ul>{statuses}</ul>
    <p style="font-size:13px;color:#64748b">Provider acceptance does not confirm that the recipient has received or read the message.</p></section>'''
