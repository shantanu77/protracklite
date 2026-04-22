from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import smtplib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from email.message import EmailMessage
from typing import Any

import bleach
import httpx
from fastapi import Body, Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, func, inspect, or_, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import Base, engine, get_db
from app.models import (
    ActivityType,
    Holiday,
    Leave,
    LeaveType,
    Organization,
    OrgSettings,
    Project,
    Role,
    Task,
    TaskStatus,
    TimeLog,
    User,
)
from app.reports import compute_work_rate, current_week_bounds, monday_report, previous_week_bounds, reports_overview
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_temp_password,
    hash_password,
    verify_password,
)
from app.seed import seed_defaults


settings = get_settings()
app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
logger = logging.getLogger(__name__)

SAFE_TAGS = ["p", "b", "strong", "i", "em", "ul", "ol", "li", "br", "a", "code", "pre"]
AUTH_REDIRECT_ERRORS = {
    "Authentication required",
    "Invalid token",
    "Malformed token",
    "Inactive user",
    "Organization mismatch",
}
ACTIVITY_CATEGORY_CHOICES = [
    ("software_development", "Software Development"),
    ("project_delivery_management", "Project / Delivery Management"),
    ("product_management", "Product Management"),
    ("it_tasks", "IT Tasks"),
    ("infra_management", "Infra Management"),
    ("people_management", "People Management"),
    ("others", "Others"),
]
ACTIVITY_CATEGORY_LABELS = dict(ACTIVITY_CATEGORY_CHOICES)
DEFAULT_TASK_COLOR = "#22c55e"
TASK_COLOR_CHOICES = [
    ("#22c55e", "Green"),
    ("#16a34a", "Forest"),
    ("#65a30d", "Lime"),
    ("#84cc16", "Citron"),
    ("#eab308", "Amber"),
    ("#f59e0b", "Gold"),
    ("#f97316", "Orange"),
    ("#ea580c", "Burnt Orange"),
    ("#ef4444", "Red"),
    ("#dc2626", "Crimson"),
    ("#ec4899", "Pink"),
    ("#db2777", "Rose"),
    ("#a855f7", "Violet"),
    ("#7c3aed", "Indigo"),
    ("#6366f1", "Iris"),
    ("#2563eb", "Blue"),
    ("#0ea5e9", "Sky"),
    ("#06b6d4", "Cyan"),
    ("#14b8a6", "Teal"),
    ("#10b981", "Mint"),
    ("#64748b", "Slate"),
    ("#475569", "Steel"),
    ("#78716c", "Stone"),
    ("#a16207", "Ochre"),
]
TASK_COLOR_MAP = {color: label for color, label in TASK_COLOR_CHOICES}
TASK_COLOR_VALUES = set(TASK_COLOR_MAP)
templates.env.globals["task_color_choices"] = TASK_COLOR_CHOICES
templates.env.globals["default_task_color"] = DEFAULT_TASK_COLOR


def infer_activity_category(code: str, name: str) -> str:
    token = f"{code} {name}".lower()
    if any(word in token for word in ["dev", "test", "qa", "bug", "code review", "design"]):
        return "software_development"
    if any(word in token for word in ["plan", "demo", "documentation", "specification"]):
        return "project_delivery_management"
    if any(word in token for word in ["product"]):
        return "product_management"
    if any(word in token for word in ["support", "helpdesk", "admin"]):
        return "it_tasks"
    if any(word in token for word in ["deploy", "devops", "infra"]):
        return "infra_management"
    if any(word in token for word in ["training", "performance", "process review", "people"]):
        return "people_management"
    return "others"


def normalize_task_color(raw_color: str | None) -> str:
    color = str(raw_color or "").strip().lower()
    return color if color in TASK_COLOR_VALUES else DEFAULT_TASK_COLOR


def parse_task_tags(raw_value: str | None) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    for raw_tag in re.split(r"[,;\n]+", raw_value or ""):
        tag = re.sub(r"\s+", " ", raw_tag).strip().strip("#")
        tag = re.sub(r"[^\w /&+\-.]", "", tag)
        normalized = tag.lower().strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        tags.append(normalized[:40])
    return tags[:20]


def serialize_task_tags(tags: list[str]) -> str:
    return ", ".join(parse_task_tags(", ".join(tags)))


def task_tags(task: Task) -> list[str]:
    return parse_task_tags(task.tags_text)


def task_tags_text(task: Task) -> str:
    return " ".join(task_tags(task))

def ensure_org_settings_schema() -> None:
    inspector = inspect(engine)
    if "org_settings" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("org_settings")}
    ddl_by_column = {
        "default_project_id": "ALTER TABLE org_settings ADD COLUMN default_project_id INTEGER NULL",
        "default_activity_type_id": "ALTER TABLE org_settings ADD COLUMN default_activity_type_id INTEGER NULL",
        "default_task_status": "ALTER TABLE org_settings ADD COLUMN default_task_status VARCHAR(30) NOT NULL DEFAULT 'not_started'",
        "default_estimated_hours": "ALTER TABLE org_settings ADD COLUMN default_estimated_hours NUMERIC(5, 2) NULL",
        "default_time_log_hours": "ALTER TABLE org_settings ADD COLUMN default_time_log_hours NUMERIC(4, 2) NULL",
    }
    with engine.begin() as connection:
        for column_name, ddl in ddl_by_column.items():
            if column_name not in columns:
                connection.execute(text(ddl))


def ensure_tasks_schema() -> None:
    inspector = inspect(engine)
    if "tasks" not in inspector.get_table_names():
        return
    task_columns = {column["name"]: column for column in inspector.get_columns("tasks")}
    columns = set(task_columns)
    ddl_by_column = {
        "stalled_reason": "ALTER TABLE tasks ADD COLUMN stalled_reason VARCHAR(500) NOT NULL DEFAULT ''",
        "is_archived": "ALTER TABLE tasks ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT FALSE",
        "dashboard_rank": "ALTER TABLE tasks ADD COLUMN dashboard_rank INTEGER NOT NULL DEFAULT 0",
        "task_color": f"ALTER TABLE tasks ADD COLUMN task_color VARCHAR(7) NOT NULL DEFAULT '{DEFAULT_TASK_COLOR}'",
        "tags_text": "ALTER TABLE tasks ADD COLUMN tags_text TEXT NOT NULL DEFAULT ''",
    }
    with engine.begin() as connection:
        for column_name, ddl in ddl_by_column.items():
            if column_name not in columns:
                connection.execute(text(ddl))
        start_date_column = task_columns.get("start_date")
        if start_date_column and not start_date_column.get("nullable", True) and engine.dialect.name == "mysql":
            connection.execute(text("ALTER TABLE tasks MODIFY COLUMN start_date DATE NULL"))
        if start_date_column and not start_date_column.get("nullable", True) and engine.dialect.name == "sqlite":
            migrate_sqlite_tasks_table(connection)


def migrate_sqlite_tasks_table(connection) -> None:
    connection.execute(text("PRAGMA foreign_keys=OFF"))
    connection.execute(text("ALTER TABLE tasks RENAME TO tasks__old"))
    connection.execute(
        text(
            """
            CREATE TABLE tasks (
                id INTEGER NOT NULL PRIMARY KEY,
                task_id VARCHAR(20) NOT NULL,
                org_id INTEGER NOT NULL,
                project_id INTEGER NOT NULL,
                assigned_to INTEGER NOT NULL,
                created_by INTEGER NOT NULL,
                name VARCHAR(300) NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                activity_type_id INTEGER NOT NULL,
                status VARCHAR(30) NOT NULL,
                task_color VARCHAR(7) NOT NULL DEFAULT '#22c55e',
                tags_text TEXT NOT NULL DEFAULT '',
                is_private BOOLEAN NOT NULL DEFAULT FALSE,
                is_archived BOOLEAN NOT NULL DEFAULT FALSE,
                dashboard_rank INTEGER NOT NULL DEFAULT 0,
                start_date DATE NULL,
                end_date DATE NULL,
                estimated_hours NUMERIC(5, 2) NULL,
                logged_hours NUMERIC(6, 2) NOT NULL DEFAULT 0,
                stalled_reason VARCHAR(500) NOT NULL DEFAULT '',
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                closed_at DATETIME NULL,
                FOREIGN KEY(org_id) REFERENCES organizations (id),
                FOREIGN KEY(project_id) REFERENCES projects (id),
                FOREIGN KEY(assigned_to) REFERENCES users (id),
                FOREIGN KEY(created_by) REFERENCES users (id),
                FOREIGN KEY(activity_type_id) REFERENCES activity_types (id)
            )
            """
        )
    )
    connection.execute(
        text(
            """
            INSERT INTO tasks (
                id, task_id, org_id, project_id, assigned_to, created_by, name, description, activity_type_id,
                status, task_color, tags_text, is_private, is_archived, dashboard_rank, start_date, end_date, estimated_hours,
                logged_hours, stalled_reason, created_at, updated_at, closed_at
            )
            SELECT
                id, task_id, org_id, project_id, assigned_to, created_by, name, description, activity_type_id,
                status, COALESCE(task_color, '#22c55e'), COALESCE(tags_text, ''), is_private, COALESCE(is_archived, FALSE), COALESCE(dashboard_rank, 0), start_date, end_date, estimated_hours,
                COALESCE(logged_hours, 0), COALESCE(stalled_reason, ''), created_at, updated_at, closed_at
            FROM tasks__old
            """
        )
    )
    connection.execute(text("DROP TABLE tasks__old"))
    connection.execute(text("CREATE UNIQUE INDEX ix_tasks_task_id ON tasks (task_id)"))
    connection.execute(text("CREATE INDEX ix_tasks_org_id ON tasks (org_id)"))
    connection.execute(text("CREATE INDEX ix_tasks_assigned_to ON tasks (assigned_to)"))
    connection.execute(text("PRAGMA foreign_keys=ON"))


def ensure_activity_types_schema() -> None:
    inspector = inspect(engine)
    if "activity_types" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("activity_types")}
    ddl_by_column = {
        "category": "ALTER TABLE activity_types ADD COLUMN category VARCHAR(80) NOT NULL DEFAULT 'others'",
    }
    with engine.begin() as connection:
        for column_name, ddl in ddl_by_column.items():
            if column_name not in columns:
                connection.execute(text(ddl))


def ensure_query_indexes() -> None:
    inspector = inspect(engine)
    index_plan = {
        "tasks": {
            "ix_tasks_org_assignee_archived_rank_start_created": (
                "CREATE INDEX ix_tasks_org_assignee_archived_rank_start_created "
                "ON tasks (org_id, assigned_to, is_archived, dashboard_rank, start_date, created_at)"
            ),
            "ix_tasks_org_assignee_archived_closedat": (
                "CREATE INDEX ix_tasks_org_assignee_archived_closedat "
                "ON tasks (org_id, assigned_to, is_archived, closed_at)"
            ),
            "ix_tasks_org_assignee_archived_status_start": (
                "CREATE INDEX ix_tasks_org_assignee_archived_status_start "
                "ON tasks (org_id, assigned_to, is_archived, status, start_date)"
            ),
            "ix_tasks_org_assignee_archived_status_closed": (
                "CREATE INDEX ix_tasks_org_assignee_archived_status_closed "
                "ON tasks (org_id, assigned_to, is_archived, status, closed_at)"
            ),
            "ix_tasks_org_assignee_archived_end": (
                "CREATE INDEX ix_tasks_org_assignee_archived_end "
                "ON tasks (org_id, assigned_to, is_archived, end_date)"
            ),
            "ix_tasks_org_archived_created": (
                "CREATE INDEX ix_tasks_org_archived_created "
                "ON tasks (org_id, is_archived, created_at)"
            ),
        },
        "time_logs": {
            "ix_time_logs_user_log_date": "CREATE INDEX ix_time_logs_user_log_date ON time_logs (user_id, log_date)",
            "ix_time_logs_task_log_date": "CREATE INDEX ix_time_logs_task_log_date ON time_logs (task_id, log_date)",
        },
    }
    with engine.begin() as connection:
        for table_name, statements in index_plan.items():
            if table_name not in inspector.get_table_names():
                continue
            existing_indexes = {item["name"] for item in inspector.get_indexes(table_name)}
            for index_name, ddl in statements.items():
                if index_name not in existing_indexes:
                    connection.execute(text(ddl))


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_org_settings_schema()
    ensure_tasks_schema()
    ensure_activity_types_schema()
    ensure_query_indexes()
    db = next(get_db())
    try:
        seed_defaults(db)
        backfill_activity_type_categories(db)
    finally:
        db.close()


def send_email(recipient: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_username:
            server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


def build_forgot_password_captcha(org_slug: str) -> dict[str, str | int]:
    left = secrets.randbelow(8) + 2
    right = secrets.randbelow(8) + 1
    issued_at = int(datetime.now(UTC).timestamp())
    payload = f"{org_slug}:{left}:{right}:{issued_at}"
    signature = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return {
        "captcha_left": left,
        "captcha_right": right,
        "captcha_issued_at": issued_at,
        "captcha_signature": signature,
    }


def verify_forgot_password_captcha(
    org_slug: str,
    answer: str,
    left: str,
    right: str,
    issued_at: str,
    signature: str,
) -> bool:
    if not all([answer, left, right, issued_at, signature]):
        return False
    try:
        left_value = int(left)
        right_value = int(right)
        issued_at_value = int(issued_at)
        answer_value = int(answer)
    except ValueError:
        return False

    age = int(datetime.now(UTC).timestamp()) - issued_at_value
    if age < 0 or age > 600:
        return False

    payload = f"{org_slug}:{left_value}:{right_value}:{issued_at_value}"
    expected_signature = hmac.new(settings.secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return False

    return answer_value == left_value + right_value


def issue_temporary_password(user: User) -> str:
    temp_password = generate_temp_password()
    user.password_hash = hash_password(temp_password)
    user.force_password_change = True
    user.temp_password_expires = datetime.utcnow() + timedelta(hours=24)
    return temp_password


def render_login(
    request: Request,
    org: Organization,
    *,
    status_code: int = 200,
    error: str | None = None,
    forgot_error: str | None = None,
    forgot_success: str | None = None,
):
    context = {
        "request": request,
        "org": org,
        "error": error,
        "forgot_error": forgot_error,
        "forgot_success": forgot_success,
        **build_forgot_password_captcha(org.slug),
    }
    return templates.TemplateResponse("login.html", context, status_code=status_code)


def get_org_or_404(db: Session, org_slug: str) -> Organization:
    org = db.scalar(select(Organization).where(Organization.slug == org_slug, Organization.is_active.is_(True)))
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


def issue_auth_cookies(response: RedirectResponse | JSONResponse, user: User, org_slug: str) -> None:
    subject = f"{user.id}:{org_slug}"
    access_cookie_age = settings.access_token_ttl_minutes * 60
    refresh_cookie_age = settings.refresh_token_ttl_days * 24 * 60 * 60
    response.set_cookie(
        "access_token",
        create_access_token(subject),
        httponly=True,
        samesite="lax",
        max_age=access_cookie_age,
    )
    response.set_cookie(
        "refresh_token",
        create_refresh_token(subject),
        httponly=True,
        samesite="lax",
        max_age=refresh_cookie_age,
    )


def clear_auth_cookies(response: RedirectResponse | JSONResponse) -> None:
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")


def is_browser_page_request(request: Request) -> bool:
    if request.url.path.startswith("/api/"):
        return False
    accept = request.headers.get("accept", "")
    return "text/html" in accept or "*/*" in accept


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code in {status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN} and exc.detail in AUTH_REDIRECT_ERRORS:
        if is_browser_page_request(request):
            response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
            clear_auth_cookies(response)
            return response
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    subject = decode_token(token, "access")
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if ":" not in subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token")
    user_id_str, org_slug = subject.split(":", 1)
    request.state.org_slug = org_slug
    user = db.get(User, int(user_id_str))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inactive user")
    return user


def get_org_user(
    request: Request,
    org_slug: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> tuple[Organization, User]:
    resolved_slug = org_slug or getattr(request.state, "org_slug", None)
    if not resolved_slug:
        raise HTTPException(status_code=400, detail="Organization context missing")
    org = get_org_or_404(db, resolved_slug)
    if user.org_id != org.id or request.state.org_slug != resolved_slug:
        raise HTTPException(status_code=403, detail="Organization mismatch")
    return org, user


def must_be_admin(user: User) -> None:
    if user.role != Role.ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")


def next_task_id(project: Project) -> str:
    project.project_task_sequence += 1
    return f"{project.code}{project.project_task_sequence:04d}"


def sanitize_html(raw_html: str) -> str:
    return bleach.clean(raw_html or "", tags=SAFE_TAGS, strip=True)


def escape_ical_text(value: str) -> str:
    return (
        (value or "")
        .replace("\\", "\\\\")
        .replace(";", r"\;")
        .replace(",", r"\,")
        .replace("\r\n", r"\n")
        .replace("\n", r"\n")
    )


def backfill_activity_type_categories(db: Session) -> None:
    updated = False
    items = db.scalars(select(ActivityType)).all()
    for item in items:
        current = (item.category or "").strip()
        if not current or current not in ACTIVITY_CATEGORY_LABELS:
            item.category = infer_activity_category(item.code, item.name)
            updated = True
    if updated:
        db.commit()


def build_task_ical(task: Task, org: Organization) -> str:
    if not task.start_date:
        raise HTTPException(status_code=400, detail="Backlog tasks without a schedule cannot be exported to calendar")
    start_date = task.start_date.strftime("%Y%m%d")
    end_source = task.end_date or task.start_date
    end_date = (end_source + timedelta(days=1)).strftime("%Y%m%d")
    stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    summary = escape_ical_text(f"{task.task_id} {task.name}")
    description_bits = [f"Organization: {org.name}", f"Task ID: {task.task_id}", f"Status: {task.status.value}"]
    if task.description:
        description_bits.append(bleach.clean(task.description, tags=[], strip=True))
    description = escape_ical_text("\n".join(description_bits))
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//ProtrackLite//Tasks//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "BEGIN:VEVENT",
            f"UID:task-{task.id}@{org.slug}.protracklite",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{start_date}",
            f"DTEND;VALUE=DATE:{end_date}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{description}",
            "STATUS:CONFIRMED",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )


def dashboard_task_summary(task: Task, today: date) -> dict[str, Any]:
    tags = task_tags(task)
    color = normalize_task_color(task.task_color)
    overdue_days = None
    deadline_label = "No deadline"
    deadline_tone = "muted"
    completion_delay_days = None
    completion_delay_label = ""
    status_label = task.status.value.replace("_", " ")
    status_tone = "warning"
    status_icon = "○"
    if task.status == TaskStatus.STARTED:
        status_tone = "success"
        status_icon = "▶"
    elif task.status == TaskStatus.CLOSED:
        status_tone = "success"
        status_icon = "✓"
    elif task.status == TaskStatus.STALLED:
        status_tone = "danger"
        status_icon = "⏸"

    if task.end_date:
        day_delta = (task.end_date - today).days
        if day_delta < 0 and task.status != TaskStatus.CLOSED:
            overdue_days = abs(day_delta)
            deadline_label = f"Overdue by {overdue_days} day{'s' if overdue_days != 1 else ''}"
            deadline_tone = "late"
        elif day_delta == 0:
            deadline_label = "Due today"
            deadline_tone = "due"
        else:
            deadline_label = f"{day_delta} day{'s' if day_delta != 1 else ''} remaining"
            deadline_tone = "upcoming"
    if task.status == TaskStatus.CLOSED and task.closed_at and task.end_date:
        completion_delay_days = (task.closed_at.date() - task.end_date).days
        if completion_delay_days > 0:
            completion_delay_label = f"Closed late by {completion_delay_days} day{'s' if completion_delay_days != 1 else ''}"
        elif completion_delay_days < 0:
            completion_delay_label = f"Closed {abs(completion_delay_days)} day{'s' if abs(completion_delay_days) != 1 else ''} early"
        else:
            completion_delay_label = "Closed on time"

    return {
        "id": task.id,
        "task_id": task.task_id,
        "name": task.name,
        "description": bleach.clean(task.description or "", tags=[], strip=True),
        "created_at": task.created_at,
        "status": task.status.value,
        "task_color": color,
        "task_color_label": TASK_COLOR_MAP.get(color, "Green"),
        "tags": tags,
        "tags_text": ", ".join(tags),
        "start_date": task.start_date,
        "end_date": task.end_date,
        "logged_hours": task.logged_hours,
        "estimated_hours": task.estimated_hours,
        "stalled_reason": task.stalled_reason,
        "deadline_label": deadline_label,
        "deadline_tone": deadline_tone,
        "overdue_days": overdue_days,
        "status_label": status_label,
        "status_tone": status_tone,
        "status_icon": status_icon,
        "is_backlog": task.start_date is None and task.end_date is None,
        "completion_delay_days": completion_delay_days,
        "completion_delay_label": completion_delay_label,
        "completion_min_date": task.start_date or task.created_at.date(),
        "completion_max_date": today,
    }


def next_named_weekday(target_weekday: int) -> date:
    today = date.today()
    days_ahead = (target_weekday - today.weekday()) % 7
    return today + timedelta(days=days_ahead)


def next_week_named_weekday(target_weekday: int) -> date:
    today = date.today()
    days_ahead = (target_weekday - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return today + timedelta(days=days_ahead + 7)


def parse_human_date(raw_value: str | None) -> date | None:
    value = (raw_value or "").strip().lower()
    if not value:
        return None
    value = re.sub(r"^(on|by|due|from|starting|start|ending|end|until|till|for)\s+", "", value).strip()
    try:
        return date.fromisoformat(value)
    except ValueError:
        pass

    if value == "today":
        return date.today()
    if value == "tomorrow":
        return date.today() + timedelta(days=1)
    if value == "this week":
        return date.today()
    if value == "next week":
        return date.today() + timedelta(days=7)

    weekday_map = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    relative_weekday_match = re.fullmatch(r"(this|next)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", value)
    if relative_weekday_match:
        week_scope, weekday_name = relative_weekday_match.groups()
        weekday_number = weekday_map[weekday_name]
        if week_scope == "next":
            return next_week_named_weekday(weekday_number)
        return next_named_weekday(weekday_number)
    if value in weekday_map:
        return next_named_weekday(weekday_map[value])

    slash_match = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", value)
    if slash_match:
        day_value = int(slash_match.group(1))
        month_value = int(slash_match.group(2))
        year_value = slash_match.group(3)
        target_year = int(year_value) if year_value else date.today().year
        if target_year < 100:
            target_year += 2000
        try:
            return date(target_year, month_value, day_value)
        except ValueError:
            return None

    named_month_match = re.fullmatch(r"(\d{1,2})[- /]([a-z]{3,9})(?:[- /](\d{2,4}))?", value)
    if named_month_match:
        month_map = {
            "jan": 1,
            "january": 1,
            "feb": 2,
            "february": 2,
            "mar": 3,
            "march": 3,
            "apr": 4,
            "april": 4,
            "may": 5,
            "jun": 6,
            "june": 6,
            "jul": 7,
            "july": 7,
            "aug": 8,
            "august": 8,
            "sep": 9,
            "sept": 9,
            "september": 9,
            "oct": 10,
            "october": 10,
            "nov": 11,
            "november": 11,
            "dec": 12,
            "december": 12,
        }
        month_value = month_map.get(named_month_match.group(2))
        if month_value:
            day_value = int(named_month_match.group(1))
            year_value = named_month_match.group(3)
            target_year = int(year_value) if year_value else date.today().year
            if target_year < 100:
                target_year += 2000
            try:
                return date(target_year, month_value, day_value)
            except ValueError:
                return None
    return None


def parse_optional_date(raw_value: str | None) -> date | None:
    return parse_human_date(raw_value)


def parse_optional_decimal(raw_value: str | None) -> Decimal | None:
    value = (raw_value or "").strip()
    return Decimal(value) if value else None


def parse_json_payload(raw_content: str) -> dict[str, Any]:
    content = (raw_content or "").strip()
    if content.startswith("```"):
        parts = content.split("```")
        content = next((part for part in parts if "{" in part or "[" in part), content).strip()
        if content.startswith("json"):
            content = content[4:].strip()
    return json.loads(content)


def extract_task_dates_from_line(line: str) -> tuple[date | None, date | None]:
    lower_line = line.lower()
    start_patterns = [
        r"\bstart(?:ing)?(?: on)?[: ]+([a-z0-9/\- ]+?)(?=\s+\b(?:end|due|by|effort|hrs?|hours?)\b|,|$)",
        r"\bfrom[: ]+([a-z0-9/\- ]+?)(?=\s+\b(?:to|till|until|end|due|by|effort|hrs?|hours?)\b|,|$)",
        r"\b(?:on|starting)\s+((?:this|next)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)|today|tomorrow)\b",
    ]
    end_patterns = [
        r"\bend(?:ing)?(?: on)?[: ]+([a-z0-9/\- ]+?)(?=\s+\b(?:start|from|effort|hrs?|hours?)\b|,|$)",
        r"\bdue(?: on)?[: ]+([a-z0-9/\- ]+?)(?=\s+\b(?:start|from|effort|hrs?|hours?)\b|,|$)",
        r"\bby[: ]+([a-z0-9/\- ]+?)(?=\s+\b(?:start|from|effort|hrs?|hours?)\b|,|$)",
        r"\b(?:by|due|for|until|till)\s+((?:this|next)\s+(?:week|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    ]
    start_date = None
    end_date = None
    for pattern in start_patterns:
        match = re.search(pattern, lower_line)
        if match:
            start_date = parse_human_date(match.group(1).strip())
            if start_date:
                break
    for pattern in end_patterns:
        match = re.search(pattern, lower_line)
        if match:
            end_date = parse_human_date(match.group(1).strip())
            if end_date:
                break

    if not start_date or not end_date:
        generic_dates = []
        for raw_date in re.findall(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", lower_line):
            parsed_date = parse_human_date(raw_date)
            if parsed_date:
                generic_dates.append(parsed_date)
        if not start_date and generic_dates:
            start_date = generic_dates[0]
        if not end_date and len(generic_dates) >= 2:
            end_date = generic_dates[1]
        elif not end_date and len(generic_dates) == 1 and re.search(r"\b(due|end|by)\b", lower_line):
            end_date = generic_dates[0]
            start_date = None
    return start_date, end_date


def extract_task_effort_from_line(line: str) -> Decimal | None:
    match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\b", line.lower())
    if not match:
        return None
    try:
        return Decimal(match.group(1))
    except Exception:
        return None


def extract_task_title_from_line(line: str) -> str:
    title = re.sub(r"\b(start(?:ing)?|from|end(?:ing)?|due|by|effort)\b[: ]+[a-z0-9/\- ]+", "", line, flags=re.IGNORECASE)
    title = re.sub(r"\b\d+(?:\.\d+)?\s*(?:h|hr|hrs|hour|hours)\b", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", "", title)
    title = re.sub(r"\s+", " ", title).strip(" -,:;")
    return (title or line.strip())[:300]


def extract_bulk_tasks_locally(task_lines: list[str]) -> list[dict[str, Any]]:
    parsed_tasks: list[dict[str, Any]] = []
    for line in task_lines:
        start_date, end_date = extract_task_dates_from_line(line)
        parsed_tasks.append(
            {
                "title": extract_task_title_from_line(line),
                "description": line.strip(),
                "start_date": start_date,
                "end_date": end_date,
                "estimated_hours": extract_task_effort_from_line(line),
            }
        )
    return parsed_tasks


def enrich_task_fields_from_text(title: str, description: str) -> dict[str, Any]:
    source_text = " ".join(part.strip() for part in [title, description] if part and part.strip())
    start_date, end_date = extract_task_dates_from_line(source_text)
    return {
        "start_date": start_date,
        "end_date": end_date,
        "estimated_hours": extract_task_effort_from_line(source_text),
    }


def normalize_ai_boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def split_freeflow_task_input(raw_content: str) -> list[str]:
    chunks: list[str] = []
    for block in re.split(r"\n\s*\n+", raw_content):
        block = block.strip()
        if not block:
            continue
        raw_lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        block_lines = [line.strip(" -*\t[]") for line in raw_lines]
        is_explicit_list = len(raw_lines) > 1 and all(
            re.match(r"^\s*(?:\[[ xX]?\]|\(?\d+[.)]|[-*•])\s+", line) for line in raw_lines
        )
        if is_explicit_list:
            chunks.extend(block_lines)
        elif len(block_lines) > 1 and all(len(line.split()) <= 20 for line in block_lines):
            chunks.extend(block_lines)
        else:
            chunks.append(" ".join(block_lines))
    return [chunk[:2000] for chunk in chunks if chunk]


def resolve_default_task_targets(db: Session, org_id: int) -> tuple[Project, ActivityType]:
    settings_obj = get_org_settings(db, org_id)
    project = db.get(Project, settings_obj.default_project_id) if settings_obj.default_project_id else None
    activity = db.get(ActivityType, settings_obj.default_activity_type_id) if settings_obj.default_activity_type_id else None
    if not project or project.org_id != org_id or not project.is_active:
        project = db.scalar(select(Project).where(Project.org_id == org_id, Project.is_active.is_(True)).order_by(Project.name.asc()))
    if not activity or activity.org_id != org_id or not activity.is_active:
        activity = db.scalar(
            select(ActivityType).where(ActivityType.org_id == org_id, ActivityType.is_active.is_(True)).order_by(ActivityType.name.asc())
        )
    if not project or not activity:
        raise HTTPException(status_code=400, detail="A default project and activity type are required for AI backlog import")
    return project, activity


def select_activity_type_for_ai_task(
    activity_types: list[ActivityType],
    default_activity_type: ActivityType,
    category: str | None,
) -> ActivityType:
    normalized_category = (category or "").strip()
    if normalized_category in ACTIVITY_CATEGORY_LABELS:
        category_matches = [item for item in activity_types if item.category == normalized_category]
        if default_activity_type in category_matches:
            return default_activity_type
        if category_matches:
            return category_matches[0]
    return default_activity_type


def extract_bulk_tasks_with_openai(raw_content: str) -> list[dict[str, Any]]:
    task_lines = split_freeflow_task_input(raw_content)
    if not task_lines:
        return []
    if not settings.openai_api_key:
        logger.warning("Bulk backlog AI fallback: OPENAI_API_KEY is not configured")
        return extract_bulk_tasks_locally(task_lines)
    payload = {
        "model": settings.openai_backlog_model,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an expert task extraction engine for a work tracker. "
                    "Convert free-form emails, meeting notes, chats, and bullet lists into a JSON object with key \"tasks\". "
                    "Return JSON only. Do not include markdown fences or explanatory text. "
                    "Each task object must use this shape exactly: "
                    "{\"title\":\"...\",\"description\":\"...\",\"start_date\":\"YYYY-MM-DD or null\",\"end_date\":\"YYYY-MM-DD or null\","
                    "\"estimated_hours\":number or null,\"category\":\"software_development|project_delivery_management|product_management|it_tasks|infra_management|people_management|others\","
                    "\"status\":\"not_started|started|stalled|closed\",\"is_backlog\":boolean,\"stalled_reason\":\"string or empty\"}. "
                    "Extract every actionable task. Split multiple asks into separate tasks. Ignore greetings, signatures, and non-actionable chatter. "
                    "Rewrite title and description to be concise, professional, and directly actionable. "
                    "Prefer specific dates when the text implies them. Resolve phrases like today, tomorrow, this week, next week, Monday, Friday, by Wednesday, and similar scheduling language into dates. "
                    "If the source indicates a due date but no start date, keep start_date null and set end_date. "
                    "Estimate effort only when the text gives a clear signal or a reasonable small-task inference; otherwise null. "
                    "Set category to the best matching value from the allowed list. "
                    "Set status to not_started unless the source clearly says work has begun, is stalled, or is completed. "
                    "Set is_backlog true only when there is no reliable schedule and no reliable effort estimate. Otherwise set it false. "
                    "If status is stalled, include a short stalled_reason; otherwise use an empty string."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Extract actionable tasks from the following content and return the JSON object only.\n"
                    f"{raw_content.strip()}\n"
                    "Use null for unknown dates or effort. Use only the allowed category and status values."
                ),
            },
        ],
    }
    try:
        with httpx.Client(timeout=45.0) as client:
            response = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        response.raise_for_status()
        data = response.json()
        raw_content = data["choices"][0]["message"]["content"]
        parsed = parse_json_payload(raw_content)
        tasks = parsed.get("tasks", [])
        normalized_tasks = []
        for item in tasks:
            title = str(item.get("title") or "").strip()[:300]
            description = str(item.get("description") or "").strip()
            if not title:
                continue
            inferred = enrich_task_fields_from_text(title, description)
            start_date = parse_optional_date(str(item.get("start_date") or "")) or inferred["start_date"]
            end_date = parse_optional_date(str(item.get("end_date") or "")) or inferred["end_date"]
            estimated_hours = parse_optional_decimal(str(item.get("estimated_hours") or "")) or inferred["estimated_hours"]
            category = str(item.get("category") or "others").strip()
            status = str(item.get("status") or TaskStatus.NOT_STARTED.value).strip()
            stalled_reason = str(item.get("stalled_reason") or "").strip()
            if category not in ACTIVITY_CATEGORY_LABELS:
                category = "others"
            if status not in {item.value for item in TaskStatus}:
                status = TaskStatus.NOT_STARTED.value
            is_backlog = normalize_ai_boolean(item.get("is_backlog"))
            if is_backlog and (start_date or end_date or estimated_hours is not None):
                is_backlog = False
            normalized_tasks.append(
                {
                    "title": title,
                    "description": description or title,
                    "start_date": None if is_backlog else start_date,
                    "end_date": None if is_backlog else end_date,
                    "estimated_hours": None if is_backlog else estimated_hours,
                    "category": category,
                    "status": status,
                    "is_backlog": is_backlog,
                    "stalled_reason": stalled_reason if status == TaskStatus.STALLED.value else "",
                }
            )
        if normalized_tasks:
            return normalized_tasks
        logger.warning("Bulk task AI returned no usable tasks, using local fallback")
        return extract_bulk_tasks_locally(task_lines)
    except Exception as exc:
        response_text = ""
        if isinstance(exc, httpx.HTTPStatusError):
            response_text = exc.response.text[:500]
        logger.warning("Bulk backlog AI parsing failed, using local fallback: %s %s", exc.__class__.__name__, response_text)
        return extract_bulk_tasks_locally(task_lines)


def dashboard_payload(db: Session, org: Organization, user: User) -> dict[str, Any]:
    monday, sunday = current_week_bounds()
    tasks = db.scalars(
        select(Task)
        .where(
            Task.org_id == org.id,
            Task.assigned_to == user.id,
            Task.is_archived.is_(False),
            or_(
                Task.status != TaskStatus.CLOSED,
                Task.start_date.between(monday, sunday),
                Task.end_date.between(monday, sunday),
            ),
        )
        .order_by(Task.dashboard_rank.asc(), Task.start_date.asc(), Task.created_at.desc())
    ).all()
    completed_tasks = db.scalars(
        select(Task)
        .where(
            Task.org_id == org.id,
            Task.assigned_to == user.id,
            Task.is_archived.is_(False),
            Task.status == TaskStatus.CLOSED,
            Task.closed_at.is_not(None),
            Task.closed_at >= datetime.combine(monday, datetime.min.time()),
            Task.closed_at <= datetime.combine(sunday, datetime.max.time()),
        )
        .order_by(Task.closed_at.desc())
        .limit(12)
    ).all()

    groups = {"today": [], "week": [], "overdue": [], "pending": [], "completed": []}
    today = date.today()
    for task in tasks:
        summary = dashboard_task_summary(task, today)
        in_this_week = (
            (task.start_date and monday <= task.start_date <= sunday)
            or (task.end_date and monday <= task.end_date <= sunday)
            or (
                task.status == TaskStatus.CLOSED
                and task.closed_at is not None
                and datetime.combine(monday, datetime.min.time()) <= task.closed_at <= datetime.combine(sunday, datetime.max.time())
            )
        )
        if in_this_week:
            groups["week"].append(summary)
        if task.status == TaskStatus.CLOSED:
            continue
        if task.start_date == today or task.end_date == today:
            groups["today"].append(summary)
        elif task.end_date and task.end_date < today and task.status != TaskStatus.CLOSED:
            groups["overdue"].append(summary)
        else:
            groups["pending"].append(summary)
    for task in completed_tasks:
        groups["completed"].append(dashboard_task_summary(task, today))

    groups["week"].sort(
        key=lambda item: (
            item["end_date"] is None,
            item["end_date"] or date.max,
            item["start_date"] or date.max,
            item["task_id"],
        )
    )

    return groups


def backlog_tasks_payload(db: Session, org: Organization, user: User) -> list[dict[str, Any]]:
    today = date.today()
    backlog_tasks = db.scalars(
        select(Task)
        .where(
            Task.org_id == org.id,
            Task.assigned_to == user.id,
            Task.is_archived.is_(False),
            Task.status != TaskStatus.CLOSED,
            Task.status != TaskStatus.STALLED,
            Task.start_date.is_(None),
            Task.end_date.is_(None),
            Task.estimated_hours.is_(None),
        )
        .order_by(Task.created_at.desc(), Task.id.desc())
    ).all()
    return [dashboard_task_summary(task, today) for task in backlog_tasks]


def today_payload(db: Session, org: Organization, user: User) -> dict[str, Any]:
    today = date.today()
    month_start = today.replace(day=1)
    settings_obj = get_org_settings(db, org.id)
    default_log_hours = float(settings_obj.default_time_log_hours or Decimal("1.00"))

    worked_today_rows = db.execute(
        select(
            Task,
            func.coalesce(func.sum(TimeLog.hours), 0).label("today_hours"),
            func.max(TimeLog.created_at).label("last_log_at"),
        )
        .select_from(TimeLog)
        .join(Task, TimeLog.task_id == Task.id)
        .where(
            Task.org_id == org.id,
            Task.assigned_to == user.id,
            Task.is_archived.is_(False),
            TimeLog.user_id == user.id,
            TimeLog.log_date == today,
        )
        .group_by(Task.id)
        .order_by(func.sum(TimeLog.hours).desc(), func.max(TimeLog.created_at).desc(), Task.updated_at.desc())
    ).all()

    worked_today: list[dict[str, Any]] = []
    worked_today_task_ids: set[int] = set()
    today_total_hours = Decimal("0")
    for task, today_hours, _ in worked_today_rows:
        worked_today_task_ids.add(task.id)
        today_total_hours += Decimal(str(today_hours or 0))
        summary = dashboard_task_summary(task, today)
        summary["today_hours"] = float(today_hours or 0)
        worked_today.append(summary)

    tasks_needing_action = [
        dashboard_task_summary(task, today)
        for task in db.scalars(
            select(Task)
            .where(
                Task.org_id == org.id,
                Task.assigned_to == user.id,
                Task.is_archived.is_(False),
                Task.status != TaskStatus.CLOSED,
                Task.end_date == today,
            )
            .order_by(Task.dashboard_rank.asc(), Task.created_at.desc())
        ).all()
        if task.id not in worked_today_task_ids
    ]

    delayed_tasks = [
        dashboard_task_summary(task, today)
        for task in db.scalars(
            select(Task)
            .where(
                Task.org_id == org.id,
                Task.assigned_to == user.id,
                Task.is_archived.is_(False),
                Task.status != TaskStatus.CLOSED,
                Task.end_date.is_not(None),
                Task.end_date < today,
            )
            .order_by(Task.end_date.asc(), Task.dashboard_rank.asc(), Task.created_at.desc())
        ).all()
    ]

    month_logged_hours = db.scalar(
        select(func.coalesce(func.sum(TimeLog.hours), 0)).where(
            TimeLog.user_id == user.id,
            TimeLog.log_date >= month_start,
            TimeLog.log_date <= today,
        )
    )

    monthly_ranking_rows = db.execute(
        select(
            User.id,
            User.full_name,
            func.coalesce(func.sum(TimeLog.hours), 0).label("month_hours"),
        )
        .select_from(User)
        .outerjoin(
            TimeLog,
            and_(
                TimeLog.user_id == User.id,
                TimeLog.log_date >= month_start,
                TimeLog.log_date <= today,
            ),
        )
        .where(User.org_id == org.id, User.is_active.is_(True))
        .group_by(User.id, User.full_name)
        .order_by(func.coalesce(func.sum(TimeLog.hours), 0).desc(), User.full_name.asc())
    ).all()

    month_rank = None
    for index, row in enumerate(monthly_ranking_rows, start=1):
        if row.id == user.id:
            month_rank = index
            break

    return {
        "today": today,
        "default_log_hours": default_log_hours,
        "summary": {
            "today_total_hours": round(float(today_total_hours), 2),
            "worked_task_count": len(worked_today),
            "month_logged_hours": round(float(month_logged_hours or 0), 2),
            "month_rank": month_rank,
            "team_size": len(monthly_ranking_rows),
        },
        "worked_today": worked_today,
        "tasks_needing_action": tasks_needing_action,
        "delayed_tasks": delayed_tasks,
    }


def safe_org_redirect(org_slug: str, redirect_to: str | None, fallback: str) -> str:
    target = (redirect_to or "").strip()
    if target.startswith(f"/{org_slug}/") and "\n" not in target and "\r" not in target:
        return target
    return fallback


def org_people(db: Session, org_id: int) -> list[User]:
    return db.scalars(select(User).where(User.org_id == org_id, User.is_active.is_(True)).order_by(User.full_name.asc())).all()


def org_projects(db: Session, org_id: int) -> list[Project]:
    return db.scalars(select(Project).where(Project.org_id == org_id, Project.is_active.is_(True)).order_by(Project.name.asc())).all()


def all_org_projects(db: Session, org_id: int) -> list[Project]:
    return db.scalars(select(Project).where(Project.org_id == org_id).order_by(Project.name.asc())).all()


def org_activity_types(db: Session, org_id: int) -> list[ActivityType]:
    return db.scalars(
        select(ActivityType).where(ActivityType.org_id == org_id, ActivityType.is_active.is_(True)).order_by(ActivityType.name.asc())
    ).all()


def active_activity_categories(db: Session, org_id: int) -> list[tuple[str, str]]:
    categories = sorted({item.category for item in org_activity_types(db, org_id) if item.category in ACTIVITY_CATEGORY_LABELS})
    return [(key, ACTIVITY_CATEGORY_LABELS[key]) for key in categories]


def user_tasks(db: Session, org_id: int, user_id: int) -> list[Task]:
    return db.scalars(
        select(Task)
        .where(Task.org_id == org_id, Task.assigned_to == user_id, Task.is_archived.is_(False))
        .order_by(Task.dashboard_rank.asc(), Task.status.asc(), Task.start_date.desc(), Task.created_at.desc())
    ).all()


def recent_task_summaries(db: Session, org_id: int, user_id: int) -> list[dict[str, Any]]:
    tasks = db.scalars(
        select(Task)
        .where(Task.org_id == org_id, Task.assigned_to == user_id, Task.is_archived.is_(False))
        .order_by(Task.created_at.desc(), Task.id.desc())
    ).all()
    project_map = {project.id: project for project in all_org_projects(db, org_id)}
    activity_type_map = {item.id: item for item in org_activity_types(db, org_id)}
    return [
        {
            "task_id": task.task_id,
            "name": task.name,
            "status": task.status.value,
            "task_color": normalize_task_color(task.task_color),
            "task_color_label": TASK_COLOR_MAP.get(normalize_task_color(task.task_color), "Green"),
            "tags": task_tags(task),
            "tags_text": ", ".join(task_tags(task)),
            "project_code": project_map.get(task.project_id).code if project_map.get(task.project_id) else "",
            "project_name": project_map.get(task.project_id).name if project_map.get(task.project_id) else "",
            "activity_type_name": activity_type_map.get(task.activity_type_id).name if activity_type_map.get(task.activity_type_id) else "",
            "is_backlog": task.start_date is None and task.end_date is None and task.estimated_hours is None,
            "start_date": task.start_date,
            "end_date": task.end_date,
            "estimated_hours": float(task.estimated_hours) if task.estimated_hours is not None else None,
            "logged_hours": float(task.logged_hours or 0),
            "is_private": task.is_private,
            "created_at": task.created_at,
        }
        for task in tasks
    ]


def task_tag_suggestions(db: Session, org_id: int, limit: int = 80) -> list[str]:
    values: set[str] = set()
    for raw_tags in db.scalars(select(Task.tags_text).where(Task.org_id == org_id, Task.tags_text != "")).all():
        values.update(parse_task_tags(raw_tags))
    return sorted(values)[:limit]


def next_dashboard_rank(db: Session, org_id: int, user_id: int) -> int:
    current_max = db.scalar(select(func.max(Task.dashboard_rank)).where(Task.org_id == org_id, Task.assigned_to == user_id))
    return int(current_max or 0) + 1


def get_org_settings(db: Session, org_id: int) -> OrgSettings:
    settings_obj = db.scalar(select(OrgSettings).where(OrgSettings.org_id == org_id))
    if settings_obj:
        return settings_obj
    settings_obj = OrgSettings(
        org_id=org_id,
        weekend_days=[5, 6],
        work_hours_per_day=Decimal("8.00"),
        default_task_status=TaskStatus.NOT_STARTED.value,
    )
    db.add(settings_obj)
    db.commit()
    db.refresh(settings_obj)
    return settings_obj


def parse_weekend_days(raw_days: list[str]) -> list[int]:
    return sorted({int(day) for day in raw_days if str(day).strip() != ""})


@app.get("/", response_class=HTMLResponse)
def root(request: Request, db: Session = Depends(get_db)):
    orgs = db.scalars(select(Organization).where(Organization.is_active.is_(True)).order_by(Organization.name.asc())).all()
    return templates.TemplateResponse("orgs.html", {"request": request, "orgs": orgs})


@app.get("/{org_slug}/login", response_class=HTMLResponse)
def login_page(request: Request, org_slug: str, db: Session = Depends(get_db)):
    org = get_org_or_404(db, org_slug)
    return render_login(request, org)


@app.post("/{org_slug}/login")
def login_action(
    request: Request,
    org_slug: str,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    org = get_org_or_404(db, org_slug)
    user = db.scalar(select(User).where(User.email == email.strip().lower(), User.org_id == org.id))
    if not user or not verify_password(password, user.password_hash):
        return render_login(request, org, error="Invalid email or password")

    response = RedirectResponse(url=f"/{org_slug}/dashboard", status_code=303)
    issue_auth_cookies(response, user, org_slug)
    return response


@app.post("/{org_slug}/logout")
def logout_action(org_slug: str):
    response = RedirectResponse(url=f"/{org_slug}/login", status_code=303)
    clear_auth_cookies(response)
    return response


@app.post("/api/v1/auth/login")
def api_login(payload: dict, db: Session = Depends(get_db)):
    org = get_org_or_404(db, payload["org_slug"])
    user = db.scalar(select(User).where(User.email == payload["email"].strip().lower(), User.org_id == org.id))
    if not user or not verify_password(payload["password"], user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    response = JSONResponse({"ok": True, "user_id": user.id, "org_slug": org.slug})
    issue_auth_cookies(response, user, org.slug)
    return response


@app.post("/api/v1/auth/refresh")
def api_refresh(request: Request):
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail="Missing refresh token")
    subject = decode_token(token, "refresh")
    if not subject:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    response = JSONResponse({"ok": True})
    response.set_cookie(
        "access_token",
        create_access_token(subject),
        httponly=True,
        samesite="lax",
        max_age=settings.access_token_ttl_minutes * 60,
    )
    return response


@app.post("/api/v1/auth/logout")
def api_logout():
    response = JSONResponse({"ok": True})
    clear_auth_cookies(response)
    return response


@app.post("/api/v1/auth/forgot-password")
def api_forgot_password(payload: dict, db: Session = Depends(get_db)):
    org = get_org_or_404(db, payload["org_slug"])
    user = db.scalar(select(User).where(User.email == payload["email"].strip().lower(), User.org_id == org.id))
    if not user:
        return {"ok": True}
    temp_password = issue_temporary_password(user)
    db.commit()
    try:
        send_email(user.email, "ProtrackLite temporary password", f"Your temporary password is: {temp_password}")
    except Exception:
        # Keep local development usable even without SMTP.
        print(f"[forgot-password] {user.email}: {temp_password}")
    return {"ok": True}


@app.post("/{org_slug}/forgot-password")
def forgot_password_action(
    request: Request,
    org_slug: str,
    email: str = Form(...),
    captcha_answer: str = Form(""),
    captcha_left: str = Form(""),
    captcha_right: str = Form(""),
    captcha_issued_at: str = Form(""),
    captcha_signature: str = Form(""),
    db: Session = Depends(get_db),
):
    org = get_org_or_404(db, org_slug)

    if not verify_forgot_password_captcha(
        org.slug,
        captcha_answer,
        captcha_left,
        captcha_right,
        captcha_issued_at,
        captcha_signature,
    ):
        return render_login(request, org, forgot_error="Captcha answer was incorrect or expired. Please try again.")

    user = db.scalar(select(User).where(User.email == email.strip().lower(), User.org_id == org.id))
    if user:
        temp_password = issue_temporary_password(user)
        db.commit()
        try:
            send_email(user.email, "ProtrackLite temporary password", f"Your temporary password is: {temp_password}")
        except Exception:
            print(f"[forgot-password] {user.email}: {temp_password}")

    return render_login(request, org, forgot_success="If the account exists, a new temporary password has been sent.")


@app.get("/{org_slug}/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    created_task_id: str | None = None,
    created_count: int | None = None,
    created_summary: str | None = None,
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    created_task_ids = [item.strip() for item in (created_summary or "").split(",") if item.strip()]
    if created_task_id and created_task_id not in created_task_ids:
        created_task_ids.insert(0, created_task_id)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "org": org,
            "user": user,
            "groups": dashboard_payload(db, org, user),
            "today": date.today(),
            "created_task_id": created_task_id,
            "created_count": created_count,
            "created_summary": created_summary,
            "created_task_ids": created_task_ids,
        },
    )


@app.get("/{org_slug}/today", response_class=HTMLResponse)
def today_page(request: Request, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    payload = today_payload(db, org, user)
    return templates.TemplateResponse(
        "today.html",
        {
            "request": request,
            "org": org,
            "user": user,
            **payload,
        },
    )


@app.get("/{org_slug}/backlogs", response_class=HTMLResponse)
def backlog_management_page(request: Request, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    today = date.today()
    _, week_end = current_week_bounds(today)
    return templates.TemplateResponse(
        "backlog_management.html",
        {
            "request": request,
            "org": org,
            "user": user,
            "today": today,
            "week_end": week_end,
            "backlog_tasks": backlog_tasks_payload(db, org, user),
        },
    )


@app.get("/{org_slug}/tasks/new", response_class=HTMLResponse)
def new_task_page(
    request: Request,
    created_task_id: str | None = None,
    created_count: int | None = None,
    created_summary: str | None = None,
    open_ai: int | None = None,
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    settings_obj = get_org_settings(db, org.id)
    activity_types = org_activity_types(db, org.id)
    created_task_ids = [item.strip() for item in (created_summary or "").split(",") if item.strip()]
    if created_task_id and created_task_id not in created_task_ids:
        created_task_ids.insert(0, created_task_id)
    return templates.TemplateResponse(
        "task_form.html",
        {
            "request": request,
            "org": org,
            "user": user,
            "task": None,
            "projects": org_projects(db, org.id),
            "activity_types": activity_types,
            "activity_categories": active_activity_categories(db, org.id),
            "statuses": list(TaskStatus),
            "settings": settings_obj,
            "today": date.today(),
            "tasks": recent_task_summaries(db, org.id, user.id),
            "created_task_id": created_task_id,
            "created_count": created_count,
            "created_summary": created_summary,
            "created_task_ids": created_task_ids,
            "open_ai": bool(open_ai),
        },
    )


@app.post("/{org_slug}/tasks/new")
def create_task_page(
    org_slug: str,
    project_id: int = Form(...),
    name: str = Form(...),
    activity_type_id: int = Form(...),
    description: str = Form(""),
    start_date: str = Form(""),
    end_date: str = Form(""),
    estimated_hours: str = Form(""),
    tags: str = Form(""),
    status_value: TaskStatus = Form(TaskStatus.NOT_STARTED, alias="status"),
    is_backlog: bool = Form(False),
    is_private: bool = Form(False),
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    project = db.get(Project, project_id)
    if not project or project.org_id != org.id:
        raise HTTPException(status_code=404, detail="Project not found")

    parsed_start_date = None if is_backlog else parse_optional_date(start_date)
    parsed_end_date = None if is_backlog else parse_optional_date(end_date)
    parsed_estimated_hours = None if is_backlog else parse_optional_decimal(estimated_hours)

    task = Task(
        task_id=next_task_id(project),
        org_id=org.id,
        project_id=project.id,
        assigned_to=user.id,
        created_by=user.id,
        name=name,
        description=sanitize_html(description),
        activity_type_id=activity_type_id,
        status=status_value,
        tags_text=serialize_task_tags(parse_task_tags(tags)),
        is_private=is_private,
        dashboard_rank=next_dashboard_rank(db, org.id, user.id),
        start_date=parsed_start_date,
        end_date=parsed_end_date,
        estimated_hours=parsed_estimated_hours,
        closed_at=datetime.utcnow() if status_value == TaskStatus.CLOSED else None,
    )
    db.add(task)
    db.commit()
    return RedirectResponse(url=f"/{org_slug}/tasks/new?created_task_id={task.task_id}", status_code=303)


@app.post("/{org_slug}/tasks/new/bulk-backlog-ai")
def create_bulk_backlog_tasks(
    org_slug: str,
    freeflow_tasks: str = Form(""),
    is_private: bool = Form(False),
    redirect_to: str = Form(""),
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    task_lines = split_freeflow_task_input(freeflow_tasks)
    if not task_lines:
        return RedirectResponse(url=f"/{org_slug}/tasks/new", status_code=303)

    project, default_activity_type = resolve_default_task_targets(db, org.id)
    activity_types = org_activity_types(db, org.id)
    parsed_tasks = extract_bulk_tasks_with_openai(freeflow_tasks)
    created_task_ids: list[str] = []

    for parsed_task in parsed_tasks:
        activity_type = select_activity_type_for_ai_task(activity_types, default_activity_type, parsed_task.get("category"))
        status_value = TaskStatus(parsed_task.get("status") or TaskStatus.NOT_STARTED.value)
        task = Task(
            task_id=next_task_id(project),
            org_id=org.id,
            project_id=project.id,
            assigned_to=user.id,
            created_by=user.id,
            name=parsed_task["title"],
            description=sanitize_html(parsed_task["description"]),
            activity_type_id=activity_type.id,
            status=status_value,
            is_private=is_private,
            dashboard_rank=next_dashboard_rank(db, org.id, user.id),
            start_date=parsed_task["start_date"],
            end_date=parsed_task["end_date"],
            estimated_hours=parsed_task["estimated_hours"],
            stalled_reason=parsed_task.get("stalled_reason") or "",
            closed_at=datetime.utcnow() if status_value == TaskStatus.CLOSED else None,
        )
        db.add(task)
        db.flush()
        created_task_ids.append(task.task_id)

    db.commit()
    created_summary = ",".join(created_task_ids[:5])
    redirect_base = safe_org_redirect(org_slug, redirect_to, f"/{org_slug}/tasks/new")
    return RedirectResponse(
        url=f"{redirect_base}?created_task_id={created_task_ids[0]}&created_count={len(created_task_ids)}&created_summary={created_summary}",
        status_code=303,
    )


@app.get("/{org_slug}/tasks/{task_code}", response_class=HTMLResponse)
def task_detail_page(request: Request, org_slug: str, task_code: str, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    settings_obj = get_org_settings(db, org.id)
    task = db.scalar(select(Task).where(Task.task_id == task_code, Task.org_id == org.id))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    logs = db.scalars(select(TimeLog).where(TimeLog.task_id == task.id).order_by(TimeLog.log_date.desc(), TimeLog.created_at.desc())).all()
    return templates.TemplateResponse(
        "task_detail.html",
        {
            "request": request,
            "org": org,
            "user": user,
            "task": task,
            "logs": logs,
            "projects": all_org_projects(db, org.id),
            "activity_types": org_activity_types(db, org.id),
            "activity_categories": active_activity_categories(db, org.id),
            "current_activity_category": db.get(ActivityType, task.activity_type_id).category if db.get(ActivityType, task.activity_type_id) else "others",
            "statuses": list(TaskStatus),
            "people": org_people(db, org.id),
            "settings": settings_obj,
            "today": date.today(),
        },
    )


@app.get("/{org_slug}/tasks/{task_code}/calendar.ics")
def download_task_calendar(org_slug: str, task_code: str, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    task_query = select(Task).where(Task.task_id == task_code, Task.org_id == org.id)
    if user.role != Role.ADMIN:
        task_query = task_query.where(Task.assigned_to == user.id)
    task = db.scalar(task_query)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    ical_body = build_task_ical(task, org)
    filename = f"{task.task_id.lower()}-calendar.ics"
    return Response(
        content=ical_body,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/{org_slug}/tasks/{task_code}/archive")
def archive_task_page(org_slug: str, task_code: str, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    task_query = select(Task).where(Task.task_id == task_code, Task.org_id == org.id)
    if user.role != Role.ADMIN:
        task_query = task_query.where(Task.assigned_to == user.id)
    task = db.scalar(task_query)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.is_archived = True
    db.commit()
    return RedirectResponse(url=f"/{org_slug}/dashboard", status_code=303)


@app.post("/{org_slug}/backlogs/{task_code}/delete")
def delete_backlog_task_page(
    org_slug: str,
    task_code: str,
    redirect_to: str = Form(""),
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    task_query = select(Task).where(Task.task_id == task_code, Task.org_id == org.id, Task.is_archived.is_(False))
    if user.role != Role.ADMIN:
        task_query = task_query.where(Task.assigned_to == user.id)
    task = db.scalar(task_query)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status in {TaskStatus.CLOSED, TaskStatus.STALLED} or task.start_date or task.end_date or task.estimated_hours is not None:
        raise HTTPException(status_code=400, detail="Only backlog items can be deleted from backlog management")

    db.delete(task)
    db.commit()
    return RedirectResponse(url=safe_org_redirect(org_slug, redirect_to, f"/{org_slug}/backlogs"), status_code=303)


@app.post("/{org_slug}/backlogs/{task_code}/add-to-this-week")
def add_backlog_task_to_this_week(
    org_slug: str,
    task_code: str,
    redirect_to: str = Form(""),
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    task_query = select(Task).where(Task.task_id == task_code, Task.org_id == org.id, Task.is_archived.is_(False))
    if user.role != Role.ADMIN:
        task_query = task_query.where(Task.assigned_to == user.id)
    task = db.scalar(task_query)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status in {TaskStatus.CLOSED, TaskStatus.STALLED} or task.start_date or task.end_date or task.estimated_hours is not None:
        raise HTTPException(status_code=400, detail="Only backlog items can be added from backlog management")

    today = date.today()
    _, week_end = current_week_bounds(today)
    task.start_date = today
    task.end_date = week_end
    db.commit()
    return RedirectResponse(url=safe_org_redirect(org_slug, redirect_to, f"/{org_slug}/backlogs"), status_code=303)


@app.post("/{org_slug}/tasks/{task_code}/complete")
def complete_task_page(
    org_slug: str,
    task_code: str,
    completion_date: date = Form(...),
    redirect_to: str = Form(""),
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    task_query = select(Task).where(Task.task_id == task_code, Task.org_id == org.id)
    if user.role != Role.ADMIN:
        task_query = task_query.where(Task.assigned_to == user.id)
    task = db.scalar(task_query)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    today = date.today()
    earliest_completion_date = task.start_date or task.created_at.date()
    if completion_date < earliest_completion_date or completion_date > today:
        raise HTTPException(status_code=400, detail="Completion date must be between the task start date and today")

    task.status = TaskStatus.CLOSED
    task.closed_at = datetime.combine(completion_date, datetime.max.time().replace(microsecond=0))
    if task.start_date is None:
        task.start_date = completion_date
    if task.end_date is None:
        task.end_date = completion_date
    db.commit()
    return RedirectResponse(url=safe_org_redirect(org_slug, redirect_to, f"/{org_slug}/dashboard"), status_code=303)


@app.post("/{org_slug}/tasks/{task_code}/unarchive")
def unarchive_task_page(org_slug: str, task_code: str, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    task_query = select(Task).where(Task.task_id == task_code, Task.org_id == org.id)
    if user.role != Role.ADMIN:
        task_query = task_query.where(Task.assigned_to == user.id)
    task = db.scalar(task_query)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.is_archived = False
    db.commit()
    return RedirectResponse(url=f"/{org_slug}/tasks/{task_code}", status_code=303)


@app.post("/{org_slug}/dashboard/today-order")
def update_dashboard_today_order(
    org_slug: str,
    payload: dict[str, list[str]] = Body(...),
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    ordered_task_codes = [str(task_code).strip() for task_code in payload.get("task_ids", []) if str(task_code).strip()]
    if not ordered_task_codes:
        return JSONResponse({"ok": False, "detail": "No tasks supplied"}, status_code=400)

    today = date.today()
    today_tasks = db.scalars(
        select(Task)
        .where(
            Task.org_id == org.id,
            Task.assigned_to == user.id,
            Task.is_archived.is_(False),
            Task.status != TaskStatus.CLOSED,
            or_(Task.start_date == today, Task.end_date == today),
        )
        .order_by(Task.dashboard_rank.asc(), Task.created_at.desc())
    ).all()
    today_task_by_code = {task.task_id: task for task in today_tasks}
    missing_codes = [task.task_id for task in today_tasks if task.task_id not in ordered_task_codes]
    normalized_codes = [task_code for task_code in ordered_task_codes if task_code in today_task_by_code] + missing_codes

    for rank, task_code in enumerate(normalized_codes, start=1):
        today_task_by_code[task_code].dashboard_rank = rank

    db.commit()
    return JSONResponse({"ok": True, "task_ids": normalized_codes})


@app.post("/{org_slug}/tasks/{task_code}")
def update_task_page(
    org_slug: str,
    task_code: str,
    project_id: int = Form(...),
    name: str = Form(...),
    activity_type_id: int = Form(...),
    description: str = Form(""),
    start_date: str = Form(""),
    end_date: str = Form(""),
    estimated_hours: str = Form(""),
    tags: str = Form(""),
    status_value: TaskStatus = Form(..., alias="status"),
    stalled_reason: str = Form(""),
    is_backlog: bool = Form(False),
    is_private: bool = Form(False),
    assigned_to: int | None = Form(None),
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    task_query = select(Task).where(Task.task_id == task_code, Task.org_id == org.id)
    if user.role != Role.ADMIN:
        task_query = task_query.where(Task.assigned_to == user.id)
    task = db.scalar(task_query)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    parsed_start_date = None if is_backlog else parse_optional_date(start_date)
    parsed_end_date = None if is_backlog else parse_optional_date(end_date)
    parsed_estimated_hours = None if is_backlog else parse_optional_decimal(estimated_hours)

    task.project_id = project_id
    task.name = name
    task.activity_type_id = activity_type_id
    task.description = sanitize_html(description)
    task.tags_text = serialize_task_tags(parse_task_tags(tags))
    task.start_date = parsed_start_date
    task.end_date = parsed_end_date
    task.estimated_hours = parsed_estimated_hours
    task.status = status_value
    task.stalled_reason = stalled_reason.strip() if status_value == TaskStatus.STALLED else ""
    task.is_private = is_private
    if user.role == Role.ADMIN and assigned_to:
        assignee = db.get(User, assigned_to)
        if assignee and assignee.org_id == org.id and assignee.is_active:
            task.assigned_to = assignee.id
    task.closed_at = datetime.utcnow() if status_value == TaskStatus.CLOSED else None
    db.commit()
    return RedirectResponse(url=f"/{org_slug}/tasks/{task_code}", status_code=303)


@app.post("/{org_slug}/tasks/{task_code}/time-log")
def add_time_log_page(
    org_slug: str,
    task_code: str,
    log_date: date = Form(...),
    hours: Decimal = Form(...),
    notes: str = Form(""),
    redirect_to: str = Form(""),
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    task = db.scalar(select(Task).where(Task.task_id == task_code, Task.org_id == org.id, Task.assigned_to == user.id))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.add(TimeLog(task_id=task.id, user_id=user.id, log_date=log_date, hours=hours, notes=notes))
    db.flush()
    if task.status == TaskStatus.NOT_STARTED:
        task.status = TaskStatus.STARTED
    if task.start_date is None:
        task.start_date = log_date
    task.logged_hours = db.scalar(select(func.coalesce(func.sum(TimeLog.hours), 0)).where(TimeLog.task_id == task.id))
    db.commit()
    return RedirectResponse(
        url=safe_org_redirect(org_slug, redirect_to, f"/{org_slug}/tasks/{task_code}"),
        status_code=303,
    )


@app.get("/api/v1/tasks/")
def api_list_tasks(
    status: str | None = None,
    project_id: int | None = None,
    q: str | None = None,
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    query = select(Task).where(Task.org_id == org.id, Task.assigned_to == user.id)
    if status:
        query = query.where(Task.status == TaskStatus(status))
    if project_id:
        query = query.where(Task.project_id == project_id)
    if q:
        query = query.where(or_(Task.name.ilike(f"%{q}%"), Task.task_id.ilike(f"%{q}%"), Task.tags_text.ilike(f"%{q}%")))
    tasks = db.scalars(query.order_by(Task.created_at.desc())).all()
    return [
        {
            "task_id": task.task_id,
            "name": task.name,
            "status": task.status.value,
            "task_color": normalize_task_color(task.task_color),
            "tags": task_tags(task),
            "logged_hours": float(task.logged_hours or 0),
            "estimated_hours": float(task.estimated_hours) if task.estimated_hours is not None else None,
            "stalled_reason": task.stalled_reason,
            "is_private": task.is_private,
        }
        for task in tasks
    ]


@app.post("/api/v1/tasks/")
def api_create_task(payload: dict, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    project = db.get(Project, payload["project_id"])
    if not project or project.org_id != org.id:
        raise HTTPException(status_code=404, detail="Project not found")
    task = Task(
        task_id=next_task_id(project),
        org_id=org.id,
        project_id=project.id,
        assigned_to=user.id,
        created_by=user.id,
        name=payload["name"],
        description=sanitize_html(payload.get("description", "")),
        activity_type_id=payload["activity_type_id"],
        status=TaskStatus(payload.get("status", "not_started")),
        task_color=normalize_task_color(payload.get("task_color")),
        tags_text=serialize_task_tags(parse_task_tags(payload.get("tags"))),
        is_private=payload.get("is_private", False),
        start_date=None if payload.get("is_backlog") else parse_optional_date(payload.get("start_date")) or date.today(),
        end_date=None if payload.get("is_backlog") else parse_optional_date(payload.get("end_date")),
        estimated_hours=None if payload.get("is_backlog") else parse_optional_decimal(str(payload.get("estimated_hours", "") or "")),
        stalled_reason=(payload.get("stalled_reason") or "").strip() if payload.get("status") == "stalled" else "",
    )
    db.add(task)
    db.commit()
    return {"task_id": task.task_id}


@app.get("/api/v1/tasks/quick-create/options")
def api_quick_create_task_options(org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, _ = org_user
    settings_obj = get_org_settings(db, org.id)
    projects = org_projects(db, org.id)
    activity_types = org_activity_types(db, org.id)
    default_project, default_activity_type = resolve_default_task_targets(db, org.id)
    default_status = settings_obj.default_task_status or TaskStatus.NOT_STARTED.value

    return {
        "projects": [{"id": item.id, "name": item.name, "code": item.code} for item in projects],
        "activity_types": [
            {"id": item.id, "name": item.name, "category": item.category}
            for item in activity_types
        ],
        "activity_categories": [
            {"key": key, "label": label}
            for key, label in active_activity_categories(db, org.id)
        ],
        "statuses": [{"value": item.value, "label": item.value.replace("_", " ")} for item in TaskStatus],
        "defaults": {
            "project_id": default_project.id,
            "activity_type_id": default_activity_type.id,
            "status": default_status,
            "start_date": date.today().isoformat(),
            "task_color": DEFAULT_TASK_COLOR,
        },
    }


@app.get("/api/v1/tasks/{task_code}")
def api_get_task(task_code: str, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    task = db.scalar(select(Task).where(Task.task_id == task_code, Task.org_id == org.id))
    if not task or (task.assigned_to != user.id and task.is_private):
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": task.task_id,
        "name": task.name,
        "description": task.description,
        "status": task.status.value,
        "task_color": normalize_task_color(task.task_color),
        "tags": task_tags(task),
        "logged_hours": float(task.logged_hours or 0),
        "estimated_hours": float(task.estimated_hours) if task.estimated_hours is not None else None,
        "stalled_reason": task.stalled_reason,
    }


@app.put("/api/v1/tasks/{task_code}")
def api_update_task(task_code: str, payload: dict, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    task = db.scalar(select(Task).where(Task.task_id == task_code, Task.org_id == org.id, Task.assigned_to == user.id))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    for attr in ["name", "project_id", "activity_type_id", "is_private"]:
        if attr in payload:
            setattr(task, attr, payload[attr])
    if "description" in payload:
        task.description = sanitize_html(payload["description"])
    if "task_color" in payload:
        task.task_color = normalize_task_color(payload.get("task_color"))
    if "tags" in payload:
        task.tags_text = serialize_task_tags(parse_task_tags(payload.get("tags")))
    is_backlog = bool(payload.get("is_backlog"))
    if "is_backlog" in payload and is_backlog:
        task.start_date = None
        task.end_date = None
        task.estimated_hours = None
    else:
        if "start_date" in payload:
            task.start_date = parse_optional_date(payload.get("start_date")) or task.start_date
        if "end_date" in payload:
            task.end_date = parse_optional_date(payload.get("end_date"))
        if "estimated_hours" in payload:
            task.estimated_hours = parse_optional_decimal(str(payload.get("estimated_hours", "") or ""))
    if "status" in payload:
        task.status = TaskStatus(payload["status"])
        task.closed_at = datetime.utcnow() if task.status == TaskStatus.CLOSED else None
        if task.status != TaskStatus.STALLED:
            task.stalled_reason = ""
    if "stalled_reason" in payload:
        task.stalled_reason = str(payload["stalled_reason"]).strip() if task.status == TaskStatus.STALLED else ""
    db.commit()
    return {"ok": True}


@app.post("/api/v1/tasks/{task_code}/time-log")
def api_add_time_log(task_code: str, payload: dict, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    task = db.scalar(select(Task).where(Task.task_id == task_code, Task.org_id == org.id, Task.assigned_to == user.id))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.add(
        TimeLog(
            task_id=task.id,
            user_id=user.id,
            log_date=date.fromisoformat(payload["log_date"]),
            hours=payload["hours"],
            notes=payload.get("notes", ""),
        )
    )
    db.flush()
    first_log_date = date.fromisoformat(payload["log_date"])
    if task.status == TaskStatus.NOT_STARTED:
        task.status = TaskStatus.STARTED
    if task.start_date is None:
        task.start_date = first_log_date
    task.logged_hours = db.scalar(select(func.coalesce(func.sum(TimeLog.hours), 0)).where(TimeLog.task_id == task.id))
    db.commit()
    return {"ok": True, "logged_hours": float(task.logged_hours or 0)}


@app.get("/api/v1/tasks/{task_code}/time-logs")
def api_list_time_logs(task_code: str, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    task = db.scalar(select(Task).where(Task.task_id == task_code, Task.org_id == org.id))
    if not task or (task.assigned_to != user.id and task.is_private):
        raise HTTPException(status_code=404, detail="Task not found")
    logs = db.scalars(select(TimeLog).where(TimeLog.task_id == task.id).order_by(TimeLog.log_date.desc())).all()
    return [{"date": item.log_date.isoformat(), "hours": float(item.hours), "notes": item.notes} for item in logs]


@app.get("/api/v1/tasks/tag-options")
def api_task_tag_options(org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, _ = org_user
    return {"tags": task_tag_suggestions(db, org.id)}


@app.post("/api/v1/tasks/{task_code}/color")
def api_update_task_color(task_code: str, payload: dict, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    task_query = select(Task).where(Task.task_id == task_code, Task.org_id == org.id)
    if user.role != Role.ADMIN:
        task_query = task_query.where(Task.assigned_to == user.id)
    task = db.scalar(task_query)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    task.task_color = normalize_task_color(payload.get("color"))
    db.commit()
    return {"ok": True, "task_id": task.task_id, "color": task.task_color, "label": TASK_COLOR_MAP.get(task.task_color, "Green")}


@app.get("/api/v1/projects/")
def api_list_projects(org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, _ = org_user
    return [{"id": item.id, "name": item.name, "code": item.code} for item in org_projects(db, org.id)]


@app.post("/api/v1/projects/")
def api_create_project(payload: dict, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    must_be_admin(user)
    project = Project(
        org_id=org.id,
        name=payload["name"],
        code=payload["code"].upper(),
        description=payload.get("description", ""),
        created_by=user.id,
    )
    db.add(project)
    db.commit()
    return {"id": project.id}


@app.get("/api/v1/users/")
def api_list_users(org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, _ = org_user
    return [{"id": item.id, "full_name": item.full_name, "email": item.email, "role": item.role.value} for item in org_people(db, org.id)]


@app.get("/api/v1/users/me")
def api_user_me(org_user: tuple[Organization, User] = Depends(get_org_user)):
    _, user = org_user
    return {"id": user.id, "full_name": user.full_name, "email": user.email, "role": user.role.value}


@app.put("/api/v1/users/me")
def api_update_me(payload: dict, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    _, user = org_user
    if payload.get("full_name"):
        user.full_name = payload["full_name"]
    if payload.get("password"):
        user.password_hash = hash_password(payload["password"])
        user.force_password_change = False
        user.temp_password_expires = None
    db.commit()
    return {"ok": True}


@app.get("/api/v1/users/{user_id}/tasks")
def api_public_tasks(user_id: int, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, _ = org_user
    tasks = db.scalars(
        select(Task).where(Task.org_id == org.id, Task.assigned_to == user_id, Task.is_private.is_(False)).order_by(Task.created_at.desc())
    ).all()
    return [{"task_id": task.task_id, "name": task.name, "status": task.status.value, "logged_hours": float(task.logged_hours or 0)} for task in tasks]


@app.get("/{org_slug}/team/{user_id}/tasks", response_class=HTMLResponse)
def team_tasks_page(request: Request, org_slug: str, user_id: int, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, current_user = org_user
    teammate = db.get(User, user_id)
    if not teammate or teammate.org_id != org.id:
        raise HTTPException(status_code=404, detail="User not found")
    tasks = db.scalars(
        select(Task).where(Task.org_id == org.id, Task.assigned_to == teammate.id, Task.is_private.is_(False)).order_by(Task.created_at.desc())
    ).all()
    return templates.TemplateResponse(
        "team_tasks.html",
        {"request": request, "org": org, "user": current_user, "teammate": teammate, "tasks": tasks},
    )


@app.get("/{org_slug}/reports/work-rate", response_class=HTMLResponse)
def work_rate_page(
    request: Request,
    org_slug: str,
    from_date: date | None = None,
    to_date: date | None = None,
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    today = date.today()
    from_date = from_date or today.replace(day=1)
    to_date = to_date or today
    report = compute_work_rate(db, org.id, user.id, from_date, to_date)
    return templates.TemplateResponse(
        "work_rate.html",
        {"request": request, "org": org, "user": user, "report": report, "from_date": from_date, "to_date": to_date},
    )


@app.get("/{org_slug}/reports/monday", response_class=HTMLResponse)
def monday_report_page(request: Request, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    report = monday_report(db, org.id, user.id)
    return templates.TemplateResponse("monday_report.html", {"request": request, "org": org, "user": user, "report": report})


@app.post("/{org_slug}/reports/monday/add-from-backlog")
async def monday_report_add_from_backlog(
    org_slug: str,
    request: Request,
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    this_monday, this_sunday = current_week_bounds()
    form = await request.form()
    selected_task_codes = form.getlist("selected_task_codes")

    if not selected_task_codes:
        return RedirectResponse(url=f"/{org_slug}/reports/monday", status_code=303)

    tasks = db.scalars(
        select(Task).where(
            Task.org_id == org.id,
            Task.assigned_to == user.id,
            Task.status != TaskStatus.CLOSED,
            Task.status != TaskStatus.STALLED,
            Task.task_id.in_(selected_task_codes),
        )
    ).all()
    task_by_code = {task.task_id: task for task in tasks}

    for task_code in selected_task_codes:
        task = task_by_code.get(task_code)
        if not task:
            continue
        end_date_raw = str(form.get(f"end_date_{task_code}") or "").strip()
        estimated_hours_raw = str(form.get(f"estimated_hours_{task_code}") or "").strip()
        task.start_date = this_monday
        task.end_date = date.fromisoformat(end_date_raw) if end_date_raw else this_sunday
        task.estimated_hours = Decimal(estimated_hours_raw) if estimated_hours_raw else Decimal("8.00")

    db.commit()
    return RedirectResponse(url=f"/{org_slug}/reports/monday", status_code=303)


@app.get("/{org_slug}/reports/overview", response_class=HTMLResponse)
def reports_overview_page(request: Request, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    report = reports_overview(db, org.id, user.id)
    return templates.TemplateResponse(
        "reports_overview.html",
        {
            "request": request,
            "org": org,
            "user": user,
            "report": report,
            "activity_category_labels": ACTIVITY_CATEGORY_LABELS,
        },
    )


@app.get("/api/v1/reports/work-rate")
def api_work_rate(
    from_date: date,
    to_date: date,
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    return compute_work_rate(db, org.id, user.id, from_date, to_date)


@app.get("/api/v1/reports/closures")
def api_closure_report(
    from_date: date,
    to_date: date,
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    tasks = db.scalars(
        select(Task)
        .where(
            Task.org_id == org.id,
            Task.assigned_to == user.id,
            Task.status == TaskStatus.CLOSED,
            Task.closed_at >= datetime.combine(from_date, datetime.min.time()),
            Task.closed_at <= datetime.combine(to_date, datetime.max.time()),
        )
        .order_by(Task.closed_at.desc())
    ).all()
    return [
        {
            "task_id": task.task_id,
            "name": task.name,
            "closed_at": task.closed_at.isoformat() if task.closed_at else None,
            "estimated_hours": float(task.estimated_hours) if task.estimated_hours is not None else None,
            "logged_hours": float(task.logged_hours or 0),
        }
        for task in tasks
    ]


@app.get("/api/v1/reports/monday-demo")
def api_monday_demo(org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    report = monday_report(db, org.id, user.id)
    return {
        "this_week_tasks": [item["task_id"] for item in report["this_week_tasks"]],
        "pending_from_last_week": [item["task_id"] for item in report["pending_from_last_week"]],
        "closed_this_week": [item["task_id"] for item in report["closed_this_week"]],
    }


@app.get("/api/v1/reports/my-standing")
def api_my_standing(
    compare_user_id: int | None = None,
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    today = date.today()
    start = today.replace(day=1)
    mine = compute_work_rate(db, org.id, user.id, start, today)
    comparison = None
    if compare_user_id:
        comparison = compute_work_rate(db, org.id, compare_user_id, start, today)
    return {"mine": mine, "comparison": comparison}


@app.get("/api/v1/leaves/")
def api_list_leaves(org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    _, user = org_user
    leaves = db.scalars(select(Leave).where(Leave.user_id == user.id).order_by(Leave.leave_date.desc())).all()
    return [{"id": item.id, "leave_date": item.leave_date.isoformat(), "leave_type": item.leave_type.value, "reason": item.reason} for item in leaves]


@app.post("/api/v1/leaves/")
def api_add_leave(payload: dict, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    _, user = org_user
    leave = Leave(
        user_id=user.id,
        leave_date=date.fromisoformat(payload["leave_date"]),
        leave_type=LeaveType(payload.get("leave_type", "full")),
        reason=payload.get("reason", ""),
    )
    db.add(leave)
    db.commit()
    return {"id": leave.id}


@app.delete("/api/v1/leaves/{leave_id}")
def api_delete_leave(leave_id: int, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    _, user = org_user
    leave = db.get(Leave, leave_id)
    if not leave or leave.user_id != user.id:
        raise HTTPException(status_code=404, detail="Leave not found")
    db.delete(leave)
    db.commit()
    return {"ok": True}


@app.get("/{org_slug}/admin/dashboard", response_class=HTMLResponse)
def admin_dashboard_page(request: Request, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    must_be_admin(user)
    today = date.today()
    month_start = today.replace(day=1)
    team = org_people(db, org.id)
    rows = []
    for member in team:
        rates = compute_work_rate(db, org.id, member.id, month_start, today)
        open_tasks = db.scalar(select(func.count()).select_from(Task).where(Task.org_id == org.id, Task.assigned_to == member.id, Task.status != TaskStatus.CLOSED))
        closed_tasks = db.scalar(
            select(func.count()).select_from(Task).where(Task.org_id == org.id, Task.assigned_to == member.id, Task.status == TaskStatus.CLOSED)
        )
        rows.append({"member": member, "rates": rates, "open_tasks": open_tasks, "closed_tasks": closed_tasks})

    summary = {
        "employees": len(team),
        "tasks_created_month": db.scalar(select(func.count()).select_from(Task).where(Task.org_id == org.id, Task.created_at >= datetime.combine(month_start, datetime.min.time()))),
        "tasks_closed_month": db.scalar(
            select(func.count()).select_from(Task).where(
                Task.org_id == org.id,
                Task.status == TaskStatus.CLOSED,
                Task.closed_at >= datetime.combine(month_start, datetime.min.time()),
            )
        ),
    }
    return templates.TemplateResponse(
        "admin_dashboard.html",
        {
            "request": request,
            "org": org,
            "user": user,
            "summary": summary,
            "rows": rows,
            "settings": get_org_settings(db, org.id),
        },
    )


@app.get("/{org_slug}/admin/users", response_class=HTMLResponse)
def admin_users_page(request: Request, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    must_be_admin(user)
    people = db.scalars(select(User).where(User.org_id == org.id).order_by(User.created_at.desc())).all()
    return templates.TemplateResponse("admin_users.html", {"request": request, "org": org, "user": user, "people": people, "roles": list(Role)})


@app.post("/{org_slug}/admin/users")
def admin_create_user(
    org_slug: str,
    full_name: str = Form(...),
    email: str = Form(...),
    role: Role = Form(Role.EMPLOYEE),
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    must_be_admin(user)
    temp_password = generate_temp_password()
    new_user = User(
        org_id=org.id,
        full_name=full_name.strip(),
        email=email.strip().lower(),
        role=role,
        password_hash=hash_password(temp_password),
        force_password_change=True,
        temp_password_expires=datetime.utcnow() + timedelta(hours=24),
        is_active=True,
    )
    db.add(new_user)
    db.commit()
    try:
        send_email(new_user.email, "ProtrackLite temporary password", f"Your temporary password is: {temp_password}")
    except Exception:
        print(f"[admin-create-user] {new_user.email}: {temp_password}")
    return RedirectResponse(url=f"/{org_slug}/admin/users", status_code=303)


@app.post("/{org_slug}/admin/users/{user_id}")
def admin_update_user(
    org_slug: str,
    user_id: int,
    full_name: str = Form(...),
    role: Role = Form(...),
    is_active: bool = Form(False),
    reset_password: str | None = Form(None),
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    must_be_admin(user)
    target = db.get(User, user_id)
    if not target or target.org_id != org.id:
        raise HTTPException(status_code=404, detail="User not found")
    target.full_name = full_name.strip()
    target.role = role
    target.is_active = is_active
    if reset_password:
        temp_password = generate_temp_password()
        target.password_hash = hash_password(temp_password)
        target.force_password_change = True
        target.temp_password_expires = datetime.utcnow() + timedelta(hours=24)
        try:
            send_email(target.email, "ProtrackLite password reset", f"Your temporary password is: {temp_password}")
        except Exception:
            print(f"[admin-reset-user] {target.email}: {temp_password}")
    db.commit()
    return RedirectResponse(url=f"/{org_slug}/admin/users", status_code=303)


@app.get("/{org_slug}/admin/projects", response_class=HTMLResponse)
def admin_projects_page(request: Request, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    must_be_admin(user)
    projects = db.scalars(select(Project).where(Project.org_id == org.id).order_by(Project.created_at.desc())).all()
    return templates.TemplateResponse("admin_projects.html", {"request": request, "org": org, "user": user, "projects": projects})


@app.post("/{org_slug}/admin/projects")
def admin_create_project(
    org_slug: str,
    name: str = Form(...),
    code: str = Form(...),
    description: str = Form(""),
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    must_be_admin(user)
    normalized_code = code.strip().upper()
    duplicate = db.scalar(select(Project).where(Project.org_id == org.id, Project.code == normalized_code))
    if duplicate:
        raise HTTPException(status_code=400, detail="Project code already exists")
    project = Project(
        org_id=org.id,
        name=name.strip(),
        code=normalized_code,
        description=description.strip(),
        created_by=user.id,
        is_active=True,
    )
    db.add(project)
    db.commit()
    return RedirectResponse(url=f"/{org_slug}/admin/projects", status_code=303)


@app.post("/{org_slug}/admin/projects/{project_id}")
def admin_update_project(
    org_slug: str,
    project_id: int,
    name: str = Form(...),
    code: str = Form(...),
    description: str = Form(""),
    is_active: bool = Form(False),
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    must_be_admin(user)
    project = db.get(Project, project_id)
    if not project or project.org_id != org.id:
        raise HTTPException(status_code=404, detail="Project not found")
    normalized_code = code.strip().upper()
    duplicate = db.scalar(select(Project).where(Project.org_id == org.id, Project.code == normalized_code, Project.id != project.id))
    if duplicate:
        raise HTTPException(status_code=400, detail="Project code already exists")
    project.name = name.strip()
    project.code = normalized_code
    project.description = description.strip()
    project.is_active = is_active
    db.commit()
    return RedirectResponse(url=f"/{org_slug}/admin/projects", status_code=303)


@app.get("/{org_slug}/admin/activity-types", response_class=HTMLResponse)
def admin_activity_types_page(request: Request, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    must_be_admin(user)
    activity_types = db.scalars(select(ActivityType).where(ActivityType.org_id == org.id).order_by(ActivityType.name.asc())).all()
    return templates.TemplateResponse(
        "admin_activity_types.html",
        {
            "request": request,
            "org": org,
            "user": user,
            "activity_types": activity_types,
            "activity_categories": ACTIVITY_CATEGORY_CHOICES,
            "activity_category_labels": ACTIVITY_CATEGORY_LABELS,
        },
    )


@app.post("/{org_slug}/admin/activity-types")
def admin_create_activity_type(
    org_slug: str,
    code: str = Form(...),
    name: str = Form(...),
    category: str = Form("others"),
    is_chargeable: bool = Form(False),
    is_active: bool = Form(True),
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    must_be_admin(user)
    normalized_code = code.strip().upper()
    normalized_name = name.strip()
    duplicate = db.scalar(select(ActivityType).where(ActivityType.org_id == org.id, ActivityType.code == normalized_code))
    if duplicate:
        raise HTTPException(status_code=400, detail="Activity type code already exists")
    db.add(
        ActivityType(
            org_id=org.id,
            code=normalized_code,
            name=normalized_name,
            category=category if category in ACTIVITY_CATEGORY_LABELS else "others",
            is_chargeable=is_chargeable,
            is_active=is_active,
            is_default=False,
        )
    )
    db.commit()
    return RedirectResponse(url=f"/{org_slug}/admin/activity-types", status_code=303)


@app.post("/{org_slug}/admin/activity-types/{activity_type_id}")
def admin_update_activity_type(
    org_slug: str,
    activity_type_id: int,
    code: str = Form(...),
    name: str = Form(...),
    category: str = Form("others"),
    is_chargeable: bool = Form(False),
    is_active: bool = Form(False),
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    must_be_admin(user)
    activity_type = db.get(ActivityType, activity_type_id)
    if not activity_type or activity_type.org_id != org.id:
        raise HTTPException(status_code=404, detail="Activity type not found")
    normalized_code = code.strip().upper()
    normalized_name = name.strip()
    duplicate = db.scalar(
        select(ActivityType).where(
            ActivityType.org_id == org.id,
            ActivityType.code == normalized_code,
            ActivityType.id != activity_type.id,
        )
    )
    if duplicate:
        raise HTTPException(status_code=400, detail="Activity type code already exists")
    activity_type.code = normalized_code
    activity_type.name = normalized_name
    activity_type.category = category if category in ACTIVITY_CATEGORY_LABELS else "others"
    activity_type.is_chargeable = is_chargeable
    activity_type.is_active = is_active
    db.commit()
    return RedirectResponse(url=f"/{org_slug}/admin/activity-types", status_code=303)


@app.get("/{org_slug}/admin/holidays", response_class=HTMLResponse)
def admin_holidays_page(request: Request, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    must_be_admin(user)
    holidays = db.scalars(select(Holiday).where(Holiday.org_id == org.id).order_by(Holiday.holiday_date.desc())).all()
    today = date.today()
    upcoming_holidays = [holiday for holiday in holidays if holiday.holiday_date >= today]
    next_holiday = min(upcoming_holidays, key=lambda holiday: holiday.holiday_date, default=None)
    current_year_count = sum(1 for holiday in holidays if holiday.holiday_date.year == today.year)
    return templates.TemplateResponse(
        "admin_holidays.html",
        {
            "request": request,
            "org": org,
            "user": user,
            "holidays": holidays,
            "today": today,
            "next_holiday": next_holiday,
            "upcoming_count": len(upcoming_holidays),
            "current_year_count": current_year_count,
        },
    )


@app.post("/{org_slug}/admin/holidays")
def admin_create_holiday(
    org_slug: str,
    holiday_date: date = Form(...),
    name: str = Form(...),
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    must_be_admin(user)
    db.add(Holiday(org_id=org.id, holiday_date=holiday_date, name=name.strip()))
    db.commit()
    return RedirectResponse(url=f"/{org_slug}/admin/holidays", status_code=303)


@app.post("/{org_slug}/admin/holidays/{holiday_id}/delete")
def admin_delete_holiday(
    org_slug: str,
    holiday_id: int,
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    must_be_admin(user)
    holiday = db.get(Holiday, holiday_id)
    if not holiday or holiday.org_id != org.id:
        raise HTTPException(status_code=404, detail="Holiday not found")
    db.delete(holiday)
    db.commit()
    return RedirectResponse(url=f"/{org_slug}/admin/holidays", status_code=303)


@app.get("/{org_slug}/admin/settings", response_class=HTMLResponse)
def admin_settings_page(request: Request, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    must_be_admin(user)
    return templates.TemplateResponse(
        "admin_settings.html",
        {
            "request": request,
            "org": org,
            "user": user,
            "settings": get_org_settings(db, org.id),
            "weekdays": list(range(7)),
            "projects": org_projects(db, org.id),
            "activity_types": org_activity_types(db, org.id),
            "statuses": list(TaskStatus),
        },
    )


@app.post("/{org_slug}/admin/settings")
def admin_update_settings(
    org_slug: str,
    weekend_days: list[str] = Form([]),
    work_hours_per_day: Decimal = Form(...),
    default_project_id: str = Form(""),
    default_activity_type_id: str = Form(""),
    default_task_status: TaskStatus = Form(TaskStatus.NOT_STARTED),
    default_estimated_hours: str = Form(""),
    default_time_log_hours: str = Form(""),
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    must_be_admin(user)
    settings_obj = get_org_settings(db, org.id)
    project = db.get(Project, int(default_project_id)) if default_project_id.strip() else None
    if project and (project.org_id != org.id or not project.is_active):
        raise HTTPException(status_code=400, detail="Invalid default project")
    activity = db.get(ActivityType, int(default_activity_type_id)) if default_activity_type_id.strip() else None
    if activity and (activity.org_id != org.id or not activity.is_active):
        raise HTTPException(status_code=400, detail="Invalid default activity type")
    settings_obj.weekend_days = parse_weekend_days(weekend_days)
    settings_obj.work_hours_per_day = work_hours_per_day
    settings_obj.default_project_id = project.id if project else None
    settings_obj.default_activity_type_id = activity.id if activity else None
    settings_obj.default_task_status = default_task_status.value
    settings_obj.default_estimated_hours = Decimal(default_estimated_hours) if default_estimated_hours.strip() else None
    settings_obj.default_time_log_hours = Decimal(default_time_log_hours) if default_time_log_hours.strip() else None
    db.commit()
    return RedirectResponse(url=f"/{org_slug}/admin/settings", status_code=303)


@app.get("/{org_slug}/admin/tasks", response_class=HTMLResponse)
def admin_tasks_page(
    request: Request,
    assignee_id: str | None = None,
    project_id: str | None = None,
    status_filter: str | None = None,
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    must_be_admin(user)
    today = date.today()
    query = (
        select(Task)
        .join(User, Task.assigned_to == User.id)
        .where(
            Task.org_id == org.id,
            Task.is_archived.is_(False),
            User.org_id == org.id,
            User.is_active.is_(True),
        )
    )
    if assignee_id:
        query = query.where(Task.assigned_to == int(assignee_id))
    if project_id:
        query = query.where(Task.project_id == int(project_id))
    if status_filter:
        query = query.where(Task.status == TaskStatus(status_filter))
    tasks = db.scalars(query.order_by(Task.created_at.desc())).all()
    assignee_ids = sorted({task.assigned_to for task in tasks})
    people = db.scalars(
        select(User).where(User.org_id == org.id, User.is_active.is_(True), User.id.in_(assignee_ids)).order_by(User.full_name.asc())
    ).all() if assignee_ids else []
    total_logged_hours = sum(float(task.logged_hours or 0) for task in tasks)
    open_tasks = [task for task in tasks if task.status != TaskStatus.CLOSED]
    overdue_tasks = [task for task in open_tasks if task.end_date and task.end_date < today]
    backlog_tasks = [task for task in open_tasks if task.start_date is None and task.end_date is None]
    stalled_tasks = [task for task in tasks if task.status == TaskStatus.STALLED]
    completed_tasks = [task for task in tasks if task.status == TaskStatus.CLOSED]
    week_start, week_end = current_week_bounds(today)
    due_this_week = [
        task for task in open_tasks if task.end_date and week_start <= task.end_date <= week_end
    ]

    assignee_summary_map: dict[int, dict[str, Any]] = {}
    for person in people:
        assignee_summary_map[person.id] = {
            "person": person,
            "total": 0,
            "open": 0,
            "overdue": 0,
            "completed": 0,
            "logged_hours": 0.0,
        }
    for task in tasks:
        summary = assignee_summary_map.get(task.assigned_to)
        if not summary:
            continue
        summary["total"] += 1
        summary["logged_hours"] += float(task.logged_hours or 0)
        if task.status == TaskStatus.CLOSED:
            summary["completed"] += 1
        else:
            summary["open"] += 1
            if task.end_date and task.end_date < today:
                summary["overdue"] += 1
    assignee_summary = sorted(
        assignee_summary_map.values(),
        key=lambda item: (item["logged_hours"], item["overdue"], item["open"], item["completed"]),
        reverse=True,
    )

    return templates.TemplateResponse(
        "admin_tasks.html",
        {
            "request": request,
            "org": org,
            "user": user,
            "tasks": tasks,
            "people": people,
            "people_map": {person.id: person.full_name for person in people},
            "projects": all_org_projects(db, org.id),
            "statuses": list(TaskStatus),
            "assignee_id": int(assignee_id) if assignee_id else None,
            "project_id": int(project_id) if project_id else None,
            "status_filter": status_filter,
            "task_summary": {
                "total": len(tasks),
                "open": len(open_tasks),
                "overdue": len(overdue_tasks),
                "due_this_week": len(due_this_week),
                "backlog": len(backlog_tasks),
                "stalled": len(stalled_tasks),
                "completed": len(completed_tasks),
                "logged_hours": round(total_logged_hours, 2),
            },
            "assignee_summary": assignee_summary,
        },
    )


@app.get("/api/v1/admin/dashboard")
def api_admin_dashboard(org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    must_be_admin(user)
    today = date.today()
    month_start = today.replace(day=1)
    team = org_people(db, org.id)
    org_total_logged = Decimal("0")
    org_available = Decimal("0")
    for member in team:
        rates = compute_work_rate(db, org.id, member.id, month_start, today)
        org_total_logged += Decimal(str(rates["total_logged_hours"]))
        org_available += Decimal(str(rates["available_hours"]))
    total_rate = round(float((org_total_logged / org_available * 100) if org_available else Decimal("0")), 2)
    return {"employees": len(team), "org_total_rate": total_rate}
