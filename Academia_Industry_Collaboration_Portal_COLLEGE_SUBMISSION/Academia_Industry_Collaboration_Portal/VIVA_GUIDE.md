# Viva Guide

### What is the project?
A role-aware Academia–Industry Collaboration Portal built with Python Flask that connects students, faculty, industry and administrators.

### Why Flask?
It is lightweight, modular and well suited to a database-backed role-based web application.

### How is the assessment scored?
The application compares each submitted answer with the correct answer and calculates the percentage of correct responses.

### Why are questions different?
A question bank is used and questions are selected for attempts rather than showing one fixed test.

### What happens after course enrollment?
The record enters a verification/approval workflow. Once approved, attendance and progress can be recorded and completion can be tracked.

### How are certifications verified?
Student submissions are stored as pending and an authorized administrator can verify or reject them.

### How is role access controlled?
Authenticated routes use role-aware authorization checks, and navigation is tailored to the user's role.

### Why PostgreSQL for deployment?
It is suitable for shared multi-user relational data and production deployment.

### Why environment variables?
Secrets such as Gemini API keys, database URLs and secret keys should not be hardcoded or committed to source control.

### What does the AI assistant do?
It helps users with portal navigation and learning/career support using the configured AI backend.
