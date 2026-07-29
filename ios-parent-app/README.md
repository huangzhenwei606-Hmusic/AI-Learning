# H-Music Parent Mobile App

This folder is the native mobile wrapper for the H-Music parent app on iOS and Android. It opens only the parent app entry:

https://hmusic-crm.onrender.com/parent_login?native_app=1

Owner and teacher dashboards remain web-only.

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

- App Store Connect app name: H-Music Parent
- Bundle ID: `com.hmusicandarts.parent`
- Category: Education
- Target users: existing H-Music families
- Privacy Policy URL: `https://hmusic-crm.onrender.com/privacy`
- Terms URL: `https://hmusic-crm.onrender.com/terms`
- Reviewer demo account: create a parent-only demo account in production before submission.

## Google Play Settings

- Play Console app name: H-Music Parent
- Package name: `com.hmusicandarts.parent`
- Category: Education
- Default language: English (United States)
- Target users: existing H-Music families
- Privacy Policy URL: `https://hmusic-crm.onrender.com/privacy`
- Terms URL: `https://hmusic-crm.onrender.com/terms`
- Payments are for real-world music lessons and tuition, not digital goods.

## Android Release Build

Install Android Studio first. Android Studio includes the Android SDK; make sure it is configured with a Java runtime before running Gradle builds.

1. Run:

```bash
npm run sync:android
```

2. Run:

```bash
npm run open:android
```

3. In Android Studio, choose `Build > Generate Signed Bundle / APK`.
4. Choose `Android App Bundle`.
5. Create or select the H-Music upload key.
6. Build the release `.aab` file.
7. Upload the `.aab` to Google Play Console.

Keep the upload key safe. Google Play updates must use the same package name and a higher `versionCode`.

## Review Notes

The app is a secure WebView wrapper for enrolled H-Music families. Families can view schedules, messages, lesson records, invoices, and package balances. Payments are for real-world music lessons and tuition. Stripe and Square may be used for secure external payment checkout.
