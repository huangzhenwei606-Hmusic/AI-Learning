# H-Music CRM Project State

Last updated: 2026-06-12
Main app: `app.py`
Local DB: `hmusic.db`
Local URL: `http://127.0.0.1:5001`

## Current Version

V30.2 Core Complete / Ready for Trial Operation

Deployment prep started: V31.0 Render Deploy Prep

## Product Scope

H-Music CRM is a music school management system for owner, teachers, and parents.

The current core workflow supports:

- Owner creates students, teachers, parents, and lesson schedules.
- Owner links parent profiles to students.
- Parent logs into Parent Pro.
- Parent views upcoming lessons, ledger, invoices, payments, and messages.
- Parent can cancel lessons and request reschedule.
- Teacher logs in, views dashboard/calendar, messages, reschedule, sub requests, and open slots.
- Owner reviews reschedule requests, approves/rejects, and sees pending work in Command Center.
- Message Center supports owner, parent, and teacher conversations with attachments.
- Open Slot system supports manual slots, auto-gap slots, active/inactive/used status.
- Reschedule approval updates schedule, locks used manual open slot, and writes message/activity history.

## Major Completed Versions

### V26.5 Stabilization

- Unified lesson status application.
- Parent cancel uses stable status logic.
- Payroll lock/status protection improved.

### V27 Parent Pro

- Parent profile tables.
- Parent-student linking.
- Parent login/dashboard/profile.
- Owner parent management.
- Parent ledger access with permissions.

### V28 Reschedule Workflow

- Parent and teacher reschedule requests.
- Owner review, approve, reject.
- Reschedule message event creation.
- Substitute/actual teacher support.

### V28.2 / V29.5 Open Slots

- Manual open slot add/toggle.
- Auto-gap open slot detection.
- Parent can choose any teacher's available open slot.
- Open slot management page with Available / Used / Inactive.
- Used manual slots are locked after approval.

### V29 Message Center

- Unified message threads.
- Parent, teacher, owner inboxes.
- Two-way parent-teacher messages.
- Attachments for images, videos, PDFs/docs/text.
- Unread counts on teacher/parent dashboards.

### V29.4 Reschedule Polish

- Saves requested teacher/classroom/source from selected slot.
- Owner approves actual teacher/date/time/room.
- Reject requires reason.
- Duplicate review blocked.
- Manual open slot becomes used after approval.

### V30 Owner Command Center

- Owner home has Today Needs Attention.
- Shows pending reschedules, unread messages, sub requests, open invoices, low lesson students.
- Quick action badges added.

### Teacher Management

- `/teachers` added.
- Add/edit/toggle/delete teacher.
- Teacher login user is synchronized.
- Safe delete: teachers with history are deactivated instead of removed.
- Course-specific teacher pay is managed through `/rate_overrides` and `/add_teacher_course_rate`.

### V31.0 Deploy Prep

- Added Render deployment files:
  - `requirements.txt`
  - `runtime.txt`
  - `render.yaml`
  - `DEPLOY_RENDER.md`
  - `.gitignore`
- `app.py` now supports production environment variables:
  - `HMUSIC_DB_PATH`
  - `HMUSIC_UPLOAD_DIR`
  - `HMUSIC_SECRET_KEY`
- Target domain for parent app/backend:
  - `https://app.h-musicandarts.com`
- Planned hosting:
  - Render web service
  - Squarespace DNS CNAME for `app`

## Important Routes

Owner:

- `/` owner command center
- `/students`
- `/add_student`
- `/teachers`
- `/add_teacher`
- `/parents`
- `/add_parent`
- `/calendar`
- `/open_slots`
- `/owner_reschedule_requests`
- `/messages`
- `/teacher_rate_cards`
- `/rate_overrides`
- `/add_teacher_course_rate`
- `/course_types`
- `/owner_sub_requests`
- `/invoices`
- `/payroll`

Parent:

- `/parent_login`
- `/parent_dashboard`
- `/parent_reschedule`
- `/parent_messages`
- `/parent_profile`

Teacher:

- `/teacher_login`
- `/teacher_dashboard`
- `/teacher_messages`
- `/teacher_reschedule`
- `/teacher_sub_request`
- `/open_slots`

## Core Data Tables

- `students`
- `teachers`
- `users`
- `schedule`
- `parent_profiles`
- `parent_students`
- `parent_activity_logs`
- `reschedule_requests`
- `teacher_open_slots`
- `message_threads`
- `messages`
- `message_attachments`
- `notifications`
- `course_types`
- `teacher_course_rates`
- `student_course_rates`
- `teacher_rate_cards`
- `invoices`
- `payments`
- `student_ledger`
- `sub_requests`

## Trial Operation Test Flow

Use this exact flow when testing with real or test data:

1. Owner opens `/`.
2. Owner adds teacher at `/teachers` if needed.
3. Owner creates student at `/add_student`.
4. Owner creates or confirms schedule in calendar/add schedule flow.
5. Owner creates parent at `/add_parent`.
6. Owner links parent to student in parent detail page.
7. Parent logs in at `/parent_login`.
8. Parent opens `/parent_dashboard`.
9. Owner or teacher creates manual open slot at `/open_slots`.
10. Parent submits `/parent_reschedule`.
11. Owner sees pending request in `/`.
12. Owner reviews `/reschedule_request/<id>` and approves.
13. Confirm schedule moved.
14. Confirm open slot is Used/Locked.
15. Confirm message thread exists in parent/teacher/owner message center.

## Current Known Notes

- `app.py` is a large single-file Flask app. Keep future changes small and tested.
- `hmusic.db` is local runtime data and should be backed up before real trial use.
- Existing older files in this repo are experiments/prototypes; current main system is `app.py`.
- Course-specific teacher pay should be done in `teacher_course_rates` via `/rate_overrides`, not only default teacher rate cards.

## Suggested Git Checkpoint

Commit message:

`V30.2 core workflow stabilization`

Latest deployment checkpoint:

`V31.0 Render deploy prep`
