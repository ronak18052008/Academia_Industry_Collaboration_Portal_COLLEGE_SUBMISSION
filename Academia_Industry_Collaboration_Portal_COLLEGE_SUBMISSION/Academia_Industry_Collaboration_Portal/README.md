# Academia–Industry Collaboration Portal — Learning & AI Upgrade

This version extends the existing Flask portal with real learning workflows:
- Student course enrollment with verification workflow.
- AI-recommended course highlighting based on student skill levels.
- FDP applications with verification workflow.
- Approved learners can record attendance and progress; 100% progress plus at least 75% attendance marks completion.
- Notifications and audit logs are generated for enrollment, verification and completion actions.
- Admin Learning Verification queue for approve/reject decisions.
- AI Chatbot sidebar module with Gemini integration when GEMINI_API_KEY is configured and a portal-aware fallback assistant when it is not.
- Existing CAPTCHA, email/phone OTP, profile-photo, role authorization and shared database functionality retained.

Run on Windows with run_windows.bat.
