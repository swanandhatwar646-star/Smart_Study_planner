# Smart Study Planner API

A standalone FastAPI backend that turns a student's subjects, exam dates, difficulty, preparation level
and available time into a conflict-free study timetable. It uses a rule-based algorithm (no AI model),
so the schedule always respects the time constraints.

## 1. Run locally (Windows / VS Code)

```bash
cd smart_study_planner
python -m venv venv
venv\Scripts\activate              # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

* API: `http://127.0.0.1:8000`
* Swagger UI (interactive docs): `http://127.0.0.1:8000/docs`
* Health check: `http://127.0.0.1:8000/health`

To let a friend on the same Wi-Fi call it: `uvicorn main:app --host 0.0.0.0 --port 8000`
and use `http://<your-pc-ip>:8000` (find the IP with `ipconfig`).

## 2. Test in Swagger UI

1. Open `http://127.0.0.1:8000/docs`.
2. Click **POST /generate-study-plan** -> **Try it out**. The body is pre-filled with an example.
3. Change every `exam_date` (and `start_date`) so the exams are in the future, then click **Execute**.
4. Read the result under **Response body**. Wrong input (for example an exam date in the past) returns a clear error.

Automated tests: `pip install pytest httpx` then `pytest -q`.

## 3. API reference (for the frontend developer)

| Item | Value |
|---|---|
| Endpoint | `POST {BASE_URL}/generate-study-plan` (local: `http://127.0.0.1:8000/generate-study-plan`) |
| Required header | `Content-Type: application/json` |
| Authentication | none |
| Success | `200` with `"status": "success"` |
| Errors | `422` (bad input or impossible plan) or `500`, always in the error format below |

### Request body

| Field | Type | Required | Notes |
|---|---|---|---|
| `subjects` | array (1-15) | yes | see below |
| `subjects[].name` | string | yes | unique per request |
| `subjects[].difficulty` | number 0-100 **or** `"Easy"` / `"Medium"` / `"Hard"` | yes | labels map to 30 / 60 / 90 |
| `subjects[].preparation` | number 0-100 | yes | % already prepared |
| `subjects[].exam_date` | `"YYYY-MM-DD"` | yes | must be after `start_date`, within 120 days |
| `subjects[].topics` | array of strings | no | syllabus topics |
| `available_hours_per_day` | number (>0, <=16) | yes | |
| `study_start_time` | `"HH:MM"` (24h) | no, default `18:00` | |
| `session_duration` | integer minutes, 15-180 | no, default `45` | |
| `break_duration` | integer minutes, 0-60 | no, default `10` | |
| `available_days` | array of weekday names | no, default all 7 | `"Monday"` and `"mon"` both work |
| `start_date` | `"YYYY-MM-DD"` | no, default today (server date) | send tomorrow's date if today's study time has passed |

```json
{
  "subjects": [
    {"name": "Java", "difficulty": 50, "preparation": 70, "exam_date": "2026-11-15",
     "topics": ["OOP", "Inheritance", "Polymorphism"]},
    {"name": "DBMS", "difficulty": "Hard", "preparation": 30, "exam_date": "2026-11-15",
     "topics": ["Normalization", "SQL", "Transactions"]}
  ],
  "available_hours_per_day": 3,
  "study_start_time": "18:00",
  "session_duration": 45,
  "break_duration": 10,
  "available_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
  "start_date": "2026-10-26"
}
```

### Success response (shortened)

```json
{
  "status": "success",
  "plan": {
    "start_date": "2026-10-26",
    "end_date": "2026-11-14",
    "total_study_minutes": 1800,
    "total_sessions": 40,
    "sessions": [
      {
        "id": "S001", "date": "2026-10-26", "day": "Monday",
        "subject": "DBMS", "topic": "Normalization (part 1/7)", "session_type": "study",
        "start_time": "18:00", "end_time": "18:45", "duration": 45, "break_after": 10,
        "priority": "High", "status": "pending"
      }
    ],
    "daily_timetable": [
      { "date": "2026-10-26", "day": "Monday", "total_minutes": 135, "sessions": ["..."] }
    ],
    "weekly_timetable": [
      { "week_number": 1, "week_start": "2026-10-26", "week_end": "2026-11-01",
        "total_minutes": 945, "total_sessions": 21,
        "subject_minutes": { "DBMS": 495, "Java": 450 }, "days": ["..."] }
    ],
    "subject_summary": [
      { "subject": "DBMS", "exam_date": "2026-11-15", "days_until_exam": 20,
        "priority_score": 70.67, "priority": "High", "study_sessions": 21,
        "revision_sessions": 5, "allocated_minutes": 1170,
        "recommended_minutes": 597, "coverage_percent": 100 }
    ]
  },
  "warnings": []
}
```

* `sessions` is the full flat list. `daily_timetable` and `weekly_timetable` hold the same sessions grouped by day / week (Monday-Sunday weeks).
* `session_type` is `"study"` or `"revision"`. `priority` is `"High"`, `"Medium"` or `"Low"` (handy for colours).
* `break_after` is the break in minutes after a session (0 for the last session of a day).
* `status` is always `"pending"` when generated. **Completion tracking belongs to the frontend / main app in this version**:
  store the whole generated plan and keep each session's `id` with its completed/pending status.
* `warnings` is an array of readable strings. Show them to the student (for example "Limited time for DBMS ...").

### Error response

```json
{
  "status": "error",
  "message": "subjects.0.preparation: Input should be less than or equal to 100",
  "errors": [ { "field": "subjects.0.preparation", "message": "Input should be less than or equal to 100" } ]
}
```
Show `message` to the user, or use `errors[].field` to highlight the wrong form field.

## 4. Calling it from JavaScript

```javascript
const API_BASE_URL = "http://127.0.0.1:8000"; // replace with the deployed URL

async function generateStudyPlan(formData) {
  const response = await fetch(`${API_BASE_URL}/generate-study-plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(formData),
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || "Could not generate the study plan.");
  }
  return data; // { status, plan, warnings }
}

// Example usage
generateStudyPlan({
  subjects: [
    { name: "DBMS", difficulty: "Hard", preparation: 30, exam_date: "2026-11-15", topics: ["SQL", "Normalization"] },
  ],
  available_hours_per_day: 3,
  study_start_time: "18:00",
  session_duration: 45,
  break_duration: 10,
  available_days: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
})
  .then(({ plan, warnings }) => {
    console.log(plan.daily_timetable, warnings);
  })
  .catch((err) => alert(err.message));
```

## 5. CORS

CORS is already enabled in `main.py`. By default every origin is allowed (good for development).
Before sharing publicly, restrict it with an environment variable:

```bash
# Windows (cmd)
set ALLOWED_ORIGINS=http://localhost:3000,https://your-frontend.vercel.app
# macOS/Linux
export ALLOWED_ORIGINS=http://localhost:3000,https://your-frontend.vercel.app
```
On a hosting service, add `ALLOWED_ORIGINS` on its "Environment variables" page.
If the frontend is served over `https://`, the API must also be `https://` (all hosts below do this automatically).

## 6. Deploy online (example: Render, free tier)

1. Put the project files in a GitHub repository (at the repo root, or set Root Directory on Render).
2. On https://render.com choose **New -> Web Service** and connect the repository.
3. Settings:
   * Runtime: **Python 3**
   * Build command: `pip install -r requirements.txt`
   * Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   * Environment variable: `ALLOWED_ORIGINS` = your frontend URL(s)
4. Deploy. Render gives a URL like `https://smart-study-planner.onrender.com`. Check `/health`, then open `/docs`.
5. Give that URL to your friend as `API_BASE_URL`.

Free-tier services sleep when idle, so the first request after a pause can take 30-60 seconds.
Railway, Fly.io or any VPS work with the same start command.

## 7. How the algorithm works

1. **Study days**: the selected weekdays from `start_date` up to the day *before* the last exam.
2. **Sessions per day**: how many `session + break` blocks fit into the daily hours (and before midnight).
   Example: 3 hours, 45 min sessions, 10 min breaks -> 3 sessions.
3. **Priority** (all 0-100): `0.4 x Difficulty + 0.4 x (100 - Preparation) + 0.2 x Urgency`, where
   `Urgency = 100 x (1 - days_left / 30)` (0 when the exam is 30+ days away, about 97 when it is tomorrow).
   It is recalculated for every day, so a subject gets a bigger share as its exam gets closer.
4. **Allocation**: each session slot goes to the subject with the largest accumulated need (weighted round-robin).
   Difficult, poorly prepared and urgent subjects get more time, subjects are mixed instead of long repeats,
   and a subject is never scheduled on or after its own exam date.
5. **Revision**: the last ~20% of each subject's sessions are revision (subjects with fewer than 3 sessions get none).
6. **Topics**: spread in order over the sessions (several topics may share a session, or one topic may span several sessions).
7. **Times**: sessions are placed one after another with breaks, so overlaps are impossible.
8. **Warnings**: a subject gets a warning if no time could be scheduled for it, or if its scheduled time is below 80% of a
   recommended estimate (3 hours per topic, scaled by difficulty and preparation), or if the start time leaves no room before midnight.

Tune the numbers (weights, 30-day horizon, 20% revision) at the top of `priority.py` and `scheduler.py`.

## 8. Project files

```
main.py           FastAPI app, CORS, error handlers, endpoints
schemas.py        request validation + response models
scheduler.py      the scheduling algorithm
priority.py       priority formula
requirements.txt  dependencies
test_planner.py   automated tests
README.md         this guide
```
