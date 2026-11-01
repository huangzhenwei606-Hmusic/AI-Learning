"""Owner-created standalone charges; credit is granted by existing settlement only."""
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import secrets
from flask import abort, redirect, render_template_string, request, session


def register_custom_invoices(app, api):
    @app.route('/owner/family/<int:parent_id>/custom-invoice', methods=['GET', 'POST'])
    def custom_family_invoice(parent_id):
        if not api['require_owner']():
            return redirect('/owner_login')
        api['ensure_v321_schema']()
        api['ensure_guardian_billing_schema']()
        conn = api['sqlite3'].connect('hmusic.db')
        try:
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS custom_invoice_requests (request_key TEXT PRIMARY KEY, invoice_id INTEGER)")
            conn.commit()
            cur.execute('SELECT parent_name FROM parent_profiles WHERE id=?', (parent_id,))
            parent = cur.fetchone()
            if not parent:
                abort(404)
            cur.execute('''SELECT DISTINCT s.name FROM students s JOIN parent_students ps
                ON ps.student_name=s.name WHERE ps.parent_id=? AND ps.active=1 ORDER BY s.name''', (parent_id,))
            students = [r[0] for r in cur.fetchall()]
            cur.execute('''SELECT e.id,e.student_name,e.course_type_name,e.teacher_name,e.duration
                FROM enrollments e JOIN parent_students ps ON ps.student_name=e.student_name
                WHERE ps.parent_id=? AND ps.active=1
                AND COALESCE(LOWER(TRIM(e.status)),'active') NOT IN
                ('inactive','cancelled','canceled','archived','deleted')
                ORDER BY e.student_name,e.course_type_name,e.id''', (parent_id,))
            courses = cur.fetchall()
            error = ''
            values = request.form if request.method == 'POST' else {}
            if request.method == 'POST':
                try:
                    if values.get('request_key') != session.get('custom_invoice_key_' + str(parent_id)):
                        raise ValueError('This form was already used or expired. Reload before creating another invoice.')
                    student = values.get('student_name', '')
                    if student not in students:
                        raise ValueError('Choose a student linked to this family.')
                    kind = values.get('kind', '')
                    if kind not in ('custom', 'makeup'):
                        raise ValueError('Choose an invoice type.')
                    title = values.get('title', '').strip()
                    description = values.get('description', '').strip()
                    if not title or len(title) > 200 or not description or len(description) > 4000:
                        raise ValueError('Enter a title (up to 200 characters) and a description (up to 4,000 characters).')
                    amount = Decimal(values.get('amount', ''))
                    credits = Decimal(values.get('credits', '0'))
                    if not amount.is_finite() or amount <= 0 or amount > Decimal('999999.99') or amount != amount.quantize(Decimal('.01')):
                        raise ValueError('Enter a positive amount with at most two decimal places.')
                    if not credits.is_finite() or credits < 0 or credits > 10000 or credits % Decimal('.5'):
                        raise ValueError('Credits must be 0 or a positive multiple of 0.5 (up to 10,000).')
                    selected = values.get('enrollment_id', '')
                    course = next((r for r in courses if str(r[0]) == selected and r[1] == student), None)
                    if (selected and not course) or (credits > 0 and not course):
                        raise ValueError('Choose an active course for this student when adding credits.')
                    due = values.get('due_date', '')
                    date.fromisoformat(due)
                    lesson_date = values.get('lesson_date', '')
                    lesson_time = values.get('lesson_time', '')
                    duration = values.get('duration', '')
                    if lesson_date:
                        date.fromisoformat(lesson_date)
                    if lesson_time:
                        datetime.strptime(lesson_time, '%H:%M')
                    if duration and (not duration.isdigit() or not 1 <= int(duration) <= 1440):
                        raise ValueError('Duration must be between 1 and 1,440 minutes.')
                    action = values.get('action', '')
                    if action not in ('draft', 'preview'):
                        raise ValueError('Choose Save draft or Preview & send.')
                except (ValueError, InvalidOperation) as exc:
                    error = str(exc) if isinstance(exc, ValueError) else 'Enter valid amount and credit numbers.'
                else:
                    # Reserve the request in the same transaction as the invoice so
                    # concurrent double-clicks cannot create duplicate charges.
                    cur.execute("INSERT INTO custom_invoice_requests(request_key) VALUES (?) ON CONFLICT(request_key) DO NOTHING", (values['request_key'],))
                    if cur.rowcount != 1:
                        cur.execute("SELECT invoice_id FROM custom_invoice_requests WHERE request_key=?", (values['request_key'],))
                        existing = cur.fetchone()
                        return redirect('/edit_invoice/' + str(existing[0])) if existing and existing[0] else ('Invoice creation is already in progress.', 409)
                    status = 'pending_owner_approval' if action == 'draft' else 'unpaid'
                    course_label = ' · '.join(str(x) for x in (course[2], course[3]) if x) if course else ''
                    coverage_start = ' · '.join(x for x in (lesson_date, lesson_time, (duration + ' min') if duration else '') if x)
                    note = description + (('\nLesson: ' + coverage_start) if coverage_start else '')
                    now = datetime.now().strftime('%Y-%m-%d %H:%M')
                    cur.execute('''INSERT INTO invoices
                        (student_name,schedule_id,charge_lessons,amount,status,invoice_type,created_at,
                         due_date,notes,subtotal_amount,discount_amount,payment_methods,package_options,
                         enrollment_id,credits_applied,coverage_title,coverage_class,coverage_start,coverage_note)
                        VALUES (?,NULL,?,?,?,?,?,?,?,?,0,'ach,zelle','',?,?,?,?,?,?)''',
                        (student, float(credits), float(amount), status,
                         'makeup_invoice' if kind == 'makeup' else 'custom_invoice', now, due, note,
                         float(amount), course[0] if course else None, 0, title, course_label, coverage_start, note))
                    invoice_id = cur.lastrowid
                    api['sync_invoice_allocations'](cur, invoice_id, student, float(amount), status)
                    cur.execute('UPDATE custom_invoice_requests SET invoice_id=? WHERE request_key=?', (invoice_id, values['request_key']))
                    conn.commit()
                    session.pop('custom_invoice_key_' + str(parent_id), None)
                    # No notifications or credits are created by this form.
                    return redirect('/review_invoice_notice/' + str(invoice_id) if action == 'draft'
                                    else '/owner/invoice/' + str(invoice_id) + '/quick-pay')
            if request.method == 'GET' or not session.get('custom_invoice_key_' + str(parent_id)):
                session['custom_invoice_key_' + str(parent_id)] = secrets.token_urlsafe(24)
            return render_template_string(TEMPLATE, parent=parent[0], parent_id=parent_id,
                students=students, courses=courses, v=values, error=error,
                due=(date.today() + timedelta(days=7)).isoformat(),
                request_key=session['custom_invoice_key_' + str(parent_id)], csrf=api['hmusic_csrf_token']()), (400 if error else 200)
        finally:
            conn.close()


TEMPLATE = '''<!doctype html><html><head><title>Create invoice</title><meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{font:15px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f5f7fb;color:#182235;margin:0;padding:24px}main{max-width:800px;margin:auto;background:white;border:1px solid #e2e8f0;border-radius:16px;padding:28px}h1{font-size:26px;margin-top:0}label{display:block;font-weight:600;margin:18px 0 7px}input,select,textarea{box-sizing:border-box;width:100%;padding:11px;border:1px solid #cbd5e1;border-radius:8px;font:inherit}textarea{min-height:100px}.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}small,p{color:#64748b;line-height:1.5}.notice{background:#edf5ff;padding:14px;border-radius:8px}.error{color:#991b1b;background:#fef2f2;padding:12px}button,a.button{display:inline-block;padding:12px 18px;border:0;border-radius:8px;background:#2169af;color:white;font-weight:600;text-decoration:none;margin:20px 8px 0 0;cursor:pointer}button.secondary{background:#e8eef5;color:#24354b}@media(max-width:600px){.grid{grid-template-columns:1fr}body{padding:12px}main{padding:18px}}</style></head><body><main>
<h1>Create invoice</h1><p>{{parent}} · Standalone extra lesson or custom charge</p>
{% if error %}<p class="error" role="alert">{{error}}</p>{% endif %}
<form method="post"><input type="hidden" name="_csrf_token" value="{{csrf}}"><input type="hidden" name="request_key" value="{{request_key}}">
<div class="grid"><div><label for="student">Student</label><select id="student" name="student_name" required>{% for student in students %}<option {% if v.get('student_name')==student %}selected{% endif %}>{{student}}</option>{% endfor %}</select></div>
<div><label for="kind">Invoice type</label><select id="kind" name="kind"><option value="custom">Custom invoice</option><option value="makeup" {% if v.get('kind')=='makeup' %}selected{% endif %}>Extra / Make-up lesson</option></select></div></div>
<label for="title">Invoice title</label><input id="title" name="title" maxlength="200" value="{{v.get('title','')}}" placeholder="Additional piano lesson" required>
<label for="description">What this payment covers (parent visible)</label><textarea id="description" name="description" maxlength="4000" placeholder="Describe the lesson or fee, including the teacher and any relevant details." required>{{v.get('description','')}}</textarea>
<div class="grid"><div><label for="amount">Amount ($)</label><input id="amount" name="amount" type="number" min="0.01" max="999999.99" step="0.01" value="{{v.get('amount','')}}" required></div>
<div><label for="due">Due date</label><input id="due" name="due_date" type="date" value="{{v.get('due_date',due)}}" required></div></div>
<div class="grid"><div><label for="lesson-date">Lesson date (optional)</label><input id="lesson-date" name="lesson_date" type="date" value="{{v.get('lesson_date','')}}"></div><div><label for="lesson-time">Lesson time (optional)</label><input id="lesson-time" name="lesson_time" type="time" value="{{v.get('lesson_time','')}}"></div></div>
<label for="duration">Duration in minutes (optional)</label><input id="duration" name="duration" type="number" min="1" max="1440" step="1" value="{{v.get('duration','')}}">
<label for="credits">Credits to add after full payment</label><input id="credits" name="credits" type="number" min="0" max="10000" step="0.5" value="{{v.get('credits','0')}}" required><small>0 = no credits. Enter 0.5, 1, 2, 10, or another multiple of 0.5.</small>
<label for="course">Course receiving the credits</label><select id="course" name="enrollment_id"><option value="">No course / fee only</option>{% for c in courses %}<option value="{{c[0]}}" data-student="{{c[1]}}" {% if v.get('enrollment_id')==c[0]|string %}selected{% endif %}>{{c[1]}} · {{c[2]}} · {{c[3]}} · {{c[4] or ''}} min</option>{% endfor %}</select>
<p id="credit-summary" class="notice" aria-live="polite">No credits will be added.</p>
<p>A make-up lesson using existing credits should normally have 0 credits added. Saving or sending this invoice does not change credits. Credits are added once, only after full payment is confirmed.</p>
<button class="secondary" type="submit" name="action" value="draft">Save draft</button><button type="submit" name="action" value="preview">Preview &amp; send</button><a class="button" href="/parent_admin/{{parent_id}}#family-billing">Back</a>
</form></main><script>
const student=document.getElementById('student'),course=document.getElementById('course'),credits=document.getElementById('credits');
function update(){for(const option of course.options){if(option.dataset.student){option.hidden=option.dataset.student!==student.value;option.disabled=option.hidden;if(option.hidden&&option.selected)course.value='';}}course.required=Number(credits.value)>0;document.getElementById('credit-summary').textContent=Number(credits.value)>0?'After full payment: add '+credits.value+' credits to the selected course.':'No credits will be added.';}
student.addEventListener('change',update);credits.addEventListener('input',update);update();
</script></body></html>'''
