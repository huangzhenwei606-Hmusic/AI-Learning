from pathlib import Path


APP = Path(__file__).with_name("app.py")


CHECKS = {
    "invoice reminder route": '"/send_invoice_payment_reminder/<int:invoice_id>"',
    "invoice reminder action": "Email reminder",
    "invoice edit route": '"/edit_invoice/<int:invoice_id>"',
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
    "quick edit course credit route": '"/quick_edit_course_credit/<int:enrollment_id>"',
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
    "student credit save action": "save-credit",
    "invoice enrollment binding": "name=\"enrollment_id\"",
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
    "teacher inline package defaults ongoing": '<option value="unlimited">Ongoing no package</option>',
}


FORBIDDEN = {
    "student-level credit write": "UPDATE students\n        SET lessons_left",
    "course credit selector empty state": "No course selected",
    "old edit credit action": "Edit credit",
    "old add first course credit action": "Add first course credit",
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
    print(f"Regression check passed: {len(CHECKS)} billing/family/message entrypoints present.")


if __name__ == "__main__":
    main()
