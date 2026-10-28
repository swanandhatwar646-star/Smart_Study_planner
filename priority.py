"""
priority.py - subject priority maths.

Everything here is a small pure function (no FastAPI, no dates from the
system clock), so it is easy to read and easy to test.
All scores are on a 0-100 scale.
"""

# Easy / Medium / Hard labels are converted to numbers so the formula can use them.
DIFFICULTY_LABELS = {"easy": 30, "medium": 60, "hard": 90}

# Weights of the priority formula (they add up to 1.0).
W_DIFFICULTY = 0.4
W_NOT_PREPARED = 0.4
W_URGENCY = 0.2

# An exam this many days away (or more) has urgency 0.
# An exam tomorrow has urgency of about 97.
URGENCY_HORIZON_DAYS = 30

# Priority labels shown to the student.
HIGH_THRESHOLD = 65
MEDIUM_THRESHOLD = 40


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    """Keep a number between low and high."""
    return max(low, min(high, value))


def urgency_score(days_left: int) -> float:
    """
    0-100 score: the closer the exam, the higher the score.
    Linear: 100 on exam day, 0 when the exam is 30+ days away.
    """
    if days_left <= 0:
        return 100.0
    return clamp(100.0 * (1 - days_left / URGENCY_HORIZON_DAYS))


def priority_score(difficulty: float, preparation: float, days_left: int) -> float:
    """
    Priority = 0.4 x Difficulty + 0.4 x (100 - Preparation) + 0.2 x Urgency

    difficulty  : 0-100 (higher = harder)
    preparation : 0-100 (higher = better prepared)
    days_left   : days between "today" and the exam
    """
    score = (
        W_DIFFICULTY * clamp(difficulty)
        + W_NOT_PREPARED * (100 - clamp(preparation))
        + W_URGENCY * urgency_score(days_left)
    )
    return round(clamp(score), 2)


def priority_label(score: float) -> str:
    """Turn a 0-100 score into High / Medium / Low."""
    if score >= HIGH_THRESHOLD:
        return "High"
    if score >= MEDIUM_THRESHOLD:
        return "Medium"
    return "Low"


def recommended_minutes(topic_count: int, difficulty: float, preparation: float) -> int:
    """
    A rough estimate of how many minutes a subject SHOULD get in total.
    It is only used to warn the student when the available time looks too small.

    - 180 minutes (3 hours) per topic (5 topics are assumed if the student gave none)
    - harder subject      -> x0.5 (easy) up to x1.5 (very hard)
    - weaker preparation  -> x0.3 (well prepared) up to x1.0 (not prepared)
    """
    topics = topic_count if topic_count > 0 else 5
    difficulty_factor = 0.5 + clamp(difficulty) / 100
    gap_factor = 0.3 + 0.7 * (100 - clamp(preparation)) / 100
    return int(round(topics * 180 * difficulty_factor * gap_factor))
