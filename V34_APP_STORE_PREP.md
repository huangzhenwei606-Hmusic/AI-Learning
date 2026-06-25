# H-Music Parent AI — iOS App Store Prep

## App Identity

- App Store Connect app name: H-Music Parent AI
- Bundle ID: `com.hmusicandarts.parent`
- SKU suggestion: `hmusic-parent-ios`
- Primary category: Education
- Target users: existing H-Music & Arts families
- App type: Parent-only lesson portal. Owner and teacher dashboards remain web-only.

## URLs

- Production app URL: `https://hmusic-crm.onrender.com/parent_login?native_app=1`
- Support URL: `https://www.h-musicandarts.com/`
- Marketing URL: `https://www.h-musicandarts.com/`
- Privacy Policy URL: `https://hmusic-crm.onrender.com/privacy`
- Terms URL: `https://hmusic-crm.onrender.com/terms`

## App Store Description Draft

H-Music Parent AI is an AI-native parent portal for enrolled H-Music & Arts families.

Parents can view upcoming lessons, check lesson balance, message the studio, request reschedules, review lesson notes and homework, and use Family Assistant for common lesson and billing questions. The assistant supports English or Chinese input and is designed to route family requests to the right studio workflow.

Payments are for real-world music lessons and studio services. Tuition checkout and bank/card setup are processed securely through Stripe or studio-approved payment methods.

## Subtitle Draft

AI-native parent lesson portal

## Keywords Draft

music lessons,piano,parent portal,AI assistant,lesson schedule,tuition,H-Music

## App Review Notes Draft

This app is for H-Music & Arts parent accounts only. It includes an AI-native Family Assistant for routing parent lesson, billing, trial, and messaging requests. Owner and teacher dashboards are intentionally not included in the iOS app; those are managed through the web admin system.

Payments are for real-world music lessons and tuition, not digital content. Stripe is used for external tuition billing and bank/card setup. H-Music does not store full card or bank account numbers.

Reviewer demo account:

- Parent email: `[create production demo parent email]`
- Password: `[create demo password]`

Suggested reviewer test path:

1. Sign in with the demo parent account.
2. View upcoming lessons.
3. Open Messages.
4. Open an invoice or payment screen.
5. Open Profile.

## Privacy Nutrition Labels

Fill App Store Connect privacy labels based on current app behavior:

- Contact Info: name, email, phone. Used for app functionality and account management.
- User Content: messages, message attachments, lesson notes, homework. Used for app functionality.
- Financial Info: invoice/payment status and AutoPay preference. Used for payments and account management.
- Identifiers: parent/student account identifiers. Used for app functionality.
- Usage Data: basic app activity/account event logs. Used for app functionality and support.

Payment card and bank account details are handled by Stripe. H-Music should not list full card or bank account numbers as collected by H-Music directly.

## Export Compliance

The app uses standard HTTPS/WebView networking and does not include custom encryption. In App Store Connect, answer export compliance accordingly unless Apple asks a more specific question.

## Screenshots Needed

Capture iPhone screenshots from the simulator or real device:

1. Login screen.
2. Parent home dashboard with upcoming lessons.
3. Messages screen.
4. Reschedule request screen.
5. Invoice/payment screen.
6. Profile or lesson notes/homework screen.

## Before TestFlight

- Confirm App Store Connect app exists for `com.hmusicandarts.parent`.
- Confirm Apple Developer Team is selected in Xcode.
- Confirm version is `1.0` and build is `1`.
- Archive from Xcode: Product > Archive.
- Upload archive to App Store Connect.
- Add external/internal TestFlight tester.

## Before App Review

- Create a production demo parent account.
- Make sure demo parent has at least one linked student.
- Add at least one upcoming lesson for the demo student.
- Add one message thread and one invoice or paid invoice for realistic review.
- Verify `https://hmusic-crm.onrender.com/privacy` is live.
- Verify `https://hmusic-crm.onrender.com/terms` is live.
