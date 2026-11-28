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


class SharedTaskStatus(str, Enum):
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    WORK_DONE = "work_done"
    ACCEPTED = "accepted"
    REWORK_NEEDED = "rework_needed"
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
    receive_team_utilization_email: Mapped[bool] = mapped_column(Boolean, default=False)
    force_password_change: Mapped[bool] = mapped_column(Boolean, default=False)
    temp_password_expires: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    avatar_128_url: Mapped[str] = mapped_column(String(255), default="")
    avatar_24_url: Mapped[str] = mapped_column(String(255), default="")
    avatar_emoji: Mapped[str] = mapped_column(String(16), default="")
    location: Mapped[str] = mapped_column(String(120), default="Noida")
    employment_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    employment_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    zoho_employee_id: Mapped[str] = mapped_column(String(40), default="")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization: Mapped[Organization] = relationship(back_populates="users")
    department: Mapped[Department | None] = relationship(back_populates="users")


class AttendanceRegularization(Base):
    __tablename__ = "attendance_regularizations"
    __table_args__ = (UniqueConstraint("org_id", "user_id", "attendance_date", name="uq_attendance_regularization_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    manager_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    attendance_date: Mapped[date] = mapped_column(Date, index=True)
    start_time: Mapped[str] = mapped_column(String(5), default="10:00")
    end_time: Mapped[str] = mapped_column(String(5), default="19:00")
    location: Mapped[str] = mapped_column(String(30), default="remote")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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


class InventoryItem(Base):
    __tablename__ = "inventory_items"
    __table_args__ = (UniqueConstraint("org_id", "asset_tag", name="uq_inventory_asset_tag_per_org"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    asset_tag: Mapped[str] = mapped_column(String(100))
    asset_type: Mapped[str] = mapped_column(String(20), default="hardware")
    asset_category: Mapped[str] = mapped_column(String(80), default="")
    name: Mapped[str] = mapped_column(String(200))
    manufacturer: Mapped[str] = mapped_column(String(120), default="")
    model: Mapped[str] = mapped_column(String(120), default="")
    serial_number: Mapped[str] = mapped_column(String(160), default="")
    license_reference: Mapped[str] = mapped_column(String(180), default="")
    configuration: Mapped[str] = mapped_column(Text, default="", nullable=True)
    os_installed: Mapped[str] = mapped_column(String(120), default="")
    current_status: Mapped[str] = mapped_column(String(40), default="In Stock")
    purchase_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    warranty_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InventoryAllocation(Base):
    __tablename__ = "inventory_allocations"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    inventory_item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    allocated_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    allocated_at: Mapped[date] = mapped_column(Date, default=date.today)
    returned_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    purpose: Mapped[str] = mapped_column(Text, default="", nullable=True)
    condition_at_issue: Mapped[str] = mapped_column(String(80), default="")
    accessories_issued: Mapped[str] = mapped_column(Text, default="", nullable=True)
    employee_identifier: Mapped[str] = mapped_column(String(80), default="")
    designation_snapshot: Mapped[str] = mapped_column(String(120), default="")
    department_snapshot: Mapped[str] = mapped_column(String(120), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InventoryAllocationEvent(Base):
    __tablename__ = "inventory_allocation_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    inventory_item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    related_inventory_item_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_items.id"), nullable=True, index=True)
    allocation_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    previous_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    event_date: Mapped[date] = mapped_column(Date, index=True)
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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
    assigned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    name: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    activity_type_id: Mapped[int] = mapped_column(ForeignKey("activity_types.id"))
    status: Mapped[TaskStatus] = mapped_column(SqlEnum(TaskStatus), default=TaskStatus.NOT_STARTED)
    tags_text: Mapped[str] = mapped_column(String(1000), default="")
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    shared_status: Mapped[str] = mapped_column(String(30), default="")
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    dashboard_rank: Mapped[int] = mapped_column(default=0)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    estimated_hours: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    complexity_weight: Mapped[Decimal] = mapped_column(Numeric(2, 1), default=Decimal("1.0"))
    is_high_priority: Mapped[bool] = mapped_column(Boolean, default=False)
    rework_count: Mapped[int] = mapped_column(default=0)
    logged_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0.00"))
    stalled_reason: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    project: Mapped[Project] = relationship(back_populates="tasks")
    assigned_by_user: Mapped[User | None] = relationship(foreign_keys=[assigned_by])
    time_logs: Mapped[list["TimeLog"]] = relationship(back_populates="task", cascade="all, delete-orphan")
    comments: Mapped[list["TaskComment"]] = relationship(back_populates="task", cascade="all, delete-orphan")


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
    members: Mapped[list["WorkListMember"]] = relationship(back_populates="work_list", cascade="all, delete-orphan")
    comments: Mapped[list["WorkListComment"]] = relationship(back_populates="work_list", cascade="all, delete-orphan")


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
    completed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    work_list: Mapped[WorkList] = relationship(back_populates="items")


class WorkListMember(Base):
    __tablename__ = "work_list_members"
    __table_args__ = (UniqueConstraint("work_list_id", "user_id", name="uq_work_list_member"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    work_list_id: Mapped[int] = mapped_column(ForeignKey("work_lists.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    work_list: Mapped[WorkList] = relationship(back_populates="members")


class WorkListComment(Base):
    __tablename__ = "work_list_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_list_id: Mapped[int] = mapped_column(ForeignKey("work_lists.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    work_list: Mapped[WorkList] = relationship(back_populates="comments")


class WorkListActivityDigestDelivery(Base):
    __tablename__ = "work_list_activity_digest_deliveries"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", "digest_date", name="uq_work_list_activity_digest_recipient_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    digest_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default="sent")
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EmailDeliveryRun(Base):
    __tablename__ = "email_delivery_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    report_type: Mapped[str] = mapped_column(String(60), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="running")
    target_count: Mapped[int] = mapped_column(default=0)
    sent_count: Mapped[int] = mapped_column(default=0)
    failed_count: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EmailDeliveryLog(Base):
    __tablename__ = "email_delivery_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("email_delivery_runs.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    recipient_email: Mapped[str] = mapped_column(String(255), index=True)
    subject: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default="pending")
    attempted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str] = mapped_column(Text, default="")


class PerformancePlan(Base):
    __tablename__ = "performance_plans"
    __table_args__ = (UniqueConstraint("org_id", "user_id", "year", name="uq_performance_plan_org_user_year"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    revision: Mapped[int] = mapped_column(default=0, server_default="0")
    year: Mapped[int] = mapped_column(index=True)
    cycle_label: Mapped[str] = mapped_column(String(40), default="")
    cycle_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    cycle_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reviewer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    self_assessment: Mapped[str] = mapped_column(Text, default="")
    reviewer_assessment: Mapped[str] = mapped_column(Text, default="")
    final_rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    goals: Mapped[list["PerformanceGoal"]] = relationship(back_populates="plan", cascade="all, delete-orphan")
    comments: Mapped[list["PerformanceComment"]] = relationship(back_populates="plan", cascade="all, delete-orphan")
    events: Mapped[list["PerformanceEvent"]] = relationship(back_populates="plan", cascade="all, delete-orphan")


class PerformanceGoal(Base):
    __tablename__ = "performance_goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    performance_plan_id: Mapped[int] = mapped_column(ForeignKey("performance_plans.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    kra_type: Mapped[str] = mapped_column(String(60), default="delivery_execution")
    weightage: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.00"))
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    plan: Mapped[PerformancePlan] = relationship(back_populates="goals")
    members: Mapped[list["PerformanceGoalMember"]] = relationship(cascade="all, delete-orphan")
    kpis: Mapped[list["PerformanceKPI"]] = relationship(back_populates="goal", cascade="all, delete-orphan")


class PerformanceGoalMember(Base):
    __tablename__ = "performance_goal_members"

    goal_id: Mapped[int] = mapped_column(ForeignKey("performance_goals.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True, index=True)
    invited_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PerformanceDigestDelivery(Base):
    __tablename__ = "performance_digest_deliveries"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    digest_date: Mapped[date] = mapped_column(Date, primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime)


class PerformanceKPI(Base):
    __tablename__ = "performance_kpis"

    id: Mapped[int] = mapped_column(primary_key=True)
    performance_goal_id: Mapped[int] = mapped_column(ForeignKey("performance_goals.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    measurement_type: Mapped[str] = mapped_column(String(30), default="checklist")
    unit: Mapped[str] = mapped_column(String(40), default="")
    baseline_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    target_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    actual_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    approved_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    measurement_frequency: Mapped[str] = mapped_column(String(30), default="annual")
    owner_update: Mapped[str] = mapped_column(Text, default="")
    weightage: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0.00"))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    goal: Mapped[PerformanceGoal] = relationship(back_populates="kpis")
    items: Mapped[list["PerformanceKPIItem"]] = relationship(back_populates="kpi", cascade="all, delete-orphan")
    evidence: Mapped[list["PerformanceEvidence"]] = relationship(back_populates="kpi", cascade="all, delete-orphan")


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
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    kpi: Mapped[PerformanceKPI] = relationship(back_populates="items")


class PerformanceEvidence(Base):
    __tablename__ = "performance_evidence"

    id: Mapped[int] = mapped_column(primary_key=True)
    performance_kpi_id: Mapped[int] = mapped_column(ForeignKey("performance_kpis.id"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    work_list_item_id: Mapped[int | None] = mapped_column(ForeignKey("work_list_items.id"), nullable=True, index=True)
    external_url: Mapped[str] = mapped_column(String(1000), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    kpi: Mapped[PerformanceKPI] = relationship(back_populates="evidence")


class PerformanceComment(Base):
    __tablename__ = "performance_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    performance_plan_id: Mapped[int] = mapped_column(ForeignKey("performance_plans.id"), index=True)
    performance_goal_id: Mapped[int | None] = mapped_column(ForeignKey("performance_goals.id"), nullable=True, index=True)
    performance_kpi_id: Mapped[int | None] = mapped_column(ForeignKey("performance_kpis.id"), nullable=True, index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    comment_type: Mapped[str] = mapped_column(String(30), default="comment")
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    plan: Mapped[PerformancePlan] = relationship(back_populates="comments")


class PerformanceEvent(Base):
    __tablename__ = "performance_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    performance_plan_id: Mapped[int] = mapped_column(ForeignKey("performance_plans.id"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    plan: Mapped[PerformancePlan] = relationship(back_populates="events")


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


class TaskComment(Base):
    __tablename__ = "task_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    comment_type: Mapped[str] = mapped_column(String(30), default="comment")
    body: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    task: Mapped[Task] = relationship(back_populates="comments")


class UserAnnouncementView(Base):
    __tablename__ = "user_announcement_views"
    __table_args__ = (UniqueConstraint("user_id", "announcement_key", name="uq_user_announcement_view"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    announcement_key: Mapped[str] = mapped_column(String(120), index=True)
    viewed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TodayAlertAcknowledgement(Base):
    __tablename__ = "today_alert_acknowledgements"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", "alert_key", name="uq_today_alert_ack_org_user_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    alert_key: Mapped[str] = mapped_column(String(180), index=True)
    action: Mapped[str] = mapped_column(String(20), default="acknowledged")
    acknowledged_on: Mapped[date] = mapped_column(Date, index=True)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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


class MonthlyWorkReport(Base):
    __tablename__ = "monthly_work_reports"
    __table_args__ = (UniqueConstraint("org_id", "user_id", "month_start", name="uq_monthly_work_report_org_user_month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    month_start: Mapped[date] = mapped_column(Date, index=True)
    month_end: Mapped[date] = mapped_column(Date)
    facts_json: Mapped[dict] = mapped_column(JSON, default=dict)
    summary_text: Mapped[str] = mapped_column(Text, default="")
    rating: Mapped[Decimal | None] = mapped_column(Numeric(2, 1), nullable=True)
    manager_comment: Mapped[str] = mapped_column(Text, default="")
    manager_comment_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    model_name: Mapped[str] = mapped_column(String(120), default="")
    prompt_version: Mapped[str] = mapped_column(String(40), default="")
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WeeklyTaskPlan(Base):
    __tablename__ = "weekly_task_plans"
    __table_args__ = (UniqueConstraint("org_id", "user_id", "week_start", name="uq_weekly_task_plan_org_user_week"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    week_start: Mapped[date] = mapped_column(Date, index=True)
    week_end: Mapped[date] = mapped_column(Date)
    focus_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WeeklyTaskPlanItem(Base):
    __tablename__ = "weekly_task_plan_items"
    __table_args__ = (UniqueConstraint("weekly_task_plan_id", "task_id", name="uq_weekly_task_plan_item_task"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    weekly_task_plan_id: Mapped[int] = mapped_column(ForeignKey("weekly_task_plans.id"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    planned_note: Mapped[str] = mapped_column(String(255), default="")
    sort_order: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Leave(Base):
    __tablename__ = "leaves"
    __table_args__ = (UniqueConstraint("user_id", "leave_date", name="uq_leave_user_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    leave_date: Mapped[date] = mapped_column(Date)
    leave_type: Mapped[LeaveType] = mapped_column(SqlEnum(LeaveType), default=LeaveType.FULL)
    leave_category: Mapped[str] = mapped_column(String(30), default="general")
    reason: Mapped[str] = mapped_column(String(255), default="")
    backup_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    request_group: Mapped[str] = mapped_column(String(40), default="", index=True)
    zoho_leave_id: Mapped[str] = mapped_column(String(40), default="", index=True)
    zoho_sync_status: Mapped[str] = mapped_column(String(20), default="pending")
    zoho_sync_error: Mapped[str] = mapped_column(String(255), default="")
    zoho_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Holiday(Base):
    __tablename__ = "holidays"
    __table_args__ = (UniqueConstraint("org_id", "holiday_date", name="uq_holiday_org_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    holiday_date: Mapped[date] = mapped_column(Date)
    name: Mapped[str] = mapped_column(String(150))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CapacityZohoSnapshot(Base):
    """Shared organizational leave snapshot, independent of the viewing user."""
    __tablename__ = "capacity_zoho_snapshots"
    __table_args__ = (UniqueConstraint("org_id", "year", "month", name="uq_capacity_zoho_org_month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    year: Mapped[int] = mapped_column()
    month: Mapped[int] = mapped_column()
    synced_at: Mapped[datetime] = mapped_column(DateTime)
    member_ids_json: Mapped[list[int]] = mapped_column(JSON, default=list)
    leave_days_json: Mapped[list[dict]] = mapped_column(JSON, default=list)


class CapacityZohoSyncRun(Base):
    __tablename__ = "capacity_zoho_sync_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="idle")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str] = mapped_column(String(500), default="")


class LeaveApproval(Base):
    """Imported request and the authoritative approval made in ProTrack."""
    __tablename__ = "leave_approvals"
    __table_args__ = (UniqueConstraint("org_id", "user_id", "zoho_leave_id", name="uq_local_leave_approval"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    zoho_leave_id: Mapped[str] = mapped_column(String(120))
    request_json: Mapped[dict] = mapped_column(JSON, default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64))
    source_status: Mapped[str] = mapped_column(String(40))
    approved_fingerprint: Mapped[str] = mapped_column(String(64), default="")
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TodayPeopleSnapshot(Base):
    """Shared daily attendance and leave, refreshed explicitly by any employee."""
    __tablename__ = "today_people_snapshots"
    __table_args__ = (UniqueConstraint("org_id", "day", name="uq_today_people_org_day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    day: Mapped[date] = mapped_column(Date)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    people_json: Mapped[list[dict]] = mapped_column(JSON, default=list)
    unmapped_count: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="idle")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str] = mapped_column(String(500), default="")
