import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ActivityType, Department, Organization, OrgSettings, Project, Role, Task, TaskStatus, TimeLog, User
from app.security import hash_password


DEFAULT_DEPARTMENTS = (
    "Product",
    "Engineering",
    "Delivery(Customer Activation)",
    "Techops/Devops",
    "Support",
    "IT",
    "QA",
    "Human Resource",
)

SOLULEVER_DEPARTMENT_ASSIGNMENTS = {
    "divya.meghwanshi@solulever.com": "Product",
    "bhupesh.joshi@solulever.com": "Product",
    "shantanu.singh@solulever.com": "Product",
    "karamveer.sharma@solulever.com": "IT",
    "devendra.mule@solulever.com": "Delivery(Customer Activation)",
    "shrey.srivastava@solulever.com": "Delivery(Customer Activation)",
    "jitin.gera@solulever.com": "Delivery(Customer Activation)",
    "pragya.srivastava@solulever.com": "Human Resource",
}

SOLULEVER_REQUIRED_USERS = {
    "pragya.srivastava@solulever.com": "Pragya Srivastava",
}

DEPARTMENT_ACTIVITY_DEFINITIONS = {
    "Product": [
        ("PRD-MKT", "Market Research & Discovery", "product_management", True),
        ("PRD-ROAD", "Roadmap Planning & Strategy", "product_management", True),
        ("PRD-SPEC", "PRD Writing & Feature Spec", "product_management", True),
        ("PRD-UX", "UI/UX Wireframing & Design Review", "product_management", True),
        ("PRD-BACK", "Backlog Grooming & Prioritization", "product_management", True),
        ("PRD-TEST", "User Testing & Feedback Analysis", "product_management", True),
        ("PRD-ADM", "General: Internal Meetings & Admin", "others", False),
        ("PRD-RSK", "General: Research & Skill Development", "others", False),
        ("PRD-MENT", "General: Team Support & Mentorship", "people_management", False),
        ("PRD-ADH", "General: Unplanned / Ad-hoc Requests", "others", True),
    ],
    "Engineering": [
        ("ENG-FEAT", "New Feature Development", "software_development", True),
        ("ENG-BUG", "Bug Fixing & Hotfixes", "software_development", True),
        ("ENG-REV", "Code Review & Refactoring", "software_development", True),
        ("ENG-ARCH", "Technical Architecture & Design", "software_development", True),
        ("ENG-API", "API Integration & Documentation", "software_development", True),
        ("ENG-TEST", "Unit & Integration Testing", "software_development", True),
        ("ENG-ADM", "General: Internal Meetings & Admin", "others", False),
        ("ENG-RSK", "General: Research & Skill Development", "others", False),
        ("ENG-MENT", "General: Team Support & Mentorship", "people_management", False),
        ("ENG-ADH", "General: Unplanned / Ad-hoc Requests", "others", True),
    ],
    "Delivery(Customer Activation)": [
        ("DLV-BPM", "Business Process Mapping", "project_delivery_management", True),
        ("DLV-CONF", "Platform Configuration & Setup", "project_delivery_management", True),
        ("DLV-DISC", "Client Discovery Workshops", "project_delivery_management", True),
        ("DLV-UAT", "User Acceptance Testing (UAT) Support", "project_delivery_management", True),
        ("DLV-TRN", "End-User Training", "project_delivery_management", True),
        ("DLV-ETL", "Data Migration & ETL", "project_delivery_management", True),
        ("DLV-ADM", "General: Internal Meetings & Admin", "others", False),
        ("DLV-RSK", "General: Research & Skill Development", "others", False),
        ("DLV-MENT", "General: Team Support & Mentorship", "people_management", False),
        ("DLV-ADH", "General: Unplanned / Ad-hoc Requests", "others", True),
    ],
    "Techops/Devops": [
        ("OPS-CLOUD", "Cloud Infrastructure Management", "infra_management", True),
        ("OPS-CICD", "CI/CD Pipeline Maintenance", "infra_management", True),
        ("OPS-SECP", "Security Patching & Hardening", "infra_management", True),
        ("OPS-DBA", "Database Administration", "infra_management", True),
        ("OPS-MON", "System Monitoring & Alerting", "infra_management", True),
        ("OPS-DEP", "Production Deployment", "infra_management", True),
        ("OPS-ADM", "General: Internal Meetings & Admin", "others", False),
        ("OPS-RSK", "General: Research & Skill Development", "others", False),
        ("OPS-MENT", "General: Team Support & Mentorship", "people_management", False),
        ("OPS-ADH", "General: Unplanned / Ad-hoc Requests", "others", True),
    ],
    "Support": [
        ("SUP-L12", "L1/L2 Ticket Resolution", "it_tasks", True),
        ("SUP-INC", "Incident Investigation", "it_tasks", True),
        ("SUP-KB", "Knowledge Base Documentation", "it_tasks", True),
        ("SUP-ESC", "Bug Escalation Management", "it_tasks", True),
        ("SUP-HEALTH", "Client Health Checks", "it_tasks", True),
        ("SUP-FEAT", "Feature Request Logging", "it_tasks", True),
        ("SUP-ADM", "General: Internal Meetings & Admin", "others", False),
        ("SUP-RSK", "General: Research & Skill Development", "others", False),
        ("SUP-MENT", "General: Team Support & Mentorship", "people_management", False),
        ("SUP-ADH", "General: Unplanned / Ad-hoc Requests", "others", True),
    ],
    "IT": [
        ("IT-IAM", "Access Management (IAM)", "it_tasks", True),
        ("IT-HW", "Hardware Procurement & Setup", "it_tasks", True),
        ("IT-VPN", "Internal Network/VPN Support", "it_tasks", True),
        ("IT-LIC", "Software License Management", "it_tasks", True),
        ("IT-AUD", "Security Audit & Compliance", "it_tasks", True),
        ("IT-HLP", "Internal Helpdesk Support", "it_tasks", True),
        ("IT-ADM", "General: Internal Meetings & Admin", "others", False),
        ("IT-RSK", "General: Research & Skill Development", "others", False),
        ("IT-MENT", "General: Team Support & Mentorship", "people_management", False),
        ("IT-ADH", "General: Unplanned / Ad-hoc Requests", "others", True),
    ],
    "QA": [
        ("QA-PLAN", "Test Planning", "software_development", True),
        ("QA-CASE", "Test Case Design", "software_development", True),
        ("QA-EXEC", "Test Execution", "software_development", True),
        ("QA-REG", "Regression Testing", "software_development", True),
        ("QA-UAT", "UAT Support", "project_delivery_management", True),
        ("QA-BUG", "Defect Verification", "software_development", True),
        ("QA-ADM", "General: Internal Meetings & Admin", "others", False),
        ("QA-RSK", "General: Research & Skill Development", "others", False),
        ("QA-ADH", "General: Unplanned / Ad-hoc Requests", "others", True),
    ],
    "Human Resource": [
        ("HR-REC", "Recruitment & Hiring", "people_management", True),
        ("HR-ONB", "Employee Onboarding", "people_management", True),
        ("HR-EMP", "Employee Relations & Engagement", "people_management", True),
        ("HR-PERF", "Performance Management", "people_management", True),
        ("HR-LND", "Learning & Development", "people_management", True),
        ("HR-OFF", "Employee Offboarding", "people_management", True),
        ("HR-ADM", "General: Internal Meetings & Admin", "others", False),
        ("HR-RSK", "General: Research & Skill Development", "others", False),
        ("HR-ADH", "General: Unplanned / Ad-hoc Requests", "others", True),
    ],
}

LEGACY_ACTIVITY_MAP_BY_DEPARTMENT = {
    "Product": {
        "Specification Writing": "PRD Writing & Feature Spec",
        "Research": "General: Research & Skill Development",
        "Design": "UI/UX Wireframing & Design Review",
        "Development / Coding": "PRD Writing & Feature Spec",
        "Testing & QA": "User Testing & Feedback Analysis",
        "Code Review": "UI/UX Wireframing & Design Review",
        "Bug Fix": "User Testing & Feedback Analysis",
        "Documentation": "PRD Writing & Feature Spec",
        "Deployment / DevOps": "General: Unplanned / Ad-hoc Requests",
        "Meeting / Discussion": "General: Internal Meetings & Admin",
        "Demo Preparation & Delivery": "User Testing & Feedback Analysis",
        "Planning": "Roadmap Planning & Strategy",
        "Self Study / Learning": "General: Research & Skill Development",
        "Training / Seminar / Workshop": "General: Research & Skill Development",
        "Administrative Work": "General: Internal Meetings & Admin",
        "Support / Helpdesk": "General: Team Support & Mentorship",
        "Performance / Process Review": "General: Team Support & Mentorship",
        "Other": "General: Unplanned / Ad-hoc Requests",
    },
    "Engineering": {
        "Specification Writing": "API Integration & Documentation",
        "Research": "General: Research & Skill Development",
        "Design": "Technical Architecture & Design",
        "Development / Coding": "New Feature Development",
        "Testing & QA": "Unit & Integration Testing",
        "Code Review": "Code Review & Refactoring",
        "Bug Fix": "Bug Fixing & Hotfixes",
        "Documentation": "API Integration & Documentation",
        "Deployment / DevOps": "Technical Architecture & Design",
        "Meeting / Discussion": "General: Internal Meetings & Admin",
        "Demo Preparation & Delivery": "General: Team Support & Mentorship",
        "Planning": "Technical Architecture & Design",
        "Self Study / Learning": "General: Research & Skill Development",
        "Training / Seminar / Workshop": "General: Research & Skill Development",
        "Administrative Work": "General: Internal Meetings & Admin",
        "Support / Helpdesk": "General: Team Support & Mentorship",
        "Performance / Process Review": "General: Team Support & Mentorship",
        "Other": "General: Unplanned / Ad-hoc Requests",
    },
    "Delivery(Customer Activation)": {
        "Specification Writing": "Business Process Mapping",
        "Research": "General: Research & Skill Development",
        "Design": "Platform Configuration & Setup",
        "Development / Coding": "Platform Configuration & Setup",
        "Testing & QA": "User Acceptance Testing (UAT) Support",
        "Code Review": "General: Team Support & Mentorship",
        "Bug Fix": "User Acceptance Testing (UAT) Support",
        "Documentation": "End-User Training",
        "Deployment / DevOps": "Platform Configuration & Setup",
        "Meeting / Discussion": "General: Internal Meetings & Admin",
        "Demo Preparation & Delivery": "End-User Training",
        "Planning": "Business Process Mapping",
        "Self Study / Learning": "General: Research & Skill Development",
        "Training / Seminar / Workshop": "General: Research & Skill Development",
        "Administrative Work": "General: Internal Meetings & Admin",
        "Support / Helpdesk": "General: Team Support & Mentorship",
        "Performance / Process Review": "General: Team Support & Mentorship",
        "Other": "General: Unplanned / Ad-hoc Requests",
    },
    "Techops/Devops": {
        "Specification Writing": "General: Unplanned / Ad-hoc Requests",
        "Research": "General: Research & Skill Development",
        "Design": "Cloud Infrastructure Management",
        "Development / Coding": "CI/CD Pipeline Maintenance",
        "Testing & QA": "System Monitoring & Alerting",
        "Code Review": "Security Patching & Hardening",
        "Bug Fix": "Security Patching & Hardening",
        "Documentation": "Database Administration",
        "Deployment / DevOps": "Production Deployment",
        "Meeting / Discussion": "General: Internal Meetings & Admin",
        "Demo Preparation & Delivery": "General: Team Support & Mentorship",
        "Planning": "Cloud Infrastructure Management",
        "Self Study / Learning": "General: Research & Skill Development",
        "Training / Seminar / Workshop": "General: Research & Skill Development",
        "Administrative Work": "General: Internal Meetings & Admin",
        "Support / Helpdesk": "System Monitoring & Alerting",
        "Performance / Process Review": "General: Team Support & Mentorship",
        "Other": "General: Unplanned / Ad-hoc Requests",
    },
    "Support": {
        "Specification Writing": "Feature Request Logging",
        "Research": "General: Research & Skill Development",
        "Design": "Knowledge Base Documentation",
        "Development / Coding": "Bug Escalation Management",
        "Testing & QA": "Incident Investigation",
        "Code Review": "Bug Escalation Management",
        "Bug Fix": "Incident Investigation",
        "Documentation": "Knowledge Base Documentation",
        "Deployment / DevOps": "Incident Investigation",
        "Meeting / Discussion": "General: Internal Meetings & Admin",
        "Demo Preparation & Delivery": "Client Health Checks",
        "Planning": "Feature Request Logging",
        "Self Study / Learning": "General: Research & Skill Development",
        "Training / Seminar / Workshop": "General: Research & Skill Development",
        "Administrative Work": "General: Internal Meetings & Admin",
        "Support / Helpdesk": "L1/L2 Ticket Resolution",
        "Performance / Process Review": "General: Team Support & Mentorship",
        "Other": "General: Unplanned / Ad-hoc Requests",
    },
    "IT": {
        "Specification Writing": "Software License Management",
        "Research": "General: Research & Skill Development",
        "Design": "Hardware Procurement & Setup",
        "Development / Coding": "Software License Management",
        "Testing & QA": "Security Audit & Compliance",
        "Code Review": "Security Audit & Compliance",
        "Bug Fix": "Internal Helpdesk Support",
        "Documentation": "Software License Management",
        "Deployment / DevOps": "Internal Network/VPN Support",
        "Meeting / Discussion": "General: Internal Meetings & Admin",
        "Demo Preparation & Delivery": "Internal Helpdesk Support",
        "Planning": "Access Management (IAM)",
        "Self Study / Learning": "General: Research & Skill Development",
        "Training / Seminar / Workshop": "General: Research & Skill Development",
        "Administrative Work": "General: Internal Meetings & Admin",
        "Support / Helpdesk": "Internal Helpdesk Support",
        "Performance / Process Review": "General: Team Support & Mentorship",
        "Other": "General: Unplanned / Ad-hoc Requests",
    },
}


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
        email="shantanu.singh@solulever.com",
        full_name="Shantanu Singh",
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
    db.flush()

    departments_by_name = ensure_departments_for_org(db, org)
    ensure_department_activity_types(db, org, departments_by_name)

    default_activity = db.scalar(
        select(ActivityType)
        .join(Department, Department.id == ActivityType.department_id)
        .where(ActivityType.org_id == org.id, Department.name == "Engineering", ActivityType.code == "ENG-FEAT")
    )
    settings_obj = db.scalar(select(OrgSettings).where(OrgSettings.org_id == org.id))
    if settings_obj and default_activity:
        settings_obj.default_activity_type_id = default_activity.id

    db.commit()


def ensure_departments_for_org(db: Session, org: Organization) -> dict[str, Department]:
    existing = db.scalars(select(Department).where(Department.org_id == org.id)).all()
    departments_by_name = {item.name: item for item in existing}
    for name in DEFAULT_DEPARTMENTS:
        if name not in departments_by_name:
            department = Department(org_id=org.id, name=name)
            db.add(department)
            db.flush()
            departments_by_name[name] = department
    return departments_by_name


def ensure_department_activity_types(
    db: Session,
    org: Organization,
    departments_by_name: dict[str, Department],
) -> dict[tuple[str, str], ActivityType]:
    existing = db.scalars(select(ActivityType).where(ActivityType.org_id == org.id)).all()
    activity_map = {(item.code, item.name): item for item in existing}
    for department_name, definitions in DEPARTMENT_ACTIVITY_DEFINITIONS.items():
        department = departments_by_name[department_name]
        for code, name, category, is_chargeable in definitions:
            key = (code, name)
            if key not in activity_map:
                item = ActivityType(
                    org_id=org.id,
                    department_id=department.id,
                    code=code,
                    name=name,
                    category=category,
                    is_chargeable=is_chargeable,
                    is_default=True,
                    is_active=True,
                )
                db.add(item)
                db.flush()
                activity_map[key] = item
            else:
                activity = activity_map[key]
                activity.department_id = department.id
                activity.category = category
                activity.is_chargeable = is_chargeable
                activity.is_default = True
                activity.is_active = True
    return activity_map


def seed_department_assignments(db: Session, org_slug: str = "solulever") -> None:
    org = db.scalar(select(Organization).where(Organization.slug == org_slug))
    if not org:
        return

    departments_by_name = ensure_departments_for_org(db, org)
    engineering_id = departments_by_name["Engineering"].id

    users = db.scalars(select(User).where(User.org_id == org.id)).all()
    users_by_email = {user.email.strip().lower(): user for user in users}
    for email, full_name in SOLULEVER_REQUIRED_USERS.items():
        if email in users_by_email:
            continue
        user = User(
            org_id=org.id,
            email=email,
            full_name=full_name,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            role=Role.EMPLOYEE,
            is_active=True,
            force_password_change=True,
        )
        db.add(user)
        db.flush()
        users.append(user)
        users_by_email[email] = user

    for user in users:
        if user.department_id is None:
            user.department_id = engineering_id

    for email, department_name in SOLULEVER_DEPARTMENT_ASSIGNMENTS.items():
        user = users_by_email.get(email)
        if user:
            user.department_id = departments_by_name[department_name].id

    db.commit()


def migrate_department_activity_catalog(db: Session, org_slug: str = "solulever") -> None:
    org = db.scalar(select(Organization).where(Organization.slug == org_slug))
    if not org:
        return

    departments_by_name = ensure_departments_for_org(db, org)
    ensure_department_activity_types(db, org, departments_by_name)

    activity_types = db.scalars(select(ActivityType).where(ActivityType.org_id == org.id)).all()
    activity_by_department_and_name = {
        (item.department_id, item.name): item for item in activity_types if item.department_id is not None
    }
    desired_codes = {
        code
        for definitions in DEPARTMENT_ACTIVITY_DEFINITIONS.values()
        for code, _name, _category, _is_chargeable in definitions
    }

    tasks = db.scalars(select(Task).where(Task.org_id == org.id)).all()
    for task in tasks:
        user = db.get(User, task.assigned_to)
        if not user or not user.department_id:
            continue
        current_activity = next((item for item in activity_types if item.id == task.activity_type_id), None)
        if not current_activity:
            continue
        if current_activity.department_id == user.department_id and current_activity.is_active:
            continue
        department = next((item for item in departments_by_name.values() if item.id == user.department_id), None)
        if not department:
            continue
        target_name = LEGACY_ACTIVITY_MAP_BY_DEPARTMENT.get(department.name, {}).get(
            current_activity.name,
            "General: Unplanned / Ad-hoc Requests",
        )
        target = activity_by_department_and_name.get((user.department_id, target_name))
        if target:
            task.activity_type_id = target.id

    legacy_items = [
        item
        for item in activity_types
        if item.department_id is None or item.code not in desired_codes
    ]
    db.flush()
    legacy_ids = {item.id for item in legacy_items}
    active_task_activity_ids = {item[0] for item in db.execute(select(Task.activity_type_id).where(Task.org_id == org.id)).all()}
    for item in legacy_items:
        if item.id not in active_task_activity_ids:
            db.delete(item)
        else:
            item.is_active = False
            item.is_default = False

    settings_obj = db.scalar(select(OrgSettings).where(OrgSettings.org_id == org.id))
    if settings_obj and (not settings_obj.default_activity_type_id or settings_obj.default_activity_type_id in legacy_ids):
        default_activity = db.scalar(
            select(ActivityType)
            .join(Department, Department.id == ActivityType.department_id)
            .where(ActivityType.org_id == org.id, Department.name == "Engineering", ActivityType.code == "ENG-FEAT")
        )
        settings_obj.default_activity_type_id = default_activity.id if default_activity else None

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
