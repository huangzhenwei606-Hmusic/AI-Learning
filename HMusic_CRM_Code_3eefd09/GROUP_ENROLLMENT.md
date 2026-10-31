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
