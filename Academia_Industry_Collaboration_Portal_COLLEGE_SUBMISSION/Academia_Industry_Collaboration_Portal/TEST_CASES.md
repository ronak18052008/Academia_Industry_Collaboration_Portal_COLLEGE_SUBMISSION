# Test Cases

| ID | Test | Expected Result |
|---|---|---|
| T01 | Valid Student login | Student dashboard |
| T02 | Wrong password | Login rejected |
| T03 | Invalid CAPTCHA | Form rejected and CAPTCHA refreshed |
| T04 | New Student signup | Account created without OTP |
| T05 | Duplicate email | Registration rejected |
| T06 | Skill assessment | Question set displayed |
| T07 | Submit answers | Score calculated correctly |
| T08 | Repeat assessment | Question bank can provide a different selection |
| T09 | Course enrollment | Pending verification record created |
| T10 | Admin learning verification | Authorized admin can approve/reject |
| T11 | Learning progress | Approved learner can update progress |
| T12 | Certification submission | Pending certification created |
| T13 | Certification verification | Admin can verify/reject |
| T14 | Profile photo | Photo can be uploaded/displayed |
| T15 | Unauthorized route | Access denied |
| T16 | Industry opportunity | Opportunity can be managed |
| T17 | Student application | Application stored |
| T18 | Notifications | Portal events create notifications |
| T19 | AI assistant | User receives assistant response |
| T20 | Health check | `/healthz` responds when service/database are healthy |
