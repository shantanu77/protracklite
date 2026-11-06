# Team Leave Review

## Purpose

Give a manager a quick way to inspect one employee's leave year, review all leave requests, and reach attendance actions. The design follows the supplied TeamHub-style reference: a team roster beside employee details, annual leave summary and calendar, then the request action table.

## Page structure

1. **Page heading and attention queue:** name the manager workflow. Show pending attendance regularization requests with a direct link to the affected employee and month.
2. **Team roster:** keep the manager's reporting-tree members in a searchable side panel. Selecting a person opens their leave view and keeps the roster available for switching employees.
3. **Period controls:** select a leave year and an attendance month. Provide attendance export where the Zoho attendance feed is available.
4. **Employee summary:** show the selected employee's avatar, name, email, and year. Summarize approved leave days, pending leave days, and public holidays.
5. **Annual calendar:** show all twelve months in a compact calendar grid. Approved leave, pending leave, weekends, and public holidays have distinct visual treatment; day tooltips expose the date and leave/holiday detail.
6. **Leave request actions:** show every request in the selected year in a table below the calendar, including date range, type, duration, reason, approval status, and a Review action when ProTrack can approve the request.
7. **Attendance detail:** keep the selected month's day-by-day attendance in a collapsed disclosure below the leave action table. Retain regularization and CSV export controls.

## Interaction and data rules

- Preserve manager/admin authorization and the existing reporting-tree scope.
- Fetch the selected employee's Zoho leave for the full selected year, apply local ProTrack approval decisions, and use locally saved requests if the live source fails.
- Count approved and pending leave separately. Exclude rejected, cancelled, and withdrawn requests from the calendar and availability counts while retaining returned requests in the request table for context.
- Treat Zoho Work From Home / remote entries as attendance context only. Exclude them from the calendar, request table, leave balances, pending reviews, and every leave total.
- Leave approval continues to record the manager and approval time in ProTrack. The review modal shows request dates, type, duration, days, and reason before confirmation.
- Regularize attendance only when the selected month's synced attendance contains missing working days. Keep the existing past-working-day validation and remote Noida behavior.
- Keep attendance export scoped to the selected employee and month.
- On narrow screens, stack the roster above the selected employee view, reduce the calendar to two or three month columns, and keep the request table horizontally scrollable.

## Visual direction

Use ProTrack's existing muted green and blue palette, white panels, restrained borders, and compact typography. Give the selected employee and approved leave a soft green treatment, pending requests amber, and public holidays a red marker. Keep table headers, searchable roster labels, keyboard-operable links, and native disclosure controls accessible.
