"""Read-only owner operations home; payment and attendance mutations stay in their existing routes."""
from datetime import datetime, timedelta
from urllib.parse import quote
from flask import render_template

INACTIVE = {'inactive', 'cancelled', 'canceled', 'archived', 'deleted'}
CANCELLED = {'excused_24h', 'teacher_cancelled', 'cancelled', 'canceled'}

def low_credit_accounts(students, accounts, near_students):
    """Course balances take precedence; legacy balances apply only without course accounts."""
    student_map = {row[0]: row for row in students}
    all_account_names = {row[1] for row in accounts}
    result = []
    def eligible(name):
        row = student_map.get(name)
        return row and str(row[2] or 'active').lower().strip() not in INACTIVE and name in near_students
    for row in accounts:
        account_id, name, course, teacher, status, left = row
        if eligible(name) and str(status or 'active').lower().strip() == 'active' and float(left or 0) <= 1:
            result.append(dict(student=name, course=course or 'Course credits', teacher=teacher or 'Unassigned', left=float(left or 0), url='/enrollment/'+str(account_id)))
    for name, left, status in students:
        if eligible(name) and name not in all_account_names and float(left or 0) <= 1:
            result.append(dict(student=name, course='Student credits', teacher='', left=float(left or 0), url='/student/'+quote(name, safe='')))
    return sorted(result, key=lambda item:(item['left'],item['student'].casefold(),item['course']))

def load_owner_dashboard(connect, today, homework_rows, selected_date=None):
    selected = today
    if selected_date:
        try: selected = datetime.strptime(selected_date,'%Y-%m-%d').date()
        except (ValueError, TypeError): pass
    recent = (today-timedelta(days=30)).isoformat()
    upcoming = (today+timedelta(days=30)).isoformat()
    conn = connect('hmusic.db')
    try:
        cursor = conn.cursor()
        def rows(sql, params=()):
            cursor.execute(sql, params)
            return cursor.fetchall()
        def scalar(sql, params=()):
            return rows(sql, params)[0][0] or 0
        students = rows('SELECT name, COALESCE(lessons_left,0), status FROM students')
        accounts = rows('SELECT id,student_name,course_type_name,teacher_name,status,COALESCE(lessons_left,0) FROM enrollments')
        near_students = {r[0] for r in rows("SELECT DISTINCT student_name FROM schedule WHERE lesson_date >= ? AND lesson_date <= ? AND COALESCE(status,'scheduled') NOT IN ('teacher_cancelled','excused_24h','cancelled','canceled')", (recent,upcoming))}
        renewals = low_credit_accounts(students, accounts, near_students)
        schedule_rows = rows("""SELECT s.id,s.student_name,s.teacher,s.lesson_time,COALESCE(s.duration,30),s.classroom,
            COALESCE(s.status,'scheduled'),COALESCE(s.is_group,0),s.group_name,
            (SELECT COUNT(*) FROM group_schedule_students g WHERE g.schedule_id=s.id)
            FROM schedule s WHERE s.lesson_date = ? ORDER BY s.lesson_time,s.teacher,s.id""",(selected.isoformat(),))
        lessons = []
        for r in schedule_rows:
            status = r[6]
            label = {'present':'Present','scheduled':'Scheduled','no_show':'No show','last_min_cancel':'Last-minute cancel','excused_24h':'Cancelled by student','teacher_cancelled':'Teacher cancelled'}.get(status,status.replace('_',' ').title())
            lessons.append(dict(id=r[0],student=(r[8] or 'Group class') if r[7] else r[1],teacher=r[2] or 'Unassigned',time=r[3] or '—',duration=r[4],room=r[5] or 'Room not set',status=label,style='present' if status=='present' else ('scheduled' if status=='scheduled' else 'neutral'),group=r[7],participants=r[9],cancelled=status in CANCELLED,url='/calendar?month='+selected.strftime('%Y-%m')+'&student='+quote(r[1] or '',safe='')))
        month_prefix = today.strftime('%Y-%m')
        monthly_payments = scalar('SELECT COALESCE(SUM(amount),0) FROM payments WHERE payment_date LIKE ?', (month_prefix+'%',))
        payments = [dict(student=r[0],amount=float(r[1] or 0),method=r[2] or 'Payment',date=r[3] or '') for r in rows('SELECT student_name,amount,payment_method,payment_date FROM payments ORDER BY payment_date DESC,id DESC LIMIT 5')]
        invoice_summary = rows("SELECT COUNT(*),COALESCE(SUM(amount),0) FROM invoices WHERE LOWER(COALESCE(status,'open')) NOT IN ('paid','cancelled','canceled','void','voided','archived','draft')")[0]
        tasks = []
        def add(kind,title,detail,url,count=1): tasks.append(dict(kind=kind,title=title,detail=detail,url=url,count=count))
        reschedules = rows("SELECT id,student_name,original_date,requested_date,requested_time FROM reschedule_requests WHERE status='pending' AND (original_date >= ? OR requested_date >= ?) ORDER BY original_date,id", (today.isoformat(),today.isoformat()))
        for r in reschedules[:3]: add('Reschedule',r[1] or 'Student',str(r[3] or 'Date to confirm')+' · '+str(r[4] or ''),'/reschedule_request/'+str(r[0]))
        subs = rows("SELECT id,student_name,teacher_name,lesson_date,lesson_time FROM sub_requests WHERE status='pending' AND lesson_date >= ? ORDER BY lesson_date,id", (today.isoformat(),))
        for r in subs[:3]: add('Substitute',r[1] or 'Student',str(r[2] or '')+' · '+str(r[3] or '')+' '+str(r[4] or ''),'/owner_sub_requests')
        bookings = scalar("SELECT COUNT(*) FROM parent_booking_requests WHERE status IN ('pending','pending_owner_review')")
        if bookings: add('Booking','Lesson booking requests','Review requested dates and teachers','/owner_booking_requests',bookings)
        cancellations = scalar("SELECT COUNT(*) FROM lesson_change_requests WHERE request_type='cancel_lesson' AND status IN ('pending','pending_owner_review')")
        if cancellations: add('Cancellation','Cancellation requests','Review student requests','/owner_cancel_requests',cancellations)
        events = scalar("SELECT COUNT(*) FROM event_room_bookings WHERE status='pending'")
        if events: add('Room booking','Event room requests','Review room bookings','/owner_event_room_bookings',events)
        messages = scalar("SELECT COUNT(*) FROM messages WHERE recipient_role='owner' AND read_at IS NULL")
        if messages: add('Message','Unread messages','Open the owner inbox','/messages',messages)
        intake = scalar("SELECT COUNT(*) FROM inquiries WHERE status IN ('New Lead','Inquiry') OR COALESCE(owner_verified,0)=0")
        if intake: add('Intake','New student intake','Review trial scheduling and family setup','/new_students',intake)
        recent_homework = [r for r in homework_rows if str(r[3] or '') >= (today-timedelta(days=6)).isoformat() and str(r[3] or '') <= today.isoformat()]
        if recent_homework: add('Homework','Recent missing homework','Present lessons in the last 7 days','/missing_homework',len(recent_homework))
        pending_count = len(reschedules)+len(subs)+bookings+cancellations+events+intake
        return dict(today=today.isoformat(),day=selected.isoformat(),day_label=selected.strftime('%A, %b %d'),previous_day=(selected-timedelta(days=1)).isoformat(),next_day=(selected+timedelta(days=1)).isoformat(),month_label=today.strftime('%B %Y'),lessons=lessons,lesson_count=sum(not l['cancelled'] for l in lessons),present_count=sum(l['style']=='present' for l in lessons),tasks=tasks,pending_count=pending_count,monthly_payments=float(monthly_payments),open_invoice_count=invoice_summary[0],open_invoice_total=float(invoice_summary[1] or 0),renewals=renewals[:6],renewal_count=len(renewals),renewal_students=len({r['student'] for r in renewals}),payments=payments,homework_recent=len(recent_homework),homework_history=len(homework_rows)-len(recent_homework),messages=messages)
    finally: conn.close()

def render_owner_dashboard(connect,today,homework_rows,display_name,selected_date=None):
    data=load_owner_dashboard(connect,today,homework_rows,selected_date)
    return render_template('owner_home.html',**data,display_name=display_name or 'Owner')
