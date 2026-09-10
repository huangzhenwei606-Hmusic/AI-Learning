# H-Music Teacher Mobile App

This folder is the native mobile wrapper for the H-Music teacher app on iOS and Android. It opens the teacher portal entry:

https://hmusic-crm.onrender.com/teacher_login?native_app=1

## Setup

Install dependencies:

```bash
npm install
```

Sync both platforms:

```bash
npm run sync
```

Open iOS in Xcode:

```bash
npm run open:ios
```

Open Android in Android Studio:

```bash
npm run open:android
```

## Apple Settings

- App Store Connect app name: H-Music Teacher
- Bundle ID: `com.hmusicandarts.teacher`
- Category: Education
- Target users: active H-Music teachers
- Privacy Policy URL: `https://hmusic-crm.onrender.com/privacy`
- Terms URL: `https://hmusic-crm.onrender.com/terms`
- Reviewer demo account: create a teacher-only demo account in production before submission.

## Teacher Features

- Today, week, and month schedule views.
- Multi-select lessons and set attendance status.
- Lesson detail with notes, homework, reminders, reschedule, cancel, and sub request actions.
- Parent and owner messages.
- Open slot creation and time off requests.
- Teacher permissions are controlled by the owner in the CRM.

## Backend API Contract

The production Flask app exposes app-friendly JSON endpoints under `/api/teacher/*`:

- `GET /api/teacher/bootstrap`
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

The wrapper can ship first as a native WebView, then individual screens can move to these APIs without changing the backend permission model.
