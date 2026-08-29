# Academia–Industry Collaboration Portal — College Submission

## Project
A role-aware Flask portal connecting Students, Faculty, Industry and Platform Administrators through shared records and workflows.

## Implemented Features
- Role-based Student / Faculty / Industry / Admin workspaces
- CAPTCHA-protected login and signup
- Signup without mandatory OTP verification
- Profile pages and profile-photo support
- Skill assessment with question bank, randomized selection and score calculation
- Skill-gap analysis and AI recommendations
- Course enrollment, approval/verification, attendance, progress and completion
- Certification submission and administrator verification
- Industry opportunities and student applications
- Faculty guidance, mentorship and collaboration
- AI chatbot / Academia Assistant
- Notifications and messages
- Admin verification, permissions, analytics and audit areas
- PostgreSQL-ready deployment with SQLite fallback for local demo
- Gunicorn, Docker and Render configuration
- `/healthz` health-check endpoint

## Demo Accounts
Password for all seeded demo accounts: `demo123`

| Role | Email |
|---|---|
| Student | student@demo.com |
| Faculty | faculty@demo.com |
| Industry | industry@demo.com |
| Platform Admin | admin@demo.com |
| Super Admin | superadmin@demo.com |

These are fictional demo credentials. Change them before real deployment.

## Local Run
On Windows:

```bat
run_windows.bat
```

Then open:

`http://127.0.0.1:5000`

## Deployment
The project contains `render.yaml`, `Dockerfile`, `Procfile`, `gunicorn.conf.py`, PostgreSQL configuration and environment-variable support.

Never commit `.env`, API keys, passwords or a production database.

## Suggested Demonstration
Student login → Profile/photo → Skill Assessment → Score → Skill Gap → AI Recommendation → Course enrollment → Admin verification → Progress/completion → AI Assistant → Industry opportunity/application → Faculty guidance → Admin governance/audit.

## Submission Note
This is an academic demonstration project. Seeded data is fictional. Production use should add persistent object storage, backups, monitoring, rate limiting and a long-lived managed database.
