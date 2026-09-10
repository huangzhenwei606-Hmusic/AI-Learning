# V35 Teacher App Store Prep

## Scope

H-Music Teacher is for active H-Music teachers. It gives teachers mobile access to schedule, attendance, lesson notes, homework, parent messages, open slots, time off requests, substitute requests, and teacher-controlled workflow items.

Owner and billing administration remain controlled by the CRM web owner account. Teacher access is limited by owner-managed teacher permissions.

## App Store Metadata

- App name: H-Music Teacher
- Bundle ID: `com.hmusicandarts.teacher`
- Category: Education
- Audience: H-Music teachers only
- Privacy Policy URL: `https://hmusic-crm.onrender.com/privacy`
- Terms URL: `https://hmusic-crm.onrender.com/terms`
- Reviewer account: create a production teacher demo account with sample schedule, messages, and homework.

## Required Screenshots

- Login screen.
- Today schedule with Day / Week / Month selector.
- Multi-select status workflow.
- Lesson detail with note and homework fields.
- Messages screen.
- Open slot or time off request screen.

## Teacher Mobile API

- `GET /api/teacher/bootstrap` returns teacher identity, permissions, counts, server time, and `csrf_token`.
- `POST /api/teacher/device_token`
- `GET /api/teacher/calendar?view=day|week|month`
- `GET /api/teacher/lookups`
- `GET /api/teacher/lesson/<schedule_id>`
- `POST /api/teacher/lesson/status`
- `POST /api/teacher/lesson/bulk_status`
- `POST /api/teacher/lesson/save`
- `GET/POST /api/teacher/open_slots`
- `GET/POST /api/teacher/time_off`
- `GET/POST /api/teacher/messages`
- `GET/POST /api/teacher/messages/<thread_id>`
- `POST /api/teacher/add_schedule`

All teacher mobile `POST` requests must send the latest bootstrap token in the `X-CSRFToken` header.

## Notification Readiness

The backend can store teacher APNS/device tokens in `teacher_device_tokens`.
Existing CRM notifications already queue push/email/SMS channels through `notification_delivery_queue`.
APNS provider delivery is still a separate production integration step.

## Review Notes

The app is a secure teacher portal for H-Music staff. Teachers can only access lessons, students, and message threads permitted by their teacher account. The app is not for emergency communication.
