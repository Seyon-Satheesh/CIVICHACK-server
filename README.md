# CivicSpeak – admin console (Django + PostGIS)

## Deploy on Coolify
1. **Database:** a PostgreSQL database using a PostGIS image (for example `postgis/postgis:16-3.4`).
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
