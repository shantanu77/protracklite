from __future__ import annotations

from typing import TypedDict


class ListTemplate(TypedDict):
    key: str
    title: str
    description: str
    items: list[str]


LIST_TEMPLATES: list[ListTemplate] = [
    {
        "key": "employee-onboarding",
        "title": "Employee Onboarding",
        "description": "Coordinate the essential steps for welcoming and enabling a new employee.",
        "items": [
            "Confirm signed offer letter and joining date",
            "Collect personal, payroll, tax, and emergency-contact details",
            "Complete identity and background verification",
            "Prepare employment agreement and company policies",
            "Arrange laptop, accessories, ID card, and workspace",
            "Create email, HRMS, communication, and required system accounts",
            "Assign reporting manager, onboarding buddy, and department",
            "Share first-week schedule and induction plan",
            "Conduct company, HR policy, and security orientation",
            "Explain role expectations, goals, and probation criteria",
            "Introduce the employee to their team and key stakeholders",
            "Schedule 7-day, 30-day, 60-day, and 90-day check-ins",
        ],
    },
    {
        "key": "project-initiation",
        "title": "Project Initiation",
        "description": "Cover the essential decisions and setup required to start a project well.",
        "items": [
            "Define the business objective and expected outcomes",
            "Confirm project sponsor, owner, and core team",
            "Identify stakeholders and decision makers",
            "Document scope, assumptions, constraints, and exclusions",
            "Agree success measures and acceptance criteria",
            "Estimate budget, people, tools, and other resources",
            "Identify major risks, dependencies, and mitigations",
            "Define milestones, target dates, and delivery approach",
            "Establish governance, reporting, and escalation paths",
            "Set up project workspace, documentation, and communication channels",
            "Hold the project kickoff meeting",
            "Publish the approved project charter and next actions",
        ],
    },
    {
        "key": "employee-offboarding",
        "title": "Employee Offboarding",
        "description": "Manage a secure, respectful, and complete employee exit.",
        "items": [
            "Confirm resignation or separation details and last working day",
            "Notify the manager, HR, IT, payroll, and relevant stakeholders",
            "Create and approve the knowledge-transfer plan",
            "Reassign active work, customers, approvals, and ownership",
            "Collect company laptop, ID card, keys, and other assets",
            "Revoke system, email, VPN, building, and third-party access",
            "Complete attendance, leave, expense, and payroll reconciliation",
            "Calculate and process final settlement and benefits",
            "Conduct the exit interview and record feedback",
            "Collect confidentiality and required exit acknowledgements",
            "Issue relieving, experience, and tax documents",
            "Share alumni or future-contact information where applicable",
        ],
    },
]
