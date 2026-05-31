from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum as SqlEnum, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Role(str, Enum):
    EMPLOYEE = "employee"
    MANAGER = "manager"
    ADMIN = "admin"


class TaskStatus(str, Enum):
    NOT_STARTED = "not_started"
    STARTED = "started"
    STALLED = "stalled"
    CLOSED = "closed"


class LeaveType(str, Enum):
    FULL = "full"
    HALF_AM = "half_am"
    HALF_PM = "half_pm"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    slug: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    settings: Mapped["OrgSettings"] = relationship(back_populates="organization", uselist=False, cascade="all, delete-orphan")
    users: Mapped[list["User"]] = relationship(back_populates="organization")
    departments: Mapped[list["Department"]] = relationship(back_populates="organization")
    projects: Mapped[list["Project"]] = relationship(back_populates="organization")
    activity_types: Mapped[list["ActivityType"]] = relationship(back_populates="organization")


class OrgSettings(Base):
    __tablename__ = "org_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), unique=True, index=True)
    weekend_days: Mapped[list[int]] = mapped_column(JSON, default=lambda: [5, 6])
    work_hours_per_day: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("8.00"))
    default_project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)
    default_activity_type_id: Mapped[int | None] = mapped_column(ForeignKey("activity_types.id"), nullable=True)
    default_task_status: Mapped[str] = mapped_column(String(30), default="not_started")
    default_estimated_hours: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    default_time_log_hours: Mapped[Decimal | None] = mapped_column(Numeric(4, 2), nullable=True)

    organization: Mapped[Organization] = relationship(back_populates="settings")


class Department(Base):
    __tablename__ = "departments"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_department_name_per_org"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(150))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    organization: Mapped[Organization] = relationship(back_populates="departments")
    users: Mapped[list["User"]] = relationship(back_populates="department")
    activity_types: Mapped[list["ActivityType"]] = relationship(back_populates="department")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(String(255))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), index=True, nullable=True)
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    role: Mapped[Role] = mapped_column(SqlEnum(Role), default=Role.EMPLOYEE)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    send_effort_reminder: Mapped[bool] = mapped_column(Boolean, default=True)
    force_password_change: Mapped[bool] = mapped_column(Boolean, default=False)
    temp_password_expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization: Mapped[Organization] = relationship(back_populates="users")
    department: Mapped[Department | None] = relationship(back_populates="users")


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_project_code_per_org"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(10))
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    project_task_sequence: Mapped[int] = mapped_column(default=0)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    organization: Mapped[Organization] = relationship(back_populates="projects")
    tasks: Mapped[list["Task"]] = relationship(back_populates="project")


class ProjectActivityType(Base):
    __tablename__ = "project_activity_types"
    __table_args__ = (UniqueConstraint("project_id", "activity_type_id", name="uq_project_activity_type"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    activity_type_id: Mapped[int] = mapped_column(ForeignKey("activity_types.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ActivityType(Base):
    __tablename__ = "activity_types"
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_activity_code_per_org"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), index=True, nullable=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(150))
    category: Mapped[str] = mapped_column(String(80), default="others")
    is_chargeable: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    organization: Mapped[Organization] = relationship(back_populates="activity_types")
    department: Mapped[Department | None] = relationship(back_populates="activity_types")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    assigned_to: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    activity_type_id: Mapped[int] = mapped_column(ForeignKey("activity_types.id"))
    status: Mapped[TaskStatus] = mapped_column(SqlEnum(TaskStatus), default=TaskStatus.NOT_STARTED)
    task_color: Mapped[str] = mapped_column(String(7), default="#22c55e")
    tags_text: Mapped[str] = mapped_column(String(1000), default="")
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    dashboard_rank: Mapped[int] = mapped_column(default=0)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    estimated_hours: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    logged_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0.00"))
    stalled_reason: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped[Project] = relationship(back_populates="tasks")
    time_logs: Mapped[list["TimeLog"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class WorkList(Base):
    __tablename__ = "work_lists"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    items: Mapped[list["WorkListItem"]] = relationship(back_populates="work_list", cascade="all, delete-orphan")


class WorkListItem(Base):
    __tablename__ = "work_list_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_list_id: Mapped[int] = mapped_column(ForeignKey("work_lists.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    notes: Mapped[str] = mapped_column(Text, default="")
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[str] = mapped_column(String(20), default="low")
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    work_list: Mapped[WorkList] = relationship(back_populates="items")


class PerformancePlan(Base):
    __tablename__ = "performance_plans"
    __table_args__ = (UniqueConstraint("org_id", "user_id", "year", name="uq_performance_plan_org_user_year"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    year: Mapped[int] = mapped_column(index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    goals: Mapped[list["PerformanceGoal"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class PerformanceGoal(Base):
    __tablename__ = "performance_goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    performance_plan_id: Mapped[int] = mapped_column(ForeignKey("performance_plans.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    weightage: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.00"))
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    plan: Mapped[PerformancePlan] = relationship(back_populates="goals")
    kpis: Mapped[list["PerformanceKPI"]] = relationship(back_populates="goal", cascade="all, delete-orphan")


class PerformanceKPI(Base):
    __tablename__ = "performance_kpis"

    id: Mapped[int] = mapped_column(primary_key=True)
    performance_goal_id: Mapped[int] = mapped_column(ForeignKey("performance_goals.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    weightage: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.00"))
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    goal: Mapped[PerformanceGoal] = relationship(back_populates="kpis")
    items: Mapped[list["PerformanceKPIItem"]] = relationship(back_populates="kpi", cascade="all, delete-orphan")


class PerformanceKPIItem(Base):
    __tablename__ = "performance_kpi_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    performance_kpi_id: Mapped[int] = mapped_column(ForeignKey("performance_kpis.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    kpi: Mapped[PerformanceKPI] = relationship(back_populates="items")


class TimeLog(Base):
    __tablename__ = "time_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    log_date: Mapped[date] = mapped_column(Date, default=date.today)
    hours: Mapped[Decimal] = mapped_column(Numeric(4, 2))
    notes: Mapped[str] = mapped_column(Text, default="No Details Provided")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    task: Mapped[Task] = relationship(back_populates="time_logs")


class WeeklyAISummary(Base):
    __tablename__ = "weekly_ai_summaries"
    __table_args__ = (UniqueConstraint("org_id", "user_id", "week_start", name="uq_weekly_ai_summary_org_user_week"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    week_start: Mapped[date] = mapped_column(Date, index=True)
    week_end: Mapped[date] = mapped_column(Date)
    summary_text: Mapped[str] = mapped_column(Text)
    selected_task_ids_json: Mapped[list[int]] = mapped_column(JSON, default=list)
    total_selected_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0.00"))
    input_snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    model_name: Mapped[str] = mapped_column(String(120), default="")
    prompt_version: Mapped[str] = mapped_column(String(40), default="")
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Leave(Base):
    __tablename__ = "leaves"
    __table_args__ = (UniqueConstraint("user_id", "leave_date", name="uq_leave_user_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    leave_date: Mapped[date] = mapped_column(Date)
    leave_type: Mapped[LeaveType] = mapped_column(SqlEnum(LeaveType), default=LeaveType.FULL)
    reason: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Holiday(Base):
    __tablename__ = "holidays"
    __table_args__ = (UniqueConstraint("org_id", "holiday_date", name="uq_holiday_org_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    holiday_date: Mapped[date] = mapped_column(Date)
    name: Mapped[str] = mapped_column(String(150))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
