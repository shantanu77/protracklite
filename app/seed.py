from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ActivityType, Organization, OrgSettings, Project, Role, User
from app.security import hash_password


DEFAULT_ACTIVITY_TYPES = [
    ("SPEC", "Specification Writing", True),
    ("RES", "Research", True),
    ("DES", "Design", True),
    ("DEV", "Development / Coding", True),
    ("TEST", "Testing & QA", True),
    ("REV", "Code Review", True),
    ("BUG", "Bug Fix", True),
    ("DOC", "Documentation", True),
    ("DEP", "Deployment / DevOps", True),
    ("MTG", "Meeting / Discussion", True),
    ("DEMO", "Demo Preparation & Delivery", True),
    ("PLAN", "Planning", True),
    ("STUDY", "Self Study / Learning", False),
    ("TRAIN", "Training / Seminar / Workshop", False),
    ("ADMIN", "Administrative Work", False),
    ("SUPPORT", "Support / Helpdesk", True),
    ("REVIEW", "Performance / Process Review", False),
    ("OTHER", "Other", False),
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

    for code, name, chargeable in DEFAULT_ACTIVITY_TYPES:
        db.add(
            ActivityType(
                org_id=org.id,
                code=code,
                name=name,
                is_chargeable=chargeable,
                is_default=True,
                is_active=True,
            )
        )

    db.commit()
