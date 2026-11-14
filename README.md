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
| POST | `devices/` · `devices/remove/` | Register / remove the phone's push token |

Demo content: `python manage.py load_demo_proposals` (remove with `--remove`). Every demo proposal is marked Illustrative.

## Text-message alerts (Twilio)
People without the app can text the CivicSpeak number to sign up. They send:
1. **Their address.** Only the first 3 characters of the postal code (e.g. `M5R`) are stored, never the full address.
2. **Their topics,** by number (`1 2 5`) or `ALL`.
3. **Their area:** `1` near me (their neighbourhood + city-wide) or `2` the whole city.

After that they get a text whenever a matching proposal is **published**, **changes** (status, stage, input opens or closes, summary), or gets a new **update** or **impact** in the admin console. Small edits send at most one text per proposal every `SMS_COOLDOWN_HOURS`.
Any time, they can text `TOPICS`, `AREA`, `ADDRESS`, `SETTINGS`, `HELP` or `STOP` (Twilio handles STOP/START automatically).

**Setup**
1. Buy a Canadian number in Twilio (or create a Messaging Service).
2. Add the environment variables in `.env.example` to Coolify: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` (or `TWILIO_MESSAGING_SERVICE_SID`). Keys are only read from the environment, never stored in code.
3. In Twilio, set the number's **"A message comes in"** webhook to `https://YOUR-DOMAIN/sms/twilio/` (HTTP POST). Optional status callback: `https://YOUR-DOMAIN/sms/twilio/status/`.
4. In `/admin/` → Neighbourhoods, fill in each neighbourhood's **postal FSAs** (e.g. `M5R, M5S`) so "near me" works. Until then, near-me subscribers get city-wide proposals.
5. Check it works: `python manage.py sms_test +1YOURNUMBER`.

Every incoming request is checked against Twilio's signature. If checks fail behind Coolify's proxy, set `TWILIO_WEBHOOK_URL` to the exact URL saved in Twilio.
Without Twilio keys, texts are saved in `/admin/` → SMS messages with status `not_configured` instead of being sent.

**Try it without a phone**
```bash
python manage.py sms_simulate +14165550000 "hi"
python manage.py sms_simulate +14165550000 "100 Bloor St W, M5R 1A1"
python manage.py sms_simulate +14165550000 "1 2 3"
python manage.py sms_simulate +14165550000 "1"
python manage.py sms_simulate +14165550000 --alerts
```
Subscribers and every text sent or received are listed in `/admin/` → SMS subscribers.

## Push notifications (Flutter app, Firebase Cloud Messaging)
When staff **publish** a proposal, **change** it (status, stage, input opens or closes, summary), or post an **update** or **impact**,
residents get a push if they chose app notifications in the survey and either:
- **follow** the proposal, or
- **match** it: one of their topics, and their area (whole city, their neighbourhood, their postal area, or the proposal's pin inside
  their neighbourhood's boundary), and their timing ("every update", or "only when I can have a say").

Each push is also saved to the app's bell. Small edits send at most one push per proposal every `ALERT_COOLDOWN_HOURS`.
Phones that uninstall the app are turned off automatically. Devices are listed in `/admin/` → Device tokens.

**Setup:** in Firebase → Project settings → Service accounts → *Generate new private key*, then set `FIREBASE_CREDENTIALS_JSON`
in Coolify (the JSON, or `base64 -w0 key.json`). Never commit the key. Without it, the bell still works and pushes are skipped.
Text messages and pushes are both triggered from `server/alerts.py`.
