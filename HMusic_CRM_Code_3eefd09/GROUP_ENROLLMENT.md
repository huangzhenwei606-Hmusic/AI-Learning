# Website group enrollment

## Manager workflow

1. In Calendar, create the actual group lessons with their teacher, course type,
   duration and room. Keep these as Scheduled until attendance is recorded.
2. New Students / Intake → Group Classes → create an offer. Select the existing
   future sessions, set capacity, total tuition, age/level and the parent policy.
   Offers start as drafts; planning drafts may be saved before dates are linked.
   Complete the draft, check dates and price, then publish.
3. The website's Piano Group page links to `/group-classes`. Families apply
   without an app login; their submission also appears in the existing Intake.
4. Group Enrollments → review the application and explicitly select the correct
   existing child or create a new profile. This establishes guardian access, so
   verify the family. Approve creates a zero-credit course wallet and an unpaid
   invoice, and reserves a seat for 48 hours. It does not send email or charge a card.
5. Use the existing invoice / Quick Pay workflow to review and share payment
   instructions. Verify Zelle through Billing; bank processing is not Paid.
6. Once Paid, Confirm paid enrollment adds the student to each calendar roster
   and activates their wallet. Existing invoice settlement grants credits;
   admission never grants them a second time. New parents can use the existing
   account password-reset / invitation flow.

## Behavior

- No real offers or tuition are seeded. Managers publish their own confirmed data.
- Existing calendar sessions are the only date/time source; no duplicate lessons.
- A session can belong to only one offer. Offers cannot mix duration or
  course type; rotating teachers retain their actual per-session assignments. Enrollment is blocked if dates have started or a session is no
  longer Scheduled. For a class already running, select the remaining sessions
  in a separate offer with its own reviewed tuition.
- Actual participants, live holds, paid holds and submitted bank-processing
  holds count toward capacity. Paid and processing holds do not expire.
- Class row locks serialize approvals on PostgreSQL; BEGIN IMMEDIATE serializes
  SQLite writes. Duplicate requests and already-approved student profiles cannot
  create a second invoice for the same class.
- Private receipt URLs contain an unguessable browser-specific token; stored
  receipt hashes, no-store and no-referrer protect family information.
- All mutations retain the application's global CSRF protection. Administrative
  pages require the existing manager role. Application honeypot, contact limits
  and persistent per-IP (hashed) / per-email hourly limits reduce spam.
- Policies, tuition and the submitted date snapshot are retained with the
  application. Tuition excludes unrelated pending lesson fees. Existing invoices,
  parent account passwords, private lesson wallets and historical records are
  not overwritten.
- Invoiced / paid cancellations and refunds must be resolved through Billing;
  they are not silently erased by the enrollment queue.

## Verification

`python -m unittest test_group_enrollment` exercises public submission, actual
invoice creation, capacity including concurrent approval, duplicate detection,
identity matching, bank-processing holds, roster / wallet links and access checks.
The Render build includes these tests and the existing regression suite.

## Manager editing and class images

Draft details and cancellation/makeup policy can be edited in Group Classes. Dates, teachers and locations remain sourced from Calendar; each linked date has an entry to its calendar month and teacher. Close registration before editing terms. Existing applications retain their submitted policy snapshot and prevent overwriting agreed terms.

Managers can upload or replace a class cover image independently of tuition and enrollment. PNG/JPEG/WebP uploads are limited to 4 MB and 20 megapixels, decoded and re-encoded as JPEG (metadata discarded, max 1600px). Images are stored durably in the CRM database. Draft image access requires owner authentication; published images appear in the catalog and application form. Uploads never publish a draft or create students/invoices.

## Calendar date picker

Group Classes now has visible Edit Basic Information and Edit Dates & Times actions. The date editor supports selecting dates across months, then setting a group course/duration, time, teacher and location/room in bulk or individually. Saving creates or updates native calendar rows and links them to the draft offer; it creates no students, invoices or credits. Teachers may alternate.

The server validates all selected dates and active course/teacher/room choices before writing; native pricing and teacher/room conflict checks are reused. Repeated or stale saves are rejected using a calendar version hash. Existing empty sessions retain their IDs; deselected sessions are cancelled rather than deleted. Classes with applications, past sessions or existing student rosters must use the existing Calendar workflow for changes. Registration is never automatically published by a schedule save.

Teacher and room overlaps in the group date picker are advisory only. A valid plan saves all lessons, then the manager sees a successful-save notice and an amber list of overlap details. Conflict warnings do not block creating or updating empty draft class sessions.
