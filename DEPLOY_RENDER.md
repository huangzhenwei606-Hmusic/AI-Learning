# Deploy H-Music CRM on Render

Target production URL:

```text
https://app.h-musicandarts.com
```

## What This Prep Adds

- `requirements.txt` for Python dependencies.
- `runtime.txt` for Python version.
- `render.yaml` for Render Blueprint deploy.
- Environment-variable support in `app.py`:
  - `HMUSIC_DB_PATH`
  - `HMUSIC_UPLOAD_DIR`
  - `HMUSIC_SECRET_KEY`
- `.gitignore` to avoid committing local database/runtime files.

## Render Settings

If creating the service manually instead of Blueprint:

```text
Language: Python 3
Build Command: pip install -r requirements.txt
Start Command: gunicorn app:app
```

Environment variables:

```text
HMUSIC_DB_PATH=/var/data/hmusic.db
HMUSIC_UPLOAD_DIR=/var/data/message_uploads
HMUSIC_SECRET_KEY=<generate a long random value>
```

Persistent disk:

```text
Mount path: /var/data
Size: 1 GB
```

The SQLite database and message attachments must live on the persistent disk. Do not rely on Render's normal app filesystem for production data.

## First Deploy Flow

1. Push this repo to GitHub.
2. In Render, create a new Web Service or Blueprint from the repo.
3. Confirm the service starts at the Render URL.
4. Upload or initialize `hmusic.db` on the persistent disk before using real data.
5. In Render, add custom domain:

```text
app.h-musicandarts.com
```

6. In Squarespace DNS, add the CNAME Render asks for.
7. Return to Render and verify the domain.
8. Test:

```text
https://app.h-musicandarts.com/parent_login
https://app.h-musicandarts.com/teacher_login
https://app.h-musicandarts.com/
```

## Important Warnings

- Do not commit `hmusic.db` to GitHub. It contains operational data.
- Before trial operation, make a local backup of `hmusic.db`.
- Render custom domains automatically get HTTPS certificates after DNS verifies.
- The current app is still a single-file Flask app; keep production changes small and tested.

## Squarespace DNS

Do not change existing records for:

```text
www.h-musicandarts.com
h-musicandarts.com
```

Only add a new record for:

```text
app.h-musicandarts.com
```

Render will show the exact target value for the CNAME.
