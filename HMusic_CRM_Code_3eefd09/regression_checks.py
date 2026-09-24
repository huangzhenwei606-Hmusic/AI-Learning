from pathlib import Path


APP = Path(__file__).with_name("app.py")


CHECKS = {
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
    "parent dashboard calendar dates clickable": "showParentCalendarDay",
    "parent dashboard calendar lesson detail": 'id="calendarDayDetail"',
    "parent dashboard validates pending request state": "SELECT 1 FROM lesson_change_requests lcr",
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
    "startup database preparation": "def initialize_runtime_database():",
    "database busy recovery": 'response.headers["Retry-After"] = "2"',
    "request tracing": 'response.headers["X-Request-ID"]',
    "v321 schema cached": "_v321_schema_ready = True",
    "teacher schema cached": "_teacher_management_schema_ready = True",
    "all schema helpers cached": "def hmusic_schema_once(func):",
    "schema work runs during startup": "for schema_name in _runtime_schema_names:",
    "postgres backend feature flag": "from database_backend import connect as hmusic_database_connect, using_postgres",
}


FORBIDDEN = {
    "student-level credit write": "UPDATE students\n        SET lessons_left",
    "course credit selector empty state": "No course selected",
    "old edit credit action": "Edit credit",
    "old add first course credit action": "Add first course credit",
    "sqlite-only email collation": "COLLATE NOCASE",
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
    print(f"Regression check passed: {len(CHECKS)} billing/family/message entrypoints present.")


if __name__ == "__main__":
    main()
