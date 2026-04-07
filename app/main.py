from __future__ import annotations

import smtplib
from datetime import date, datetime, timedelta
from decimal import Decimal
from email.message import EmailMessage
from typing import Any

import bleach
import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
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
from app.reports import compute_work_rate, current_week_bounds, monday_report, previous_week_bounds
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

SAFE_TAGS = ["p", "b", "strong", "i", "em", "ul", "ol", "li", "br", "a", "code", "pre"]


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    db = next(get_db())
    try:
        seed_defaults(db)
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


def verify_hcaptcha_token(token: str, remote_ip: str | None = None) -> tuple[bool, list[str]]:
    if not settings.hcaptcha_secret:
        return False, ["missing-input-secret"]

    payload = {
        "secret": settings.hcaptcha_secret,
        "response": token,
    }
    if remote_ip:
        payload["remoteip"] = remote_ip
    if settings.hcaptcha_site_key:
        payload["sitekey"] = settings.hcaptcha_site_key

    try:
        response = httpx.post("https://api.hcaptcha.com/siteverify", data=payload, timeout=10.0)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError:
        return False, ["captcha-verification-failed"]

    return bool(data.get("success")), data.get("error-codes", [])


def issue_temporary_password(user: User) -> str:
    temp_password = generate_temp_password()
    user.password_hash = hash_password(temp_password)
    user.force_password_change = True
    user.temp_password_expires = datetime.utcnow() + timedelta(hours=24)
    return temp_password


def get_org_or_404(db: Session, org_slug: str) -> Organization:
    org = db.scalar(select(Organization).where(Organization.slug == org_slug, Organization.is_active.is_(True)))
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    return org


def issue_auth_cookies(response: RedirectResponse | JSONResponse, user: User, org_slug: str) -> None:
    subject = f"{user.id}:{org_slug}"
    response.set_cookie("access_token", create_access_token(subject), httponly=True, samesite="lax")
    response.set_cookie("refresh_token", create_refresh_token(subject), httponly=True, samesite="lax")


def clear_auth_cookies(response: RedirectResponse | JSONResponse) -> None:
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")


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


def dashboard_payload(db: Session, org: Organization, user: User) -> dict[str, Any]:
    monday, friday = current_week_bounds()
    tasks = db.scalars(
        select(Task)
        .where(
            Task.org_id == org.id,
            Task.assigned_to == user.id,
            or_(
                Task.status != TaskStatus.CLOSED,
                Task.start_date.between(monday, friday),
                Task.end_date.between(monday, friday),
            ),
        )
        .order_by(Task.status.asc(), Task.start_date.asc(), Task.created_at.desc())
    ).all()

    groups = {"today": [], "week": [], "overdue": [], "pending": []}
    today = date.today()
    for task in tasks:
        if task.start_date == today or task.end_date == today:
            groups["today"].append(task)
        elif task.end_date and task.end_date < today and task.status != TaskStatus.CLOSED:
            groups["overdue"].append(task)
        elif monday <= task.start_date <= friday:
            groups["week"].append(task)
        else:
            groups["pending"].append(task)

    return groups


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


def user_tasks(db: Session, org_id: int, user_id: int) -> list[Task]:
    return db.scalars(
        select(Task)
        .where(Task.org_id == org_id, Task.assigned_to == user_id)
        .order_by(Task.status.asc(), Task.start_date.desc(), Task.created_at.desc())
    ).all()


def get_org_settings(db: Session, org_id: int) -> OrgSettings:
    settings_obj = db.scalar(select(OrgSettings).where(OrgSettings.org_id == org_id))
    if settings_obj:
        return settings_obj
    settings_obj = OrgSettings(org_id=org_id, weekend_days=[5, 6], work_hours_per_day=Decimal("8.00"))
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
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "org": org,
            "error": None,
            "forgot_error": None,
            "forgot_success": None,
            "hcaptcha_site_key": settings.hcaptcha_site_key,
        },
    )


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
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "org": org,
                "error": "Invalid email or password",
                "forgot_error": None,
                "forgot_success": None,
                "hcaptcha_site_key": settings.hcaptcha_site_key,
            },
            status_code=400,
        )

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
    response.set_cookie("access_token", create_access_token(subject), httponly=True, samesite="lax")
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
    h_captcha_response: str = Form("", alias="h-captcha-response"),
    db: Session = Depends(get_db),
):
    org = get_org_or_404(db, org_slug)

    if not settings.hcaptcha_site_key or not settings.hcaptcha_secret:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "org": org,
                "error": None,
                "forgot_error": "Forgot password is not configured yet.",
                "forgot_success": None,
                "hcaptcha_site_key": settings.hcaptcha_site_key,
            },
            status_code=400,
        )

    if not h_captcha_response:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "org": org,
                "error": None,
                "forgot_error": "Please complete the captcha challenge.",
                "forgot_success": None,
                "hcaptcha_site_key": settings.hcaptcha_site_key,
            },
            status_code=400,
        )

    verified, error_codes = verify_hcaptcha_token(h_captcha_response, request.client.host if request.client else None)
    if not verified:
        return templates.TemplateResponse(
            "login.html",
            {
                "request": request,
                "org": org,
                "error": None,
                "forgot_error": "Captcha verification failed. Please try again.",
                "forgot_success": None,
                "hcaptcha_site_key": settings.hcaptcha_site_key,
                "captcha_errors": error_codes,
            },
            status_code=400,
        )

    user = db.scalar(select(User).where(User.email == email.strip().lower(), User.org_id == org.id))
    if user:
        temp_password = issue_temporary_password(user)
        db.commit()
        try:
            send_email(user.email, "ProtrackLite temporary password", f"Your temporary password is: {temp_password}")
        except Exception:
            print(f"[forgot-password] {user.email}: {temp_password}")

    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "org": org,
            "error": None,
            "forgot_error": None,
            "forgot_success": "If the account exists, a new temporary password has been sent.",
            "hcaptcha_site_key": settings.hcaptcha_site_key,
        },
    )


@app.get("/{org_slug}/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "org": org,
            "user": user,
            "groups": dashboard_payload(db, org, user),
        },
    )


@app.get("/{org_slug}/tasks/new", response_class=HTMLResponse)
def new_task_page(request: Request, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
    return templates.TemplateResponse(
        "task_form.html",
        {
            "request": request,
            "org": org,
            "user": user,
            "task": None,
            "projects": org_projects(db, org.id),
            "activity_types": org_activity_types(db, org.id),
            "statuses": list(TaskStatus),
            "today": date.today(),
            "tasks": user_tasks(db, org.id, user.id),
        },
    )


@app.post("/{org_slug}/tasks/new")
def create_task_page(
    org_slug: str,
    project_id: int = Form(...),
    name: str = Form(...),
    activity_type_id: int = Form(...),
    description: str = Form(""),
    start_date: date = Form(...),
    end_date: date | None = Form(None),
    estimated_hours: Decimal | None = Form(None),
    status_value: TaskStatus = Form(TaskStatus.NOT_STARTED, alias="status"),
    is_private: bool = Form(False),
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    project = db.get(Project, project_id)
    if not project or project.org_id != org.id:
        raise HTTPException(status_code=404, detail="Project not found")

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
        is_private=is_private,
        start_date=start_date,
        end_date=end_date,
        estimated_hours=estimated_hours,
        closed_at=datetime.utcnow() if status_value == TaskStatus.CLOSED else None,
    )
    db.add(task)
    db.commit()
    return RedirectResponse(url=f"/{org_slug}/tasks/{task.task_id}", status_code=303)


@app.get("/{org_slug}/tasks/{task_code}", response_class=HTMLResponse)
def task_detail_page(request: Request, org_slug: str, task_code: str, org_user: tuple[Organization, User] = Depends(get_org_user), db: Session = Depends(get_db)):
    org, user = org_user
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
            "statuses": list(TaskStatus),
            "people": org_people(db, org.id),
        },
    )


@app.post("/{org_slug}/tasks/{task_code}")
def update_task_page(
    org_slug: str,
    task_code: str,
    project_id: int = Form(...),
    name: str = Form(...),
    activity_type_id: int = Form(...),
    description: str = Form(""),
    start_date: date = Form(...),
    end_date: date | None = Form(None),
    estimated_hours: Decimal | None = Form(None),
    status_value: TaskStatus = Form(..., alias="status"),
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
    task.project_id = project_id
    task.name = name
    task.activity_type_id = activity_type_id
    task.description = sanitize_html(description)
    task.start_date = start_date
    task.end_date = end_date
    task.estimated_hours = estimated_hours
    task.status = status_value
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
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    task = db.scalar(select(Task).where(Task.task_id == task_code, Task.org_id == org.id, Task.assigned_to == user.id))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    db.add(TimeLog(task_id=task.id, user_id=user.id, log_date=log_date, hours=hours, notes=notes))
    db.flush()
    task.logged_hours = db.scalar(select(func.coalesce(func.sum(TimeLog.hours), 0)).where(TimeLog.task_id == task.id))
    db.commit()
    return RedirectResponse(url=f"/{org_slug}/tasks/{task_code}", status_code=303)


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
        query = query.where(or_(Task.name.ilike(f"%{q}%"), Task.task_id.ilike(f"%{q}%")))
    tasks = db.scalars(query.order_by(Task.created_at.desc())).all()
    return [
        {
            "task_id": task.task_id,
            "name": task.name,
            "status": task.status.value,
            "logged_hours": float(task.logged_hours or 0),
            "estimated_hours": float(task.estimated_hours) if task.estimated_hours is not None else None,
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
        is_private=payload.get("is_private", False),
        start_date=date.fromisoformat(payload.get("start_date", date.today().isoformat())),
        end_date=date.fromisoformat(payload["end_date"]) if payload.get("end_date") else None,
        estimated_hours=payload.get("estimated_hours"),
    )
    db.add(task)
    db.commit()
    return {"task_id": task.task_id}


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
        "logged_hours": float(task.logged_hours or 0),
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
    if "status" in payload:
        task.status = TaskStatus(payload["status"])
        task.closed_at = datetime.utcnow() if task.status == TaskStatus.CLOSED else None
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
        "pending": [item.task_id for item in report["pending"]],
        "completed": [item.task_id for item in report["completed"]],
        "planned": [item.task_id for item in report["planned"]],
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
    project = Project(
        org_id=org.id,
        name=name.strip(),
        code=code.strip().upper(),
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
    project.name = name.strip()
    project.code = code.strip().upper()
    project.description = description.strip()
    project.is_active = is_active
    db.commit()
    return RedirectResponse(url=f"/{org_slug}/admin/projects", status_code=303)


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
        {"request": request, "org": org, "user": user, "settings": get_org_settings(db, org.id), "weekdays": list(range(7))},
    )


@app.post("/{org_slug}/admin/settings")
def admin_update_settings(
    org_slug: str,
    weekend_days: list[str] = Form([]),
    work_hours_per_day: Decimal = Form(...),
    org_user: tuple[Organization, User] = Depends(get_org_user),
    db: Session = Depends(get_db),
):
    org, user = org_user
    must_be_admin(user)
    settings_obj = get_org_settings(db, org.id)
    settings_obj.weekend_days = parse_weekend_days(weekend_days)
    settings_obj.work_hours_per_day = work_hours_per_day
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
    query = select(Task).where(Task.org_id == org.id)
    if assignee_id:
        query = query.where(Task.assigned_to == int(assignee_id))
    if project_id:
        query = query.where(Task.project_id == int(project_id))
    if status_filter:
        query = query.where(Task.status == TaskStatus(status_filter))
    tasks = db.scalars(query.order_by(Task.created_at.desc())).all()
    return templates.TemplateResponse(
        "admin_tasks.html",
        {
            "request": request,
            "org": org,
            "user": user,
            "tasks": tasks,
            "people": org_people(db, org.id),
            "people_map": {person.id: person.full_name for person in org_people(db, org.id)},
            "projects": all_org_projects(db, org.id),
            "statuses": list(TaskStatus),
            "assignee_id": int(assignee_id) if assignee_id else None,
            "project_id": int(project_id) if project_id else None,
            "status_filter": status_filter,
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
