# Academia–Industry Collaboration Portal — Deployment Guide

This package is prepared for production-style deployment of the Flask portal.

## 1. Local production test

Windows:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

Open `http://127.0.0.1:5000`.

## 2. Render deployment (recommended)

1. Push this folder to a private GitHub repository.
2. Do **not** commit `.env`, `instance/`, database files, or uploaded files.
3. In Render, create a Blueprint from the repository. Render will read `render.yaml`.
4. The Blueprint creates the web service and PostgreSQL database.
5. Set `GEMINI_API_KEY` in the web service Environment settings if AI is required.
6. Deploy and open the generated HTTPS URL.
7. Check `https://YOUR-DOMAIN/healthz` — it should return `{"status":"ok","database":"ok"}`.

## 3. Important production storage note

The application stores profile photos/certificates in `UPLOAD_FOLDER`. A normal ephemeral web filesystem is not durable across deployments/restarts. For production, use a persistent disk supported by your host or object storage and point `UPLOAD_FOLDER` at it. Do not expose private documents through predictable public URLs.

## 4. Database

The app automatically creates its tables on startup. For a serious production migration process, add Alembic/Flask-Migrate before making schema changes.

## 5. Secrets

Set `SECRET_KEY`, `DATABASE_URL`, and `GEMINI_API_KEY` in the host's secret/environment settings. Never commit real credentials.

## 6. Docker

Run:

```bash
docker compose up --build
```

Then open `http://localhost:5000`.

## 7. Production command

```bash
gunicorn app:app --workers 2 --threads 4 --timeout 120 --access-logfile - --error-logfile -
```
