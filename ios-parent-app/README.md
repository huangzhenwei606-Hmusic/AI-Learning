# H-Music Parent iOS App

This folder is the native iOS wrapper for the H-Music parent app. It points only to the parent app entry at:

https://hmusic-crm.onrender.com/parent_login

Owner and teacher dashboards remain web-only.

## Setup

1. Install dependencies:

```bash
npm install
```

2. Generate the iOS project:

```bash
npx cap add ios
```

3. Sync changes:

```bash
npm run sync
```

4. Open Xcode:

```bash
npm run open:ios
```

## Apple Settings

- App Store Connect app name: H-Music
- Bundle ID: `com.hmusicandarts.parent`
- Category: Education
- Target users: existing H-Music families
- Reviewer demo account: create a parent-only demo account in production before submission.

## App Review Notes

Payments are for real-world music lessons and tuition. Stripe is used for external tuition billing, not digital content.
