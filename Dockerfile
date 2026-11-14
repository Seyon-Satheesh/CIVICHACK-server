# Source: https://fmacedo.com/posts/coolify-your-django-project/

# Dockerfile
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /code

WORKDIR /code

# If you want to use poetry
# RUN pip install poetry
# COPY pyproject.toml poetry.lock /code/
# RUN poetry config virtualenvs.create false
# RUN poetry install --only main --no-root --no-interaction

# If you want to use pip
COPY requirements.txt /code/
RUN pip install -r requirements.txt

COPY . /code

RUN python manage.py collectstatic --noinput

RUN chmod +x /code/entrypoint.sh




# FROM python:3.12-slim

# ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# WORKDIR /app

# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

# COPY . .
# RUN python manage.py collectstatic --noinput

# EXPOSE 8000
# CMD ["sh", "-c", "python manage.py migrate && gunicorn backend.wsgi:application --bind 0.0.0.0:8000 --workers 3"]