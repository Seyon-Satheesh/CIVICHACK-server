#!/bin/sh
# Source: https://fmacedo.com/posts/coolify-your-django-project/ (adapted for CivicSpeak)
set -e
cd /code

# Create migration files for the app if they are not in the repo yet.
# Best practice: run `python manage.py makemigrations server` once locally and commit server/migrations/.
python manage.py makemigrations server --noinput

until python manage.py migrate --noinput
do
    echo "Waiting for the database to be ready..."
    sleep 2
done

# Topics, categories, a municipality and (optionally) the first staff account. Safe to run every deploy.
python manage.py setup_civicspeak

# Set LOAD_DEMO=1 to add three illustrative proposals for the app demo (safe to run every deploy).
if [ "$LOAD_DEMO" = "1" ]; then python manage.py load_demo_proposals; fi

exec gunicorn --bind :8000 --workers 2 --access-logfile - backend.wsgi
