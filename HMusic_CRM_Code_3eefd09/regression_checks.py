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
    "course credit actions": "Edit credit",
    "course credit setup gate": "Set up course credits first",
    "add enrollment student preselect": "selected_student_name = (request.args.get(\"student_name\") or \"\").strip()",
    "student course credit update route": '"/update_student_course_credit/<name>"',
    "student inline credit rows": "credit-inline-row",
    "student credit stepper": "data-credit-step",
    "student credit row forms": "course_credit_forms_html",
    "student credit save action": "save-credit",
    "invoice enrollment binding": "name=\"enrollment_id\"",
    "payment enrollment preselect": "selected_enrollment_id = request.args.get(\"enrollment_id\")",
    "schedule enrollment binding": "resolved_enrollment_id",
}


FORBIDDEN = {
    "student-level credit write": "UPDATE students\n        SET lessons_left",
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
    print(f"Regression check passed: {len(CHECKS)} billing/family/message entrypoints present.")


if __name__ == "__main__":
    main()
