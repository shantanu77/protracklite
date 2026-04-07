from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from sqlalchemy import JSON, Boolean, Date, DateTime, Enum as SqlEnum, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Role(str, Enum):
    EMPLOYEE = "employee"
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
    projects: Mapped[list["Project"]] = relationship(back_populates="organization")
    activity_types: Mapped[list["ActivityType"]] = relationship(back_populates="organization")


class OrgSettings(Base):
    __tablename__ = "org_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), unique=True, index=True)
    weekend_days: Mapped[list[int]] = mapped_column(JSON, default=lambda: [5, 6])
    work_hours_per_day: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=Decimal("8.00"))

    organization: Mapped[Organization] = relationship(back_populates="settings")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(SqlEnum(Role), default=Role.EMPLOYEE)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    force_password_change: Mapped[bool] = mapped_column(Boolean, default=False)
    temp_password_expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization: Mapped[Organization] = relationship(back_populates="users")


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


class ActivityType(Base):
    __tablename__ = "activity_types"
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_activity_code_per_org"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(150))
    is_chargeable: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    organization: Mapped[Organization] = relationship(back_populates="activity_types")


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
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    start_date: Mapped[date] = mapped_column(Date, default=date.today)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    estimated_hours: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    logged_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0.00"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped[Project] = relationship(back_populates="tasks")
    time_logs: Mapped[list["TimeLog"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class TimeLog(Base):
    __tablename__ = "time_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    log_date: Mapped[date] = mapped_column(Date, default=date.today)
    hours: Mapped[Decimal] = mapped_column(Numeric(4, 2))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    task: Mapped[Task] = relationship(back_populates="time_logs")


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
