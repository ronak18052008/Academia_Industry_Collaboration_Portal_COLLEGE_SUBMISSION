# Project Report

## Abstract
The Academia–Industry Collaboration Portal is a centralized web platform connecting students, faculty, industry stakeholders and administrators. It supports skills, assessment, learning, certifications, opportunities, applications, recommendations, communication and verification.

## Objectives
1. Provide a single collaboration platform.
2. Implement role-based access and workflows.
3. Measure skills through assessments.
4. Identify skill gaps and recommend learning.
5. Connect students with opportunities.
6. Provide verification and administrative governance.
7. Provide an AI assistant for user support.

## Technology
- Python / Flask
- Jinja HTML templates
- CSS / JavaScript
- Flask-SQLAlchemy
- Flask-Login
- Werkzeug password hashing
- SQLite local fallback
- PostgreSQL deployment
- Gemini API through environment variables
- Gunicorn
- Render / Docker deployment

## Core Workflows
### Skill Assessment
Questions are selected from a question bank. Submitted answers are checked against stored correct answers. Score is calculated as:

`correct answers / total questions × 100`

The result becomes a measurable skill signal.

### Learning
Student selects a course → enrollment is submitted → authorized verification/approval → progress and attendance → completion.

### Certification
Student submits certification → pending verification → administrator verifies or rejects → status is shown to the student.

### Opportunities
Industry publishes opportunities → student views/applies → application is stored for the relevant workflow.

### AI
Academia Assistant supports portal navigation and learning/career questions. AI credentials are configured through environment variables.

## Security
Role-aware route protection, password hashing, CAPTCHA, session authentication, environment-based secrets, verification states and audit records are implemented.

## Future Scope
Persistent object storage for uploads, production email/SMS provider, SSO, backups, advanced analytics and expanded assessment question banks.
