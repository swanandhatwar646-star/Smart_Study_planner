"""
scheduler.py - the rule-based study-plan generator.

How it works (short version):
  1. Work out which days the student can study (selected weekdays, before the last exam).
  2. Work out how many sessions fit in one day (hours, session length, breaks).
  3. Fill every session slot, one at a time, choosing the subject with the highest
     accumulated "need" (a weighted round-robin driven by the priority score).
     Priority is recalculated every day, so a subject gets more time as its exam gets closer.
     A subject is never scheduled on or after its own exam date.
  4. The last ~20% of each subject's sessions become revision sessions.
  5. Spread the syllabus topics over the sessions.
  6. Give every session a start/end time. Times are computed one after another,
     so sessions can never overlap.
  7. Build the daily + weekly views and the warnings.
"""
import datetime as dt
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from priority import priority_label, priority_score, recommended_minutes
from schemas import (
    DayPlan, StudyPlan, StudyPlanRequest, StudyPlanResponse,
    StudySession, SubjectSummary, WeekPlan, WEEKDAY_NAMES,
)

MIN_WEIGHT = 5.0            # even a very easy, well-prepared subject keeps a small share of time
REVISION_SHARE = 0.20       # about 20% of a subject's sessions are revision
WARN_COVERAGE_BELOW = 0.80  # warn if scheduled time < 80% of the recommended time


class PlanningError(Exception):
    """Raised when a plan is impossible (the API returns it as a clean 422 error)."""


@dataclass
class _Subject:
    name: str
    difficulty: int
    preparation: float
    exam_date: dt.date
    topics: List[str]
    score: float = 0.0
    label: str = "Low"
    slots: List[tuple] = field(default_factory=list)  # (date, slot_index) in time order


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _sessions_per_day(avail_min: int, session: int, brk: int, start_min: int, warnings: List[str]) -> int:
    """How many (session + break) blocks fit in a day, without passing the daily hours or midnight."""
    by_hours = (avail_min + brk) // (session + brk)
    by_midnight = (1439 - start_min + brk) // (session + brk)  # last session must end before 24:00
    if by_midnight < 1 or by_hours < 1:
        raise PlanningError(
            "A single study session does not fit between the start time and midnight. "
            "Use an earlier study_start_time or a shorter session_duration."
        )
    if by_midnight < by_hours:
        warnings.append(
            f"Only {by_midnight} session(s) per day fit between {_hhmm(start_min)} and midnight, "
            f"so your daily hours cannot be fully used. Start earlier to use all {by_hours} session(s)."
        )
    return min(by_hours, by_midnight)


def _revision_count(n_sessions: int) -> int:
    """About 20% of a subject's sessions are revision; very small subjects get none."""
    if n_sessions < 3:
        return 0
    return max(1, int(n_sessions * REVISION_SHARE + 0.5))


def _spread_topics(topics: List[str], count: int) -> List[Optional[str]]:
    """
    Spread topics evenly over `count` sessions, in order.
      fewer sessions than topics -> several topics share a session  ("SQL, Transactions")
      more sessions than topics  -> a topic gets several sessions   ("SQL (part 1/2)")
      no topics                  -> None (caller uses a generic label)
    """
    if count == 0:
        return []
    t = len(topics)
    if t == 0:
        return [None] * count
    if count <= t:
        return [", ".join(topics[j * t // count:(j + 1) * t // count]) for j in range(count)]
    idx = [j * t // count for j in range(count)]
    totals, seen, out = Counter(idx), Counter(), []
    for i in idx:
        seen[i] += 1
        out.append(f"{topics[i]} (part {seen[i]}/{totals[i]})" if totals[i] > 1 else topics[i])
    return out


def _monday(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def generate_study_plan(req: StudyPlanRequest) -> StudyPlanResponse:
    warnings: List[str] = []
    start_date = req.start_date
    session, brk = req.session_duration, req.break_duration
    avail_min = int(round(req.available_hours_per_day * 60))
    start_min = req.study_start_time.hour * 60 + req.study_start_time.minute
    per_day = _sessions_per_day(avail_min, session, brk, start_min, warnings)

    subjects = [
        _Subject(s.name, int(s.difficulty), s.preparation, s.exam_date, s.topics) for s in req.subjects
    ]
    for s in subjects:
        s.score = priority_score(s.difficulty, s.preparation, (s.exam_date - start_date).days)
        s.label = priority_label(s.score)

    # ---- 1. Which days can the student study? (selected weekdays, strictly before the last exam)
    allowed = set(req.available_days)
    last_exam = max(s.exam_date for s in subjects)
    study_days: List[dt.date] = []
    day = start_date
    while day < last_exam:
        if WEEKDAY_NAMES[day.weekday()] in allowed:
            study_days.append(day)
        day += dt.timedelta(days=1)
    if not study_days:
        raise PlanningError(
            "None of the selected study days fall between the start date and the exam dates. "
            "Select more available_days."
        )

    # ---- 2. Fill every slot: weighted round-robin driven by daily priority
    credits: Dict[str, float] = {s.name: 0.0 for s in subjects}
    for day in study_days:
        active = [s for s in subjects if s.exam_date > day]  # never study after the exam
        if not active:
            continue
        weights = {
            s.name: max(priority_score(s.difficulty, s.preparation, (s.exam_date - day).days), MIN_WEIGHT)
            for s in active
        }
        total = sum(weights.values())
        for slot in range(per_day):
            for s in active:
                credits[s.name] += weights[s.name] / total
            chosen = max(active, key=lambda s: (credits[s.name], weights[s.name], -s.exam_date.toordinal()))
            credits[chosen.name] -= 1
            chosen.slots.append((day, slot))

    # ---- 3. Revision split + topic labels
    labelled: Dict[tuple, tuple] = {}  # (date, slot) -> (subject, topic, session_type)
    summaries: List[SubjectSummary] = []
    for s in subjects:
        n = len(s.slots)
        rev = _revision_count(n)
        study_labels = _spread_topics(s.topics, n - rev)
        rev_labels = _spread_topics(s.topics, rev)
        for i, key in enumerate(s.slots):
            if i < n - rev:
                labelled[key] = (s, study_labels[i] or "General study", "study")
            else:
                text = rev_labels[i - (n - rev)]
                labelled[key] = (s, f"Revision: {text}" if text else "Full syllabus revision", "revision")

        allocated = n * session
        recommended = recommended_minutes(len(s.topics), s.difficulty, s.preparation)
        coverage = min(100, int(round(100 * allocated / recommended))) if recommended else 100
        days_left = (s.exam_date - start_date).days
        summaries.append(SubjectSummary(
            subject=s.name, exam_date=s.exam_date, days_until_exam=days_left,
            priority_score=s.score, priority=s.label,
            study_sessions=n - rev, revision_sessions=rev,
            allocated_minutes=allocated, recommended_minutes=recommended, coverage_percent=coverage,
        ))
        if n == 0:
            warnings.append(
                f"No study time could be scheduled for {s.name} before its exam on {s.exam_date}. "
                "Add more study days or hours."
            )
        elif allocated < WARN_COVERAGE_BELOW * recommended:
            warnings.append(
                f"Limited time for {s.name}: {allocated} min scheduled vs about {recommended} min recommended "
                f"({coverage}%). Consider adding study days or hours."
            )

    # ---- 4. Give every session real clock times (one after another -> no overlaps)
    sessions: List[StudySession] = []
    for number, key in enumerate(sorted(labelled), start=1):
        day, slot = key
        s, topic, kind = labelled[key]
        begin = start_min + slot * (session + brk)
        sessions.append(StudySession(
            id=f"S{number:03d}", date=day, day=WEEKDAY_NAMES[day.weekday()],
            subject=s.name, topic=topic, session_type=kind,
            start_time=_hhmm(begin), end_time=_hhmm(begin + session),
            duration=session, break_after=brk if slot < per_day - 1 else 0,
            priority=s.label,
        ))

    # ---- 5. Daily and weekly views
    by_day: Dict[dt.date, List[StudySession]] = defaultdict(list)
    for item in sessions:
        by_day[item.date].append(item)
    daily = [
        DayPlan(date=d, day=WEEKDAY_NAMES[d.weekday()], total_minutes=sum(x.duration for x in items), sessions=items)
        for d, items in sorted(by_day.items())
    ]

    by_week: Dict[dt.date, List[DayPlan]] = defaultdict(list)
    for d in daily:
        by_week[_monday(d.date)].append(d)
    weekly = []
    for number, (monday, days) in enumerate(sorted(by_week.items()), start=1):
        minutes: Dict[str, int] = defaultdict(int)
        for d in days:
            for item in d.sessions:
                minutes[item.subject] += item.duration
        weekly.append(WeekPlan(
            week_number=number, week_start=monday, week_end=monday + dt.timedelta(days=6),
            total_minutes=sum(d.total_minutes for d in days),
            total_sessions=sum(len(d.sessions) for d in days),
            subject_minutes=dict(minutes), days=days,
        ))

    plan = StudyPlan(
        start_date=daily[0].date, end_date=daily[-1].date,
        total_study_minutes=sum(x.duration for x in sessions), total_sessions=len(sessions),
        sessions=sessions, daily_timetable=daily, weekly_timetable=weekly, subject_summary=summaries,
    )
    return StudyPlanResponse(status="success", plan=plan, warnings=warnings)
