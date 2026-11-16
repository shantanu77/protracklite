"""Build and send a personal monthly attendance and effort statement."""
from __future__ import annotations

import argparse
import csv
import html
import io
import smtplib
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.config import get_settings
from app.database import SessionLocal
from app.employee_dashboard import working_calendar
from app.email_delivery_log import begin_delivery, finish_delivery, finish_run, start_run
from app.leave_approvals import apply_local_leave_approvals
from app.models import AttendanceRegularization, Holiday, Leave, LeaveType, Organization, Task, TimeLog, User
from app.time_utils import local_today
from app.zoho_people import fetch_zoho_attendance_entries, fetch_zoho_employee_ids, fetch_zoho_leave_requests

settings = get_settings()
REMOTE_TYPE = settings.zoho_work_from_home_leave_type_id.strip()


@dataclass
class MonthlyReport:
    user: User
    org: Organization
    month_start: date
    period_end: date
    rows: list[dict]
    attendance_status: str
    leave_status: str


def _month_start(value: str | None) -> date:
    if not value:
        today = local_today()
        return today.replace(day=1)
    year, month = (int(part) for part in value.split("-", 1))
    return date(year, month, 1)


def build_report(db, email: str, month_start: date) -> MonthlyReport | None:
    user = db.scalar(select(User).where(func.lower(User.email) == email.strip().lower(), User.is_active.is_(True)))
    if not user:
        return None
    org = db.get(Organization, user.org_id)
    month_end = date(month_start.year, month_start.month, monthrange(month_start.year, month_start.month)[1])
    period_end = min(month_end, local_today())
    if not user.zoho_employee_id.strip():
        directory = fetch_zoho_employee_ids(employee_emails=[user.email])
        if directory.status == "synced":
            user.zoho_employee_id = dict(directory.employee_ids).get(user.email.strip().lower(), "")
            if user.zoho_employee_id:
                db.commit()

    attendance_result = fetch_zoho_attendance_entries(
        employee_zoho_id=user.zoho_employee_id, from_date=month_start, to_date=period_end
    ) if user.zoho_employee_id else None
    leave_result = fetch_zoho_leave_requests(
        employee_zoho_ids=[user.zoho_employee_id], from_date=month_start, to_date=period_end
    ) if user.zoho_employee_id else None
    if leave_result is not None:
        leave_result = apply_local_leave_approvals(db, org.id, [user], leave_result)

    attendance_by_date = {}
    if attendance_result and attendance_result.status == "synced":
        attendance_by_date = {entry["attendance_date"]: entry for entry in attendance_result.entries}
    leaves_by_date: dict[date, list[tuple[str, float, str]]] = {}
    if leave_result and leave_result.status == "synced":
        for item in leave_result.leaves:
            name = str(item.get("leave_type_name") or "Leave")
            is_remote = "remote" in name.casefold() or "work from home" in name.casefold() or (
                REMOTE_TYPE and str(item.get("leave_type_id") or "") == REMOTE_TYPE
            )
            if is_remote:
                continue
            status = str(item.get("approval_status") or "Unknown").strip()
            if status.upper() in {"REJECTED", "CANCELLED", "CANCELED", "WITHDRAWN"}:
                continue
            counts = item.get("day_counts") or ()
            if not counts:
                dates = item.get("day_dates") or ()
                counts = [(day, min(float(item.get("leave_days") or len(dates)) / max(len(dates), 1), 1)) for day in dates]
            for day, count in counts:
                if month_start <= day <= period_end and float(count) > 0:
                    leaves_by_date.setdefault(day, []).append((name, min(float(count), 1), status))
    else:
        # Retain locally recorded legacy leave when Zoho is unavailable.
        for leave in db.scalars(select(Leave).where(
            Leave.user_id == user.id, Leave.leave_date >= month_start, Leave.leave_date <= period_end
        )):
            leaves_by_date.setdefault(leave.leave_date, []).append((leave.leave_type.value, 0.5 if leave.leave_type != LeaveType.FULL else 1, "Saved"))

    calendar = working_calendar(db, org.id, month_start, period_end)
    holiday_names = {row.holiday_date: row.name for row in db.scalars(select(Holiday).where(
        Holiday.org_id == org.id, Holiday.holiday_date >= month_start, Holiday.holiday_date <= period_end
    ))}
    effort_by_day = dict(db.execute(
        select(TimeLog.log_date, func.coalesce(func.sum(TimeLog.hours), 0))
        .join(Task, Task.id == TimeLog.task_id)
        .where(Task.org_id == org.id, TimeLog.user_id == user.id,
               TimeLog.log_date >= month_start, TimeLog.log_date <= period_end)
        .group_by(TimeLog.log_date)
    ).all())
    regularized = set(db.scalars(select(AttendanceRegularization.attendance_date).where(
        AttendanceRegularization.org_id == org.id, AttendanceRegularization.user_id == user.id,
        AttendanceRegularization.attendance_date >= month_start,
        AttendanceRegularization.attendance_date <= period_end,
        AttendanceRegularization.status == "approved",
    )))

    rows = []
    for offset in range((period_end - month_start).days + 1):
        day = month_start + timedelta(days=offset)
        entry = attendance_by_date.get(day, {})
        day_leaves = leaves_by_date.get(day, [])
        leave_count = min(sum(item[1] for item in day_leaves), 1.0)
        leave_label = "; ".join(f"{name} ({status})" for name, _, status in day_leaves)
        if day in holiday_names:
            status = "Holiday"
        elif day not in calendar:
            status = "Weekend"
        elif leave_count >= 1:
            approval = "Approved" if all(item[2].upper() == "APPROVED" for item in day_leaves) else "Applied"
            status = f"On leave · {approval}"
        elif leave_count > 0 and not (entry.get("first_in") or entry.get("last_out") or day in regularized):
            approval = "Approved" if all(item[2].upper() == "APPROVED" for item in day_leaves) else "Applied"
            status = f"On leave · {approval} ({leave_count:g}d)"
        elif entry.get("first_in") or entry.get("last_out") or day in regularized:
            mode = str(entry.get("work_mode") or ("remote" if day in regularized else "working")).title()
            status = f"Working · {mode}"
            if leave_count:
                status += " + partial leave"
        elif attendance_result and attendance_result.status == "synced":
            status = "No attendance"
        else:
            status = "Attendance unavailable"
        rows.append({
            "date": day, "day": day.strftime("%A"), "status": status,
            "first_in": entry.get("first_in").strftime("%H:%M") if entry.get("first_in") else "—",
            "last_out": entry.get("last_out").strftime("%H:%M") if entry.get("last_out") else "—",
            "leave": leave_label or (holiday_names.get(day, "") if day in holiday_names else ""),
            "leave_count": leave_count,
            "hours": float(effort_by_day.get(day, 0) or 0),
        })
    return MonthlyReport(user, org, month_start, period_end, rows,
                         attendance_result.status if attendance_result else "unavailable",
                         leave_result.status if leave_result else "unavailable")


def _summary(report: MonthlyReport) -> dict:
    return {
        "effort": sum(row["hours"] for row in report.rows),
        "effort_days": sum(row["hours"] > 0 for row in report.rows),
        "working_days": sum(row["status"] != "Weekend" and row["status"] != "Holiday" for row in report.rows),
        "attended": sum(row["status"].startswith("Working") for row in report.rows),
        "office_days": sum("Office" in row["status"] for row in report.rows),
        "remote_days": sum("Remote" in row["status"] for row in report.rows),
        "no_attendance": sum(row["status"] == "No attendance" for row in report.rows),
        "leave_days": sum(row["leave_count"] for row in report.rows),
        "holidays": sum(row["status"] == "Holiday" for row in report.rows),
        "weekends": sum(row["status"] == "Weekend" for row in report.rows),
    }


def _csv_attachment(report: MonthlyReport) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["Date", "Day", "Status", "First check-in", "Last check-out", "Leave / holiday", "Effort logged (hours)"])
    for row in report.rows:
        writer.writerow([row["date"].isoformat(), row["day"], row["status"], row["first_in"], row["last_out"], row["leave"], f'{row["hours"]:.2f}'])
    return output.getvalue()


def build_message(report: MonthlyReport) -> tuple[str, str, str]:
    summary = _summary(report)
    subject = f"Monthly attendance & effort · {report.month_start:%B %Y} · {report.user.full_name}"
    lines = [f"Hi {report.user.full_name},", "", f"Your attendance and effort summary for {report.month_start:%B %Y} (through {report.period_end:%d %b}) is attached.",
             f"Effort logged: {summary['effort']:.2f} hours across {summary['effort_days']} day(s).",
             f"Attendance: {summary['attended']} working day(s) marked; {summary['no_attendance']} working day(s) have no attendance record.",
             f"Office: {summary['office_days']} day(s); remote: {summary['remote_days']} day(s).",
             f"Leave applied: {summary['leave_days']:.1f} day(s), including pending requests; holidays: {summary['holidays']}; weekends: {summary['weekends']}.",
             "Effort hours are task time logged in ProtrackLite. Check-in/out times come from Zoho People."]
    cards = [("Working days", str(summary["working_days"]), "#f2f4f7", "#344054"),
             ("Effort logged", f"{summary['effort']:.1f}h", "#eaf3ff", "#245bb2"),
             ("Office days", str(summary["office_days"]), "#e6f5ef", "#16704a"),
             ("Remote days", str(summary["remote_days"]), "#e9efff", "#4057a5"),
             ("Leave applied", f"{summary['leave_days']:.1f}d", "#fef3f2", "#b42318")]
    card_html = "".join(f"<td style='padding:6px;width:20%'><div style='background:{background};border-radius:12px;padding:12px 9px;border-top:3px solid {accent}'><div style='font-size:11px;color:#60716e'>{html.escape(label)}</div><strong style='font-size:20px;color:{accent}'>{html.escape(value)}</strong></div></td>" for label, value, background, accent in cards)
    status_colors = {
        "Weekend": ("#667085", "#f2f4f7"), "Holiday": ("#175cd3", "#eff8ff"),
        "On leave · Approved": ("#b42318", "#fef3f2"), "On leave · Applied": ("#b42318", "#fef3f2"),
        "No attendance": ("#7a271a", "#fecdca"), "Attendance unavailable": ("#667085", "#f2f4f7"),
        "Working · Office": ("#067647", "#ecfdf3"), "Working · Remote": ("#3538cd", "#eef4ff"),
        "Working · Hybrid": ("#175cd3", "#eff8ff"),
    }
    def color_for_status(status: str) -> tuple[str, str]:
        if "leave" in status.casefold():
            return ("#b42318", "#fef3f2")
        if status == "No attendance":
            return ("#7a271a", "#fecdca")
        return next((colors for label, colors in status_colors.items()
                     if status == label or status.startswith(label + " ") or status.startswith(label + " +")),
                    ("#475467", "#f2f4f7"))
    row_html = "".join(
        "<tr>" +
        f"<td style='padding:9px;border-bottom:1px solid #e7ecea;white-space:nowrap'>{row['date']:%d %b}</td>"+
        f"<td style='padding:9px;border-bottom:1px solid #e7ecea'>{row['day']}</td>"+
        f"<td style='padding:9px;border-bottom:1px solid #e7ecea'><span style='display:inline-block;padding:5px 8px;border-radius:999px;background:{color_for_status(row['status'])[1]};color:{color_for_status(row['status'])[0]};font-weight:700'>{html.escape(row['status'])}</span></td>"+
        f"<td style='padding:9px;border-bottom:1px solid #e7ecea'>{row['first_in']} – {row['last_out']}</td>"+
        f"<td style='padding:9px;border-bottom:1px solid #e7ecea;text-align:right'>{row['hours']:.2f}</td></tr>"
        for row in report.rows
    )
    html_body = f"""<!doctype html><html><body style='margin:0;background:#eef3f2;font-family:Arial,sans-serif;color:#19352f'>
<div style='max-width:820px;margin:0 auto;padding:28px 14px'><div style='background:#173b35;border-radius:18px 18px 0 0;padding:26px;color:#fff'>
<div style='font-size:11px;letter-spacing:1.4px;text-transform:uppercase;color:#a8d8c9'>PROTRACKLITE · MONTHLY REPORT</div>
<h1 style='font-size:26px;margin:9px 0'>Attendance &amp; effort</h1><div style='color:#d6e8e2'>{report.month_start:%B %Y} · {report.month_start:%d %b}–{report.period_end:%d %b %Y}</div></div>
<div style='background:#fff;padding:24px;border:1px solid #dbe5e1;border-top:0;border-radius:0 0 18px 18px'>
<p>Hi {html.escape(report.user.full_name)},</p><p style='color:#53645f'>Here is your month-to-date view. The attached CSV is the complete day-by-day sheet.</p>
<table role='presentation' style='width:100%;border-collapse:collapse;margin:18px 0'><tr>{card_html}</tr></table>
<p style='font-size:14px;color:#53645f'>Attendance marked: <strong>{summary['attended']}</strong> &nbsp; · &nbsp; Leave applied: <strong>{summary['leave_days']:.1f} day(s)</strong> (includes pending) &nbsp; · &nbsp; No attendance: <strong>{summary['no_attendance']}</strong></p>
<h2 style='font-size:17px;margin:24px 0 10px'>Daily detail</h2><div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse;font-size:13px'>
<thead><tr style='background:#f1f5f4;text-align:left'><th style='padding:9px'>Date</th><th style='padding:9px'>Day</th><th style='padding:9px'>Status</th><th style='padding:9px'>Check-in / out</th><th style='padding:9px;text-align:right'>Effort h</th></tr></thead><tbody>{row_html}</tbody></table></div>
<p style='margin-top:20px;color:#687873;font-size:12px'>Effort hours are task time logged in ProtrackLite. Check-in/out times come from Zoho People. Attendance data: {html.escape(report.attendance_status)} · Leave data: {html.escape(report.leave_status)}.</p>
<p style='color:#82908c;font-size:12px'>ProtrackLite · {html.escape(report.org.name)}</p></div></div></body></html>"""
    return subject, "\n".join(lines), html_body


def send_report(recipient: str, report: MonthlyReport) -> None:
    subject, text_body, html_body = build_message(report)
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")
    message.add_attachment(_csv_attachment(report).encode("utf-8-sig"), maintype="text", subtype="csv",
                           filename=f"attendance-effort-{report.month_start:%Y-%m}.csv")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        if settings.smtp_username:
            server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


class DeliveryLogFinalizeError(RuntimeError):
    """SMTP accepted the message but the final audit update failed."""

    def __init__(self, report: MonthlyReport, subject: str, message: str):
        super().__init__(message)
        self.report = report
        self.subject = subject


def send_logged_report(
    db, run_id: str, user: User, month_start: date,
    report: MonthlyReport | None = None, recipient: str | None = None,
) -> tuple[MonthlyReport, str]:
    destination = (recipient or user.email).strip()
    subject = f"Monthly attendance & effort · {month_start:%B %Y} · {user.full_name}"
    delivery_id = begin_delivery(run_id, user.id, destination, subject)
    smtp_accepted = False
    try:
        report = report or build_report(db, user.email, month_start)
        if not report:
            raise RuntimeError("No active employee record")
        subject, _, _ = build_message(report)
        send_report(destination, report)
        smtp_accepted = True
    except Exception as exc:
        try:
            finish_delivery(delivery_id, status="failed", error_message=str(exc))
        except Exception:
            pass
        raise
    try:
        finish_delivery(delivery_id, status="sent")
    except Exception as exc:
        if smtp_accepted:
            raise DeliveryLogFinalizeError(
                report, subject,
                f"SMTP accepted the message, but the audit row remains pending: {exc}",
            ) from exc
        raise
    return report, subject


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a monthly personal attendance and effort report.")
    parser.add_argument("--email", help="Employee whose report to build")
    parser.add_argument("--all-enabled", action="store_true", help="Build one report for each active user in the selected organization")
    parser.add_argument("--org-slug", help="Organization scope required with --all-enabled")
    parser.add_argument("--month", help="Month in YYYY-MM format; defaults to the current month")
    parser.add_argument("--recipient", help="Delivery address; defaults to the employee email")
    parser.add_argument("--send", action="store_true", help="Send email (otherwise preview subject and summary)")
    parser.add_argument("--last-day-only", action="store_true", help="Send only when today is the last calendar day in Asia/Kolkata")
    parser.add_argument("--not-before", type=date.fromisoformat, help="Do not send before this date in Asia/Kolkata")
    args = parser.parse_args()
    if args.last_day_only:
        local_day = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        if args.not_before and local_day < args.not_before:
            print(f"Skipped: scheduled delivery begins on {args.not_before:%Y-%m-%d}.")
            return
        if local_day.day != monthrange(local_day.year, local_day.month)[1]:
            print(f"Skipped: {local_day:%Y-%m-%d} is not the last day of the month in Asia/Kolkata.")
            return
    month_start = _month_start(args.month)
    with SessionLocal() as db:
        if args.all_enabled:
            if not args.org_slug:
                parser.error("--org-slug is required with --all-enabled")
            if args.email or args.recipient:
                parser.error("--email and --recipient cannot be combined with --all-enabled")
            org = db.scalar(select(Organization).where(
                Organization.slug == args.org_slug.strip().lower(), Organization.is_active.is_(True)
            ))
            if not org:
                parser.error(f"No active organization found for slug {args.org_slug}")
            people = list(db.scalars(select(User).where(
                User.org_id == org.id, User.is_active.is_(True)
            ).order_by(User.email.asc())))
            print(f"{org.name}: {len(people)} active user(s) · {month_start:%B %Y}")
            sent = failed = 0
            report_month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            report_period_end = min(local_today(), report_month_end)
            run_id = start_run(org.id, "monthly_attendance_effort", month_start,
                               report_period_end, len(people)) if args.send else None
            for person in people:
                try:
                    if args.send:
                        try:
                            report, subject = send_logged_report(db, run_id, person, month_start)
                            sent += 1
                            print(f"[sent] {person.email}: {subject}")
                        except DeliveryLogFinalizeError as exc:
                            sent += 1
                            report, subject = exc.report, exc.subject
                            print(f"[sent-log-pending] {person.email}: {exc}")
                    else:
                        report = build_report(db, person.email, month_start)
                        if not report:
                            raise RuntimeError("No active employee record")
                        subject, _, _ = build_message(report)
                        print(f"[preview] {person.email}: {subject}")
                    if report.attendance_status != "synced" or report.leave_status != "synced":
                        print(f"  source status: attendance={report.attendance_status}, leave={report.leave_status}")
                except Exception as exc:
                    failed += 1
                    print(f"[failed] {person.email}: {exc}")
            print(f"Delivery complete: {sent} sent, {failed} failed, {len(people)} active user(s).")
            if run_id:
                try:
                    logged_run = finish_run(run_id)
                    print(f"Run log: {logged_run.id} · {logged_run.status} · {logged_run.sent_count} accepted, {logged_run.failed_count} failed")
                except Exception as exc:
                    print(f"[run-log-pending] {run_id}: {exc}")
            return

        if not args.email:
            parser.error("--email is required unless --all-enabled is used")
        report = build_report(db, args.email, month_start)
        if not report:
            parser.error(f"No active employee found for {args.email}")
        subject, text_body, _ = build_message(report)
        print(subject)
        print(text_body)
        print(f"Attendance source: {report.attendance_status}; leave source: {report.leave_status}")
        if args.send:
            recipient = (args.recipient or report.user.email).strip()
            run_id = start_run(report.org.id, "monthly_attendance_effort", month_start,
                               report.period_end, 1)
            try:
                _, subject = send_logged_report(db, run_id, report.user, month_start, report, recipient)
                print(f"Sent to {recipient} · run {run_id}")
            except DeliveryLogFinalizeError as exc:
                print(f"Sent to {recipient}, but audit row is pending · run {run_id}: {exc}")
            except Exception as exc:
                print(f"[failed] {recipient} · run {run_id}: {exc}")
            finally:
                finish_run(run_id)


if __name__ == "__main__":
    main()
