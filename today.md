# Today: Daily Action Centre

## Purpose

The Today page should help an employee answer three questions within a few seconds:

1. What requires my attention now?
2. What is the next useful action?
3. Am I making enough progress for today and this week?

Urgency must be specific and actionable. The page should not create anxiety through a large wall of red warnings, nor should it reward logging hours without meaningful progress.

## Page order

1. Daily and weekly progress statistics
2. Action alerts
3. Still Needs Action
4. Delayed Tasks
5. Worked Today

The alert inbox is intentionally limited to the four highest-priority visible alerts. The complete task sections remain available below it.

## Alert rules

### Overdue task

- Trigger: An open assigned task has an end date before today.
- Tone:
  - `urgent` when one or two days overdue.
  - `critical` when three or more days overdue.
- Re-alert: The acknowledgement version changes as the task enters a higher overdue bucket.
- Primary actions: Open task, log hours, complete, or mark stalled.

### Due today without activity

- Trigger: An open task is due today and the employee has not logged effort on it today.
- Tone: `urgent`.
- Primary actions: Open task, log hours, complete, or mark stalled.

### Stale blocker

- Trigger: A stalled assigned task has had no task update or time entry for at least two days.
- Tone: `warning`.
- Primary actions: Open the task and update the blocker.
- Duplicate control: If the same task already has an overdue alert, only the overdue alert is shown.

### Booking pace

- Trigger: At least four hours should have been booked by the current point in the working week, and recorded effort is below 70% of that expected amount.
- Tone: `planning`.
- Expected time is prorated through the current workday so the alert is not unfairly raised at the beginning of the morning.
- Primary action: Log hours against the relevant task.

## Acknowledgement semantics

Each generated alert has a deterministic `alert_key` containing the underlying task or week and an alert version.

- **Acknowledge** hides the current version for the rest of the local working day.
- **Remind next workday** hides it until 09:00 on the next organization working day, skipping configured weekends and holidays.
- An unresolved acknowledged alert returns on the next organization working day.
- If the employee recorded a next-step note, the returning alert shows that previous plan for accountability.
- An alert returns immediately as a new version when its urgency bucket changes.
- Resolution is determined from source data. Closing, rescheduling, updating, or logging against a task removes the corresponding alert naturally.

Acknowledgement is personal. One employee cannot acknowledge another employee's alert.

## Data model

`today_alert_acknowledgements`

- `org_id`
- `user_id`
- `alert_key`
- `action` (`acknowledged` or `snoozed`)
- `acknowledged_on`
- `snoozed_until`
- `note`
- `created_at`
- `updated_at`

Alert instances are not stored. They are calculated from current task, time-log, leave, holiday, and work-rate data; only the user's acknowledgement is persisted.

## Guardrails

- Show no more than four active alerts at once.
- Sort critical and urgent alerts before planning reminders.
- Never expose another employee's tasks through an alert key or action.
- Do not permanently dismiss unresolved work.
- Use positive empty-state copy when all alerts are handled.
- Do not use personal rankings as the main urgency mechanism.

## Later enhancements

- Three user-selected commitments for the day.
- A commitment action with a promised completion date and short plan.
- Leave/deadline collision alerts.
- Manager handover and approval alerts.
- End-of-day check-out for completed, carried-forward, and blocked work.
- A momentum streak based on planning and meaningful updates rather than maximum hours.
