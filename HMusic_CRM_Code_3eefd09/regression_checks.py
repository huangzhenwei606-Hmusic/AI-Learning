from pathlib import Path


APP = Path(__file__).with_name("app.py")


CHECKS = {
    "child os bearer csrf exemption": 'request.path.startswith("/api/child-os/v1/")',
    "invoice reminder route": '"/send_invoice_payment_reminder/<int:invoice_id>"',
    "invoice reminder GET recovery": 'return redirect("/invoices?reminder=not_sent")',
    "invoice reminder email fallback": "if not parent or not hmusic_is_real_email(parent[1]):",
    "invoice reminder notification isolation": "Invoice reminder in-app notification failed",
    "invoice reminder delivery isolation": "Invoice reminder email delivery failed",
    "invoice reminder error recovery": 'request.path.startswith("/send_invoice_payment_reminder/")',
    "portable email suppression key": "email TEXT PRIMARY KEY,",
    "smtp 465 ssl support": 'smtp_security = "ssl" if smtp_port == 465 else "starttls"',
    "smtp ssl client": "smtplib.SMTP_SSL if smtp_security == \"ssl\" else smtplib.SMTP",
    "smtp connection timeout": "smtp_port, timeout=30",
    "invoice reminder action": "Email reminder",
    "invoice edit route": '"/edit_invoice/<int:invoice_id>"',
    "invoice edit parent ranking uses local student join": "LEFT JOIN students s2 ON s2.name = ps2.student_name",
    "invoice coverage schema migration": 'add_column_if_missing("invoices", "coverage_title", "coverage_title TEXT")',
    "invoice coverage class migration": 'add_column_if_missing("invoices", "coverage_class", "coverage_class TEXT")',
    "invoice coverage start migration": 'add_column_if_missing("invoices", "coverage_start", "coverage_start TEXT")',
    "invoice coverage note migration": 'add_column_if_missing("invoices", "coverage_note", "coverage_note TEXT")',
    "payment edit route": '"/edit_payment/<int:payment_id>"',
    "ledger edit route": '"/edit_ledger_entry/<int:ledger_id>"',
    "ledger action column": "<th>Action</th>",
    "family workspace label": "Family Workspace",
    "family workspace clickable breadcrumb": 'aria-label="Breadcrumb"',
    "family workspace parents crumb link": '<a href="/parents">Parents</a>',
    "parent billing add entry": "Add billing",
    "messages mark all read": "/messages/mark_all_read",
    "course credit display": "Credits by course",
    "family enrollment credits": "Credits & Enrollments",
    "course credit actions": "Full course setup",
    "course credit tuition action": "Set tuition",
    "enrollment tuition anchor": 'id="tuition"',
    "set tuition return parameter": "return_to",
    "set tuition back action": '<a href="{return_to_attr}">Back</a>',
    "course credit setup gate": "Set up course credits first",
    "add enrollment student preselect": "selected_student_name = (request.args.get(\"student_name\") or \"\").strip()",
    "student course credit update route": '"/update_student_course_credit/<name>"',
    "quick add course credit route": '"/quick_add_course_credit/<name>"',
    "quick add credit closes pricing read": "student = cursor.fetchone()\n    conn.close()",
    "quick add credit uses isolated write": "Keep pricing/schema reads outside the write connection",
    "quick edit course credit route": '"/quick_edit_course_credit/<int:enrollment_id>"',
    "archive course credit route": '"/archive_course_credit/<int:enrollment_id>"',
    "archive course credit soft status": "SET status = 'archived'",
    "archive course credit action": "Archive this course credit? History will stay",
    "student main credit section": "course-credit-section",
    "student inline credit rows": "credit-inline-row",
    "student inline credit edit toggle": "data-credit-edit-target",
    "student credit stepper": "data-credit-step",
    "student credit row forms": "course_credit_forms_html",
    "student quick credit form": "quickCourseCreditForm",
    "quick credit teacher selector": 'name="teacher_name"',
    "family credit row forms": "family_credit_forms_html",
    "family quick credit form": "familyQuickCourseCreditForm",
    "family credit return target": "return_anchor",
    "parent admin teacher selector dedupe": "seen_quick_credit_teachers",
    "student credit save action": "save-credit",
    "invoice enrollment binding": "name=\"enrollment_id\"",
    "student add billing uses enrollment invoice": 'f"/create_enrollment_invoice/{course_credit_rows[0][0]}"',
    "legacy package invoice redirects to enrollment invoice": 'return redirect(f"/create_enrollment_invoice/{enrollment_id_int}")',
    "course credit label tolerates extra columns": "status, *_ = row",
    "payment enrollment preselect": "selected_enrollment_id = request.args.get(\"enrollment_id\")",
    "schedule enrollment binding": "resolved_enrollment_id",
    "teacher status ajax form": "data-teacher-status-form",
    "teacher status ajax endpoint": "wants_json = \"application/json\"",
    "teacher status repaint": "repaintTeacherScheduleEvent",
    "teacher status form binding": "bindTeacherStatusForms();",
    "teacher mobile calendar panel": "def teacher_mobile_calendar_panel",
    "teacher mobile calendar date selection": "function teacherSelectMobileDate(dateStr)",
    "teacher calendar hides piano equipment": 'r"\\b(?:grand|upright)\\s+piano\\b"',
    "teacher records postgres-safe student ordering": "GROUP BY student_name\n    ORDER BY first_lesson_time, student_name",
    "portable enrollment waiver floor": "WHEN COALESCE(policy_waiver_used, 0) + ? < 0 THEN 0",
    "portable student waiver floor": "WHEN COALESCE(free_cancel_used, 0) + ? < 0 THEN 0",
    "teacher inline add schedule modal": "teacherAddOverlay",
    "teacher calendar date opens add modal": "teacherOpenAddSchedule(dateStr)",
    "teacher inline add schedule form": "teacherInlineAddScheduleForm",
    "teacher add schedule respects return": "teacher_return = owner_calendar_return",
    "teacher inline package defaults ten lessons": '<select class="teacher-add-select" name="package_type" id="teacherInlinePackageType" onchange="syncTeacherInlinePackage()">\n                                    <option value="10">10 lessons</option>',
    "teacher inline course defaults private 30": "teacher_course_default_sort_key",
    "teacher inline room shows location": "data-location-name",
    "teacher inline room sync": "syncTeacherInlineRoom",
    "teacher inline room ids submit": 'name="room_id" id="teacherAddRoomId"',
    "teacher inline student search all students": "teacher_calendar_students = hmusic_teacher_student_rows(cursor, teacher_name, include_all=True)",
    "teacher can schedule existing student": "teacher_selected_existing_student",
    "teacher calendar compact month grid": "calendar-grid.month-view .calendar-day",
    "teacher calendar schedule grid class": "schedule_grid_class",
    "teacher calendar inline status select": 'class="teacher-card-status {dot}"',
    "teacher calendar status autosave": "statusSelectForAutoSave.addEventListener('change'",
    "parent cancel submits directly": '<form class="schedule-cancel-form" method="POST" action="/parent_cancel">',
    "parent cancel pending status": "parent_cancel_pending_confirm",
    "parent cancel pending label": "Cancel pending confirm",
    "parent cancel returns to schedule": 'return redirect("/parent_schedule?cancel=pending")',
    "parent can undo pending cancellation": 'name="action" value="undo"',
    "parent undo marks request withdrawn": "owner_decision = 'withdrawn_by_parent'",
    "parent undo restores lesson": "return redirect(\"/parent_schedule?cancel=withdrawn\")",
    "parent undo has reviewed-state guard": "return redirect(\"/parent_schedule?cancel=already_reviewed\")",
    "parent undo notifies owner": '"Cancellation request withdrawn"',
    "parent cancel rejection restores schedule": 'if action == "reject" and req[4] == "cancel_lesson"',
    "parent cancel rejection resets unconditionally": "SET status = 'scheduled'\n            WHERE id = ?",
    "parent schedule uses location only": "NULLIF(TRIM(s.location), ''), NULLIF(TRIM(l.address), '')",
    "parent schedule next lesson location": "next_lesson[9]",
    "parent schedule upcoming location": "lesson[9]",
    "parent schedule readable date label": "parent_schedule_date_label",
    "parent schedule compact pending panel": 'class="pending-action-panel"',
    "parent schedule mobile actions stack": "@media (max-width:620px)",
    "parent schedule avoids duplicate next lesson": "remaining_upcoming = upcoming[1:] if next_lesson else upcoming",
    "parent dashboard no duplicate next status pill": '<div class="next-strip"><span>Next Lesson</span></div>',
    "parent dashboard next status matches calendar data": "next_lesson_status = escape(hmusic_policy_status_label(next_lesson[6] or \"scheduled\"))",
    "parent dashboard next status has dedicated row": 'class="next-status-row"',
    "parent dashboard calendar dates clickable": "showParentCalendarDay",
    "parent dashboard calendar lesson detail": 'id="calendarDayDetail"',
    "parent dashboard validates pending request state": "SELECT 1 FROM lesson_change_requests lcr",
    "reschedule approval uses full location room selector": 'name="approved_room_id"',
    "reschedule approval shows full address": 'room_label = f"{location_name} · {address} · {room[1]}"',
    "reschedule approval saves location identifiers": "location_id = ?,\n        room_id = ?,\n        location = ?,",
    "owner calendar left-aligned time chip": '<span class="ev-time"><span class="calendar-time-chip">{time_range}</span></span>',
    "owner calendar inline status select": 'class="calendar-status-select {dot_class}"',
    "owner pending cancel option only for pending lesson": "current === 'parent_cancel_pending_confirm'",
    "owner calendar multi-select toggle": 'id="ownerMultiToggle"',
    "owner calendar multi-select checkboxes": 'class="owner-select-input"',
    "owner calendar bulk status endpoint": '"/owner_multi_select_action"',
    "owner bulk protects pending cancellations": "Pending parent cancellations must be reviewed separately.",
    "teacher mobile bootstrap api": '"/api/teacher/bootstrap"',
    "teacher mobile bootstrap csrf token": '"csrf_token": hmusic_csrf_token()',
    "teacher mobile device token api": '"/api/teacher/device_token"',
    "teacher mobile calendar api": '"/api/teacher/calendar"',
    "teacher mobile lookups api": '"/api/teacher/lookups"',
    "teacher mobile lesson detail api": '"/api/teacher/lesson/<int:schedule_id>"',
    "teacher mobile lesson status api": '"/api/teacher/lesson/status"',
    "teacher mobile bulk status api": '"/api/teacher/lesson/bulk_status"',
    "teacher mobile lesson save api": '"/api/teacher/lesson/save"',
    "teacher mobile open slots api": '"/api/teacher/open_slots"',
    "teacher mobile time off api": '"/api/teacher/time_off"',
    "teacher mobile messages api": '"/api/teacher/messages"',
    "teacher mobile add schedule api": '"/api/teacher/add_schedule"',
    "teacher mobile message recipients": "message_recipients",
    "teacher mobile device token table": "teacher_device_tokens",
    "teacher financial permissions forced off": 'perms["view_payroll"] = 0\n    perms["view_billing"] = 0',
    "teacher dashboard uses nonfinancial summary": "Lesson Summary · {month_start.strftime(\"%B\")}",
    "teacher group roster financial redaction": "def teacher_safe_group_roster(group_roster):",
    "teacher status financial redaction": "return teacher_safe_lesson_status_result(result)",
    "teacher group roster permission": '"manage_group_roster": 1',
    "teacher group roster sync": "def sync_calendar_group_roster(cursor, schedule_ids, roster_items, attendance_schedule_id=None):",
    "teacher group roster editor": "function teacherAddGroupStudent()",
    "teacher group roster removal": "function teacherRemoveGroupStudent(studentName)",
    "teacher group roster payload": "payload.group_roster = collectTeacherGroupRoster()",
    "teacher event room booking route": '"/event_room_booking"',
    "teacher event room booking navigation": '"Event Room Booking"',
    "owner event room booking route": '"/owner_event_room_bookings"',
    "event room booking schema": "CREATE TABLE IF NOT EXISTS event_room_bookings",
    "event room weekend validation": "Event Room bookings are available on Saturday or Sunday only.",
    "event room overlap protection": "def event_room_booking_conflict",
    "event room teacher calendar sync": "def calendar_event_room(booking)",
    "event room owner calendar sync": 'class="ev owner-studio-event"',
    "event room public teacher details": 'class="erb-booking-detail"',
    "event room startup schema": "ensure_event_room_booking_schema()\n    ensure_guardian_billing_schema()",
    "jason september event room seed": '"jason-piano-salon-2026-09-26"',
    "jason october event room seed": '"jason-piano-salon-2026-10-10"',
    "startup database preparation": "def initialize_runtime_database():",
    "database busy recovery": 'response.headers["Retry-After"] = "2"',
    "request tracing": 'response.headers["X-Request-ID"]',
    "v321 schema cached": "_v321_schema_ready = True",
    "teacher schema cached": "_teacher_management_schema_ready = True",
    "all schema helpers cached": "def hmusic_schema_once(func):",
    "schema work runs during startup": "for schema_name in _runtime_schema_names:",
    "postgres backend feature flag": "from database_backend import connect as hmusic_database_connect, using_postgres",
    "guardian access owner route": '"/student_guardian_access/<path:student_name>"',
    "family workspace shared guardians": "guardians_by_student",
    "family workspace guardian account links": 'class="row-label">Shared guardians</div>',
    "family workspace child management layout": "family-student-row",
    "family workspace guardian initials": "guardian-avatar",
    "family workspace dense wide layout": "@media (min-width:1500px)",
    "family workspace current guardian marker": "This account",
    "guardian invite approval route": '"/guardian_invites"',
    "guardian invite student binding": '("guardian_invites", "student_name", "student_name TEXT")',
    "postgres guardian schema migration": "def ensure_postgres_guardian_billing_schema():",
    "postgres guardian permission migration": "ALTER TABLE parent_students ADD COLUMN IF NOT EXISTS",
    "guardian schema runs during startup": "ensure_guardian_billing_schema()\n    conn = sqlite3.connect(\"hmusic.db\", timeout=15)",
    "guardian permission schema": '"can_manage_schedule", "can_manage_schedule INTEGER DEFAULT 1"',
    "guardian billing visibility permission": 'parent_has_student_permission(parent_id, invoice[1], "view_billing")',
    "student billing rules table": "CREATE TABLE IF NOT EXISTS student_billing_rules",
    "invoice allocation table": "CREATE TABLE IF NOT EXISTS invoice_allocations",
    "invoice allocation sync": "def sync_invoice_allocations",
    "invoice share payment recorder": "def record_invoice_allocation_paid",
    "invoice paid only after every share": 'if all(status == "paid" for status in statuses):',
    "stripe allocation metadata": '"allocation_id": str(allocation_id)',
    "stripe ACH only": 'payment_method_types=["us_bank_account"]',
    "owner confirms individual zelle share": 'name="action" value="confirm_allocation"',
    "schedule request permission": 'parent_has_student_permission(parent_id, student_name, "manage_schedule")',
    "billing methods ACH and zelle only": 'allowed_methods &= {"ach", "zelle"}',
}


FORBIDDEN = {
    "student-level credit write": "UPDATE students\n        SET lessons_left",
    "course credit selector empty state": "No course selected",
    "old edit credit action": "Edit credit",
    "old add first course credit action": "Add first course credit",
    "sqlite-only email collation": "COLLATE NOCASE",
    "trial paypal option": 'name="payment_method" value="PayPal"',
    "invoice card checkout option": 'method=card',
    "teacher payroll summary": "Payroll Summary ·",
    "teacher payroll KPI": "Payroll This Month",
    "teacher settled payroll": "Settled Payroll",
    "teacher projected payroll": "Projected Total",
    "teacher lesson rate row": "<span>Lesson Rate</span>",
    "sqlite-only enrollment waiver max": "policy_waiver_used = MAX(COALESCE(policy_waiver_used, 0) + ?, 0)",
    "sqlite-only student waiver max": "free_cancel_used = MAX(COALESCE(free_cancel_used, 0) + ?, 0)",
    "teacher group credit fallback": "('Credit: ' + (item.credit_units || 1))",
}

STUDENT_DETAIL_FORBIDDEN = {
    "student profile course credit management": "<h2>Credits by Course</h2>",
    "student profile parent app access management": "<h2>Parent App Access</h2>",
    "student profile billing tab": 'data-student-tab="billing"',
}


def main():
    source = APP.read_text(encoding="utf-8")
    missing = [name for name, needle in CHECKS.items() if needle not in source]
    if missing:
        print("Regression check failed. Missing:")
        for name in missing:
            print(f"- {name}: {CHECKS[name]}")
        raise SystemExit(1)
    present = [name for name, needle in FORBIDDEN.items() if needle in source]
    if present:
        print("Regression check failed. Forbidden legacy patterns found:")
        for name in present:
            print(f"- {name}: {FORBIDDEN[name]}")
        raise SystemExit(1)
    try:
        student_detail_source = source.split('def student_detail(name):', 1)[1].split('@app.route("/link_student_teacher/<name>"', 1)[0]
    except IndexError:
        print("Regression check failed. Could not locate student detail route.")
        raise SystemExit(1)
    student_detail_present = [
        name for name, needle in STUDENT_DETAIL_FORBIDDEN.items()
        if needle in student_detail_source
    ]
    if student_detail_present:
        print("Regression check failed. Student Profile has duplicated family management:")
        for name in student_detail_present:
            print(f"- {name}: {STUDENT_DETAIL_FORBIDDEN[name]}")
        raise SystemExit(1)
    try:
        parent_schedule_source = source.split("def parent_schedule():", 1)[1].split('@app.route("/parent_booking_request"', 1)[0]
    except IndexError:
        print("Regression check failed. Could not locate parent schedule route.")
        raise SystemExit(1)
    if 'href="/parent_cancel?schedule_id=' in parent_schedule_source:
        print("Regression check failed. Parent cancellation still opens the intermediate choices page.")
        raise SystemExit(1)
    if '<div class="schedule-room">Room:' in parent_schedule_source or "lesson[5] or 'Room TBD'" in parent_schedule_source:
        print("Regression check failed. Parent schedule still exposes classroom or room details.")
        raise SystemExit(1)
    runtime_schema_source = source.split("_runtime_schema_names = (", 1)[1].split(")\n\nfor _schema_name", 1)[0]
    if '"ensure_guardian_billing_schema"' in runtime_schema_source:
        print("Regression check failed. PostgreSQL guardian migration is still wrapped as SQLite-only schema work.")
        raise SystemExit(1)
    print(f"Regression check passed: {len(CHECKS)} billing/family/message entrypoints present.")


if __name__ == "__main__":
    main()
