"""
main.py - FastAPI application (the part your friend's frontend talks to).

Run locally:   uvicorn main:app --reload
Swagger UI:    http://127.0.0.1:8000/docs
"""
import logging
import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from scheduler import PlanningError, generate_study_plan
from schemas import StudyPlanRequest, StudyPlanResponse

logger = logging.getLogger("study_planner")

app = FastAPI(
    title="Smart Study Planner API",
    description="Generates a personalised, conflict-free study timetable from subjects, exam dates, "
                "difficulty, preparation level and available time.",
    version="1.0.0",
)

# --------------------------------------------------------------------------- #
# CORS - lets the frontend (running on another address) call this API.
# Set ALLOWED_ORIGINS to a comma-separated list in production, for example:
#   ALLOWED_ORIGINS=https://my-app.vercel.app,http://localhost:3000
# The default "*" allows every origin (fine for development / a college demo).
# --------------------------------------------------------------------------- #
origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,   # we use no cookies; keeps "*" valid
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Error handling - every error has the same simple shape:
#   {"status": "error", "message": "...", "errors": [{"field": "...", "message": "..."}]}
# --------------------------------------------------------------------------- #
@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    errors = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"] if p != "body") or "request"
        message = str(err["msg"]).removeprefix("Value error, ")
        errors.append({"field": field, "message": message})
    summary = "; ".join(f"{e['field']}: {e['message']}" for e in errors)
    return JSONResponse(status_code=422, content={"status": "error", "message": summary, "errors": errors})


@app.exception_handler(PlanningError)
async def planning_error_handler(request: Request, exc: PlanningError):
    return JSONResponse(status_code=422, content={"status": "error", "message": str(exc), "errors": []})


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    logger.exception("Unexpected error")
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "Something went wrong on the server.", "errors": []},
    )


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/health", tags=["System"])
def health():
    """Quick check that the service is running."""
    return {"status": "ok"}


@app.post("/generate-study-plan", response_model=StudyPlanResponse, tags=["Study Planner"])
def generate_plan(request: StudyPlanRequest):
    """Generate a complete study timetable (flat list, daily view and weekly view) from the student's inputs."""
    return generate_study_plan(request)
