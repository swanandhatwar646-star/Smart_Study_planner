"""
schemas.py - Pydantic models.

Request models validate everything the frontend sends.
Response models describe exactly what the API returns (this also gives the
frontend developer a complete, auto-generated contract at /docs).
"""
import datetime as dt
from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from priority import DIFFICULTY_LABELS

WEEKDAY_NAMES = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
]

# A plan can start at most this many days before the last exam (keeps responses small).
MAX_PLAN_DAYS = 120


# --------------------------------------------------------------------------- #
# Request
# --------------------------------------------------------------------------- #
class SubjectInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=60, description="Subject name, e.g. 'DBMS'")
    difficulty: Union[int, str] = Field(
        ...,
        description="0-100, or one of the labels 'Easy' (30), 'Medium' (60), 'Hard' (90).",
    )
    preparation: float = Field(..., ge=0, le=100, description="How prepared the student is, 0-100 (%).")
    exam_date: dt.date = Field(..., description="Exam date, format YYYY-MM-DD.")
    topics: List[str] = Field(default_factory=list, max_length=30, description="Optional syllabus topics.")

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Subject name cannot be empty.")
        return value

    @field_validator("difficulty", mode="before")
    @classmethod
    def _normalise_difficulty(cls, value):
        """Accept 'Easy'/'Medium'/'Hard' or a number 0-100 and always return an int."""
        if isinstance(value, bool):
            raise ValueError("difficulty must be Easy, Medium, Hard or a number from 0 to 100.")
        if isinstance(value, str):
            key = value.strip().lower()
            if key in DIFFICULTY_LABELS:
                return DIFFICULTY_LABELS[key]
            try:
                value = float(key)
            except ValueError:
                raise ValueError("difficulty must be Easy, Medium, Hard or a number from 0 to 100.")
        if not isinstance(value, (int, float)) or not 0 <= value <= 100:
            raise ValueError("difficulty must be Easy, Medium, Hard or a number from 0 to 100.")
        return int(round(value))

    @field_validator("topics")
    @classmethod
    def _clean_topics(cls, value: List[str]) -> List[str]:
        return [t.strip() for t in value if isinstance(t, str) and t.strip()]


class StudyPlanRequest(BaseModel):
    subjects: List[SubjectInput] = Field(..., min_length=1, max_length=15)
    available_hours_per_day: float = Field(..., gt=0, le=16, description="Study hours the student has per day.")
    study_start_time: dt.time = Field(dt.time(18, 0), description="Preferred daily start time, 'HH:MM' (24-hour).")
    session_duration: int = Field(45, ge=15, le=180, description="Length of one study session in minutes.")
    break_duration: int = Field(10, ge=0, le=60, description="Break between two sessions in minutes.")
    available_days: List[str] = Field(
        default_factory=lambda: list(WEEKDAY_NAMES),
        min_length=1,
        description="Weekdays the student can study, e.g. ['Monday', 'Tuesday'].",
    )
    start_date: Optional[dt.date] = Field(
        None,
        description="First day of the plan (YYYY-MM-DD). Defaults to today on the server. "
                    "Send tomorrow's date if today's study time has already passed.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "subjects": [
                        {"name": "Java", "difficulty": 50, "preparation": 70,
                         "exam_date": "2026-11-15", "topics": ["OOP", "Inheritance", "Polymorphism"]},
                        {"name": "DBMS", "difficulty": 90, "preparation": 30,
                         "exam_date": "2026-11-15", "topics": ["Normalization", "SQL", "Transactions"]},
                        {"name": "Operating Systems", "difficulty": "Medium", "preparation": 50,
                         "exam_date": "2026-11-15", "topics": ["Process Scheduling", "Deadlocks"]},
                    ],
                    "available_hours_per_day": 3,
                    "study_start_time": "18:00",
                    "session_duration": 45,
                    "break_duration": 10,
                    "available_days": WEEKDAY_NAMES,
                    "start_date": "2026-10-26",
                }
            ]
        }
    }

    @field_validator("available_days", mode="before")
    @classmethod
    def _normalise_days(cls, value):
        """Accept 'monday', 'MON', 'Monday' ... and return full names without duplicates."""
        if not isinstance(value, list):
            raise ValueError("available_days must be a list of weekday names.")
        lookup = {}
        for name in WEEKDAY_NAMES:
            lookup[name.lower()] = name
            lookup[name[:3].lower()] = name
        result: List[str] = []
        for item in value:
            key = str(item).strip().lower()
            if key not in lookup:
                raise ValueError(f"'{item}' is not a valid weekday. Use names like 'Monday'.")
            if lookup[key] not in result:
                result.append(lookup[key])
        return result

    @model_validator(mode="after")
    def _check_whole_request(self):
        # 1. Default start date = today.
        if self.start_date is None:
            self.start_date = dt.date.today()

        # 2. Subject names must be unique.
        names = [s.name.lower() for s in self.subjects]
        if len(names) != len(set(names)):
            raise ValueError("Subject names must be unique.")

        # 3. Exam dates must be after the start date and not too far away.
        latest_allowed = self.start_date + dt.timedelta(days=MAX_PLAN_DAYS)
        for s in self.subjects:
            if s.exam_date <= self.start_date:
                raise ValueError(
                    f"exam_date for '{s.name}' ({s.exam_date}) must be after the plan start date ({self.start_date})."
                )
            if s.exam_date > latest_allowed:
                raise ValueError(
                    f"exam_date for '{s.name}' is more than {MAX_PLAN_DAYS} days away. Please plan closer to the exam."
                )

        # 4. One session must fit inside the daily study hours.
        if self.session_duration > self.available_hours_per_day * 60:
            raise ValueError("session_duration is longer than available_hours_per_day.")
        return self


# --------------------------------------------------------------------------- #
# Response
# --------------------------------------------------------------------------- #
class StudySession(BaseModel):
    id: str = Field(..., description="Unique id inside this plan, e.g. 'S012'. Use it to track completion.")
    date: dt.date
    day: str
    subject: str
    topic: str
    session_type: Literal["study", "revision"]
    start_time: str = Field(..., description="HH:MM")
    end_time: str = Field(..., description="HH:MM")
    duration: int = Field(..., description="Minutes")
    break_after: int = Field(..., description="Minutes of break after this session (0 for the last session of the day).")
    priority: Literal["High", "Medium", "Low"]
    status: Literal["pending", "completed"] = "pending"


class DayPlan(BaseModel):
    date: dt.date
    day: str
    total_minutes: int
    sessions: List[StudySession]


class WeekPlan(BaseModel):
    week_number: int
    week_start: dt.date = Field(..., description="Monday of this week")
    week_end: dt.date = Field(..., description="Sunday of this week")
    total_minutes: int
    total_sessions: int
    subject_minutes: Dict[str, int]
    days: List[DayPlan]


class SubjectSummary(BaseModel):
    subject: str
    exam_date: dt.date
    days_until_exam: int
    priority_score: float
    priority: Literal["High", "Medium", "Low"]
    study_sessions: int
    revision_sessions: int
    allocated_minutes: int
    recommended_minutes: int
    coverage_percent: int = Field(..., description="allocated / recommended, capped at 100")


class StudyPlan(BaseModel):
    start_date: dt.date
    end_date: dt.date
    total_study_minutes: int
    total_sessions: int
    sessions: List[StudySession]
    daily_timetable: List[DayPlan]
    weekly_timetable: List[WeekPlan]
    subject_summary: List[SubjectSummary]


class StudyPlanResponse(BaseModel):
    status: Literal["success"] = "success"
    plan: StudyPlan
    warnings: List[str] = Field(default_factory=list)
