from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ActivityType, Organization, OrgSettings, Project, Role, Task, TaskStatus, TimeLog, User
from app.security import hash_password


DEFAULT_ACTIVITY_TYPES = [
    ("SPEC", "Specification Writing", "product_management", True),
    ("RES", "Research", "others", True),
    ("DES", "Design", "software_development", True),
    ("DEV", "Development / Coding", "software_development", True),
    ("TEST", "Testing & QA", "software_development", True),
    ("REV", "Code Review", "software_development", True),
    ("BUG", "Bug Fix", "software_development", True),
    ("DOC", "Documentation", "project_delivery_management", True),
    ("DEP", "Deployment / DevOps", "infra_management", True),
    ("MTG", "Meeting / Discussion", "others", True),
    ("DEMO", "Demo Preparation & Delivery", "project_delivery_management", True),
    ("PLAN", "Planning", "project_delivery_management", True),
    ("STUDY", "Self Study / Learning", "others", False),
    ("TRAIN", "Training / Seminar / Workshop", "people_management", False),
    ("ADMIN", "Administrative Work", "it_tasks", False),
    ("SUPPORT", "Support / Helpdesk", "it_tasks", True),
    ("REVIEW", "Performance / Process Review", "people_management", False),
    ("OTHER", "Other", "others", False),
]


def seed_defaults(db: Session) -> None:
    existing = db.scalar(select(Organization).where(Organization.slug == "solulever"))
    if existing:
        return

    org = Organization(name="Solulever Technologies", slug="solulever")
    db.add(org)
    db.flush()

    db.add(OrgSettings(org_id=org.id, weekend_days=[5, 6], work_hours_per_day="8.00"))
    admin = User(
        org_id=org.id,
        email="admin@solulever.com",
        full_name="Org Admin",
        password_hash=hash_password("ChangeMe123"),
        role=Role.ADMIN,
        force_password_change=True,
    )
    db.add(admin)
    db.flush()

    project = Project(
        org_id=org.id,
        name="ProtrackLite Launch",
        code="PTL",
        description="Initial rollout project",
        created_by=admin.id,
        project_task_sequence=0,
    )
    db.add(project)

    for code, name, category, chargeable in DEFAULT_ACTIVITY_TYPES:
        db.add(
            ActivityType(
                org_id=org.id,
                code=code,
                name=name,
                category=category,
                is_chargeable=chargeable,
                is_default=True,
                is_active=True,
            )
        )

    db.commit()


def seed_demo_data(db: Session, org_slug: str = "solulever", task_count: int = 28) -> dict[str, int]:
    org = db.scalar(select(Organization).where(Organization.slug == org_slug))
    if not org:
        raise ValueError(f"Organization '{org_slug}' not found")

    admin = db.scalar(select(User).where(User.org_id == org.id, User.role == Role.ADMIN).order_by(User.id.asc()))
    if not admin:
        raise ValueError("Admin user not found for organization")

    settings_obj = db.scalar(select(OrgSettings).where(OrgSettings.org_id == org.id))
    if not settings_obj:
        settings_obj = OrgSettings(org_id=org.id, weekend_days=[5, 6], work_hours_per_day="8.00", default_task_status=TaskStatus.NOT_STARTED.value)
        db.add(settings_obj)
        db.flush()

    demo_users = [
        ("Aarav Mehta", "demo.aarav@solulever.com"),
        ("Diya Kapoor", "demo.diya@solulever.com"),
        ("Kabir Nair", "demo.kabir@solulever.com"),
        ("Mira Shah", "demo.mira@solulever.com"),
    ]
    people: list[User] = [admin]
    created_users = 0
    for full_name, email in demo_users:
        user = db.scalar(select(User).where(User.org_id == org.id, User.email == email))
        if not user:
            user = User(
                org_id=org.id,
                email=email,
                full_name=full_name,
                password_hash=hash_password("ChangeMe123"),
                role=Role.EMPLOYEE,
                is_active=True,
                force_password_change=False,
            )
            db.add(user)
            db.flush()
            created_users += 1
        people.append(user)

    demo_projects = [
        ("Client Delivery Sprint", "CDS", "Fast-moving client delivery and bug resolution."),
        ("Internal Platform Ops", "OPS", "Operational work, support, and internal improvements."),
        ("Research and Planning", "RNP", "Discovery, planning, documentation, and review."),
    ]
    created_projects = 0
    project_by_code: dict[str, Project] = {}
    for name, code, description in demo_projects:
        project = db.scalar(select(Project).where(Project.org_id == org.id, Project.code == code))
        if not project:
            project = Project(
                org_id=org.id,
                name=name,
                code=code,
                description=description,
                created_by=admin.id,
                is_active=True,
            )
            db.add(project)
            db.flush()
            created_projects += 1
        project_by_code[code] = project

    default_project = db.scalar(select(Project).where(Project.org_id == org.id, Project.code == "PTL"))
    if default_project:
        project_by_code["PTL"] = default_project

    activities = db.scalars(select(ActivityType).where(ActivityType.org_id == org.id, ActivityType.is_active.is_(True)).order_by(ActivityType.id.asc())).all()
    activity_by_name = {item.name: item for item in activities}
    activity_cycle = [
        "Development / Coding",
        "Testing & QA",
        "Bug Fix",
        "Documentation",
        "Research",
        "Planning",
        "Meeting / Discussion",
        "Support / Helpdesk",
    ]
    activity_objects = [activity_by_name[name] for name in activity_cycle if name in activity_by_name] or activities
    if not activity_objects:
        raise ValueError("No active activity types found")

    prefix = "Sample Task "
    existing_sample_tasks = db.scalars(select(Task).where(Task.org_id == org.id, Task.name.like(f"{prefix}%"))).all()
    existing_names = {task.name for task in existing_sample_tasks}
    today = date.today()
    project_sequence = ["PTL", "CDS", "OPS", "RNP"]
    statuses = [TaskStatus.NOT_STARTED, TaskStatus.STARTED, TaskStatus.STALLED, TaskStatus.CLOSED]
    created_tasks = 0

    for index in range(task_count):
        status = statuses[index % len(statuses)]
        assignee = people[index % len(people)]
        project = project_by_code.get(project_sequence[index % len(project_sequence)], next(iter(project_by_code.values())))
        activity = activity_objects[index % len(activity_objects)]
        start_date = today + timedelta(days=-18 + index)
        end_date = start_date + timedelta(days=2 + (index % 6))
        if index % 5 == 0:
            end_date = today - timedelta(days=3 + (index % 4))
        elif index % 5 == 1:
            end_date = today + timedelta(days=1 + (index % 6))
        elif index % 5 == 2:
            end_date = today
        elif index % 5 == 3:
            end_date = today + timedelta(days=8 + (index % 3))

        task_name = f"{prefix}{index + 1:02d} - {status.value.replace('_', ' ').title()}"
        if task_name in existing_names:
            continue

        project.project_task_sequence += 1
        task = Task(
            task_id=f"{project.code}{project.project_task_sequence:04d}",
            org_id=org.id,
            project_id=project.id,
            assigned_to=assignee.id,
            created_by=admin.id,
            name=task_name,
            description=f"Demo task {index + 1:02d} with mixed dates and statuses for reviewing admin dashboards, reports, and task flows.",
            activity_type_id=activity.id,
            status=status,
            is_private=(index % 9 == 0),
            start_date=start_date,
            end_date=end_date,
            estimated_hours=Decimal(str(round(2.0 + (index % 7) * 1.5, 2))),
            closed_at=datetime.utcnow() - timedelta(days=index % 4) if status == TaskStatus.CLOSED else None,
        )
        db.add(task)
        db.flush()

        if status != TaskStatus.NOT_STARTED:
            log_count = 1 if status == TaskStatus.STARTED else 2
            for log_index in range(log_count):
                hours = Decimal("1.50") + Decimal(str(log_index))
                log_date = max(start_date, today - timedelta(days=log_index + (index % 5)))
                db.add(
                    TimeLog(
                        task_id=task.id,
                        user_id=assignee.id,
                        log_date=log_date,
                        hours=hours,
                        notes=f"Demo progress log {log_index + 1} for {task_name}.",
                    )
                )
                task.logged_hours = (task.logged_hours or Decimal("0.00")) + hours

        created_tasks += 1

    if getattr(settings_obj, "default_project_id", None) is None and "PTL" in project_by_code:
        settings_obj.default_project_id = project_by_code["PTL"].id
    if getattr(settings_obj, "default_activity_type_id", None) is None:
        settings_obj.default_activity_type_id = activity_objects[0].id
    settings_obj.default_task_status = TaskStatus.STARTED.value
    settings_obj.default_estimated_hours = Decimal("4.00")
    settings_obj.default_time_log_hours = Decimal("1.50")

    db.commit()
    return {
        "created_users": created_users,
        "created_projects": created_projects,
        "created_tasks": created_tasks,
        "total_people": len(people),
    }
