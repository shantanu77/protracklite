"""Persistent run and per-recipient audit log for scheduled email reports."""
from __future__ import annotations

import argparse
import uuid
from datetime import date, datetime

from sqlalchemy import select

from app.database import SessionLocal, engine
from app.models import EmailDeliveryLog, EmailDeliveryRun


def ensure_schema() -> None:
    """Create the two audit tables for standalone scheduled jobs as well as app startup."""
    EmailDeliveryRun.__table__.create(bind=engine, checkfirst=True)
    EmailDeliveryLog.__table__.create(bind=engine, checkfirst=True)


def start_run(org_id: int, report_type: str, period_start: date, period_end: date, target_count: int) -> str:
    ensure_schema()
    run_id = str(uuid.uuid4())
    with SessionLocal() as db:
        db.add(EmailDeliveryRun(
            id=run_id, org_id=org_id, report_type=report_type,
            period_start=period_start, period_end=period_end,
            target_count=target_count, status="running",
        ))
        db.commit()
    return run_id


def begin_delivery(run_id: str, user_id: int | None, recipient: str, subject: str) -> int:
    with SessionLocal() as db:
        entry = EmailDeliveryLog(
            run_id=run_id, user_id=user_id, recipient_email=recipient,
            subject=subject[:255], status="pending", attempted_at=datetime.utcnow(),
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry.id


def finish_delivery(delivery_id: int, *, status: str, error_message: str = "") -> None:
    if status not in {"sent", "failed"}:
        raise ValueError("Delivery status must be sent or failed")
    with SessionLocal() as db:
        entry = db.get(EmailDeliveryLog, delivery_id)
        if not entry:
            raise LookupError(f"Email delivery log {delivery_id} was not found")
        entry.status = status
        entry.finished_at = datetime.utcnow()
        entry.error_message = error_message[:4000]
        db.commit()


def finish_run(run_id: str) -> EmailDeliveryRun:
    with SessionLocal() as db:
        run = db.get(EmailDeliveryRun, run_id)
        if not run:
            raise LookupError(f"Email delivery run {run_id} was not found")
        entries = db.scalars(select(EmailDeliveryLog).where(EmailDeliveryLog.run_id == run_id)).all()
        run.sent_count = sum(entry.status == "sent" for entry in entries)
        run.failed_count = sum(entry.status == "failed" for entry in entries)
        if run.target_count == 0:
            run.status = "empty"
        elif len(entries) < run.target_count or any(entry.status == "pending" for entry in entries):
            run.status = "incomplete"
        elif run.failed_count and run.sent_count:
            run.status = "partial"
        elif run.failed_count:
            run.status = "failed"
        else:
            run.status = "sent"
        run.finished_at = datetime.utcnow()
        db.commit()
        db.refresh(run)
        return run


def list_runs(limit: int = 20, run_id: str | None = None) -> None:
    ensure_schema()
    with SessionLocal() as db:
        stmt = select(EmailDeliveryRun).order_by(EmailDeliveryRun.started_at.desc()).limit(max(1, min(limit, 100)))
        if run_id:
            stmt = select(EmailDeliveryRun).where(EmailDeliveryRun.id == run_id)
        runs = db.scalars(stmt).all()
        for run in runs:
            print(
                f"{run.started_at:%Y-%m-%d %H:%M:%S} UTC | {run.status:<10} | "
                f"{run.report_type} | {run.period_start}–{run.period_end} | "
                f"{run.sent_count}/{run.target_count} sent, {run.failed_count} failed | {run.id}"
            )
            if run_id:
                deliveries = db.scalars(select(EmailDeliveryLog).where(
                    EmailDeliveryLog.run_id == run.id
                ).order_by(EmailDeliveryLog.attempted_at.asc())).all()
                for entry in deliveries:
                    suffix = f" | {entry.error_message}" if entry.error_message else ""
                    print(f"  {entry.status:<10} {entry.recipient_email}{suffix}")
        if not runs:
            print("No email delivery runs found.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect persistent scheduled email delivery logs.")
    parser.add_argument("--limit", type=int, default=20, help="Number of recent runs to list (max 100)")
    parser.add_argument("--run-id", help="Show per-recipient entries for one run")
    args = parser.parse_args()
    list_runs(args.limit, args.run_id)


if __name__ == "__main__":
    main()
