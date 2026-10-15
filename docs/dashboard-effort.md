# View and correct dashboard effort

Click any day in **A week you can actually deliver** to see the tasks behind its recorded hours. The breakdown includes task code and name, project, task status, hours, and work notes. Closed tasks are included. The total follows the weekly dashboard rules: the signed-in person's logs on non-archived tasks in the current organisation.

Use **View effort history**, the work-date picker or previous/next day controls to inspect other dates, including last week. Days with no entries show an empty state. Existing add-effort actions still open the add form; the breakdown also offers **Add effort** for eligible days in the current week.

Choose **Edit date, hours & notes** to correct one entry. Changing the work date moves the existing entry; it does not copy it. A save reloads the dashboard and opens the destination day, so daily totals, weekly reports and remaining capacity reflect the change. Task lifetime effort is recalculated. The task stays open or completed as it was; the correction does not change its deadline or completion date. A move before the task start brings its start date back to the actual work date. Task names link to the existing task-details page for other task edits.

The correction accepts any real past or current date, including dates in previous weeks. Hours must be finite, positive, no more than 24 per entry, and have at most two decimal places. Existing imported work notes may be retained; changed notes use the existing 80-character minimum. An optimistic revision check rejects saving an entry changed since it was opened. Only the entry owner can correct it, including their own historical entry after task reassignment. A task event records the old/new work date and hours. The feature never moves the user's records automatically.

Routes:

- `GET /{org_slug}/dashboard/effort?log_date=YYYY-MM-DD`: read own entries, aggregate hours and revisions. Private, no-store response.
- `PATCH /{org_slug}/dashboard/effort/{log_id}`: update own entry using `log_date`, `hours`, `notes` and the returned `revision`. Recompute lifetime totals and record an audit event in the same transaction.

The existing task-details effort editor also rejects future dates and invalid/nonpositive hours.

Verification includes previous-week moves, no duplicate entries, recalculated weekly/lifetime totals, closed-task preservation, owner/organisation restrictions, missing/archived records, invalid dates/hours/notes, legacy notes, concurrency conflicts and rendered dashboard controls. JavaScript checks cover the breakdown, safe text rendering, editing, conflict feedback and reload into the destination day. Full browser visual review remains outstanding when no browser automation is available.
