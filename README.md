# CivicSpeak – admin console (Django + PostGIS)

## Deploy on Coolify
1. **Database:** a PostgreSQL database using a PostGIS image (for example `postgis/postgis:18-3.6`).
2. **App:** this repo with the **Dockerfile** build pack (or Docker Compose). Port **8000**.
3. **Environment variables:**

| Name | Example |
|---|---|
| `DATABASE_URL` | `postgres://postgres:PASSWORD@DB_HOST:5432/postgres` (Coolify shows this on the database page) |
| `SECRET_KEY` | a long random string |
| `ALLOWED_HOSTS` | `civicspeak.example.com` |
| `CSRF_TRUSTED_ORIGINS` | `https://civicspeak.example.com` |
| `DEBUG` | `False` |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` / `ADMIN_EMAIL` | first staff account (created once) |
| `MUNICIPALITY_NAME` / `MUNICIPALITY_PROVINCE` | `Toronto` / `ON` (defaults) |
| `CORS_ALLOWED_ORIGINS` | `*` (default) or the origins allowed to call `/api/` from a browser |
| `LOAD_DEMO` | `1` to add three illustrative proposals for the app demo |

On start the container creates migrations if needed, migrates, runs `setup_civicspeak` (topics, categories,
municipality, first staff account), then starts gunicorn.

- Admin console: `/` (sign in with `ADMIN_USERNAME`)
- Django admin for IT setup (neighbourhoods, more staff accounts, sources): `/admin/`

## Run locally
Needs Python 3.12, PostgreSQL with PostGIS, and GDAL (`brew install gdal` / `apt install gdal-bin libgdal-dev`).
```bash
pip install -r requirements.txt
export DATABASE_URL=postgres://postgres:postgres@localhost:5432/civicspeak DEBUG=True ADMIN_USERNAME=admin ADMIN_PASSWORD=change-me
python manage.py makemigrations server && python manage.py migrate && python manage.py setup_civicspeak
python manage.py runserver
```
Commit `server/migrations/` once it is generated so every deploy uses the same migrations.

## Resident API (for the CivicSpeak Flutter app)
All under `/api/`, JSON in and out. Sign-in returns a token; send it as `Authorization: Bearer <token>`.

| Method | Path | What it does |
|---|---|---|
| GET | `meta/` | Municipality, neighbourhoods and topics for the survey (no sign-in) |
| POST | `auth/register/` | Survey answers + username/password → token and profile |
| POST | `auth/login/` | Username/password → token and profile |
| GET / PATCH | `me/` | Profile, survey answers, language, audio mode, text size |
| GET | `proposals/?status=ongoing\|completed\|abandoned` | Brief cards, personalized order |
| GET | `proposals/<id>/` | Full proposal (no vote totals for residents) |
| POST | `proposals/<id>/follow/` | Follow / unfollow (pins it on the map) |
| POST | `proposals/<id>/feedback/` | Support / Neutral / Oppose + comment, only while input is open |
| GET | `proposals/<id>/funding/` | Cost, payers and reserve fund statements |
| GET | `map/?status=ongoing\|completed&only_following=1` | Pins with impact radius |
| GET | `community/` | One staff post per completed proposal |
| GET | `notifications/` · POST `notifications/read/` | Notifications and mark as read |

Demo content: `python manage.py load_demo_proposals` (remove with `--remove`). Every demo proposal is marked Illustrative.
