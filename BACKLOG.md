# H-Music CRM Backlog

## Now

- Run real trial with 1-2 real students, parents, and teachers.
- Before trial, make a copy of `hmusic.db` as backup.
- Verify teacher course pay for each real course type:
  - one-on-one
  - trial lesson
  - group class
  - makeup/substitute lesson if used

## Next

- Add database backup/export button for owner.
- Add confirmation pages for dangerous actions:
  - delete/deactivate teacher
  - unlink parent/student
  - approve reschedule
- Improve add schedule flow so it is easier to create one-off or package schedules.
- Add clear Teacher Management link in more places if owner keeps looking for it.
- Add edit/delete for teacher course pay records, not only add/list.
- Add unread badge to owner top navigation, not only Command Center.

## Bugs To Watch During Trial

- Parent login field is `parent_email`; keep forms consistent.
- Teacher delete should never remove teachers with historical schedules.
- Reschedule approval should always lock manual open slots.
- Parent should never see inactive or used open slots.
- Teacher should only manage their own open slots unless owner.
- Course-specific teacher pay should override course default pay.

## Later

- Email/SMS/WeChat notifications.
- Automated parent payment reminders.
- Stripe/Zelle reconciliation.
- Calendar drag/drop reschedule.
- Better UI system/shared templates.
- Split `app.py` into modules after trial stabilizes.
- Role-based permission audit.
- Daily automated database backup.

## Ideas

- Owner dashboard weekly revenue forecast.
- Teacher payroll preview before month end.
- Parent mobile-first dashboard polish.
- Message templates for reschedule approval/rejection.
- Student progress timeline.
- AI-generated lesson summary review flow.
