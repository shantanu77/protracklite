# Capacity View

## Purpose

Capacity View gives managers and administrators a timeline of team availability for planning work around registered leave and organization holidays.

Route:

```text
/{org-slug}/manager/capacity
```

Access is limited to active users with the Manager or Admin role.

## Page layout

- Uses the standard ProTrack shell and existing left navigation.
- Appears under **Manager → Capacity View** and from the Team Dashboard quick links.
- Uses elevated white cards on the existing light-gray dashboard background.
- Header title: **TEAM AVAILABILITY & CAPACITY PLANNING**.
- Header controls:
  - Scope: **My Team** or **All Organization**.
  - View: **Month View** (default), **Sprint View** (14 days), or **Week View** (7 days).
  - **View Timeline** button centers the timeline on today when today is in the selected period.
- Previous/next controls move by one month, sprint, or week.

For managers, My Team contains the manager and their direct reports. All Organization contains every active organization user. Admins see the organization in either scope because admins do not have a direct-report-only restriction.

## Timeline behavior

- The Team Member column is outside the horizontal scroll area and therefore remains fixed.
- Date columns scroll horizontally.
- Calendar header contains the period label and individual day/date cells.
- Each person row contains:
  - profile image or initials;
  - shortened display name;
  - department name when available, otherwise the ProTrack role.
- Public holidays render as light-blue vertical bands across every team row.
- Contiguous statuses are rendered as timeline bars.
- Tooltips show the employee, status, date range, and full/half-day detail.

## Status rules

| Status | Visual | Current ProTrack rule |
|---|---|---|
| Active / Available | Solid green `#22C55E` | Active employee with no registered leave and no public holiday on the date. |
| Planned Leave | Yellow `#FBBF24` with diagonal stripes | Leave date is later than the date on which the leave record was submitted. |
| Unplanned / Sick | Solid red `#EF4444` | Leave is entered on or after the affected date. ProTrack currently has no separate medical-leave category, so timing is the implemented classification rule. |
| Public Holiday | Light blue `#DBEAFE` | Organization holiday registered by an admin. It overrides individual availability for that day. |

Full-day and half-day leave use the same planned/unplanned color category; the tooltip identifies Full day, Half day AM, or Half day PM.

Customer visits are not currently a structured ProTrack status and are therefore not shown as a separate timeline bar or digest category. A future customer-visit model can add that status without changing the timeline layout.

## Conflict alert

The banner finds the highest number of simultaneous registered leaves in the visible period.

- Two or more unavailable people on a date produces a yellow conflict warning.
- One or zero produces a green no-overlap message.
- Public holidays are not treated as leave conflicts.

The current data model does not store job titles such as “Backend Developer,” so conflict messages report team-member counts rather than role-specific counts.

## Summary and legend

Summary cards show:

- people in view;
- leave entries in the visible period;
- public holidays;
- number of calendar days in the period.

The legend is centered below the timeline and shows Active / Available, dynamic Planned Leave dates, Unplanned / Sick, and Public Holiday.

## Microsoft Teams daily digest

The deployment installs `protracklite-capacity-digest.timer`, scheduled every day at **08:30 Asia/Kolkata**.

It runs:

```bash
/opt/protracklite/.venv/bin/python -m app.capacity_digest
```

The job posts a read-only text summary through a Microsoft Teams **Workflows incoming webhook**. Configure a Teams workflow for the intended `#daily-availability` channel using the “When a Teams webhook request is received” trigger, then add the copied URL to `/etc/protracklite.env`:

```env
TEAMS_AVAILABILITY_WEBHOOK_URL=https://...
```

If the URL is absent, the timer exits safely with `skipped-no-webhook` and sends nothing.

Example message:

```text
Off-Duty Summary (ProTrack Sync)
Monday, 20 July 2026

🤒 Unplanned: @Abhishek B. (Cover: @Rahul K.)
🏖️ Planned: @Divya M.
```

The `@Name` text is human-readable. A Workflows incoming webhook does not resolve those names into native Teams user mentions; native notification mentions would require a registered Teams bot/Graph integration with tenant user identifiers.

Run a non-posting preview with:

```bash
python3 -m app.capacity_digest --dry-run --org-slug solulever
```

The digest uses the same planned/unplanned timing rule as Capacity View and includes the designated backup person when one is recorded. Customer Visit is omitted because it is not currently a structured ProTrack record.
