# Monday Report Upgrade V1

## Objective

The Monday Report should become a **weekly alignment and decisions page**, rather
than a task-and-hours presentation page.

The current report is comprehensive, but its first impression is dominated by:

- booked hours;
- booking percentage;
- missing effort;
- pending task counts;
- long task tables.

This can encourage discussion about visible activity instead of outcomes and can
turn the Monday meeting into a line-by-line reading of the application.

The upgraded report should focus the conversation on:

1. outcomes completed last week;
2. important commitments for this week;
3. work that is blocked or at risk;
4. decisions, resources, or support required;
5. work that should be stopped, delayed, or deprioritized.

Detailed tasks, time logs, and capacity information should remain available as
supporting evidence without becoming the meeting agenda.

## Recommended Layout

```text
MONDAY ALIGNMENT                         13-17 July
Weekly focus: Complete customer onboarding rollout

[ Edit Plan ]  [ Start Meeting Mode ]  [ More v ]


LAST WEEK - OUTCOMES
[Completed] Customer onboarding workflow released
Impact: Operations can now onboard employees without engineering support.

[Replanned] Payroll export moved to this week
Context: Bank format changed on Thursday.
Revised commitment: Tuesday.


THIS WEEK - IMPORTANT COMMITMENTS
1. Complete payroll bank export                 Due Tue   On track
   Done when: Finance validates the production file.

2. Launch employee directory                    Due Thu   At risk
   Done when: HR imports and verifies all active employees.
   Risk: Waiting for HR master data.


RISKS, BLOCKERS AND SUPPORT NEEDED
Needs decision - Employee directory data
Impact: Thursday launch may move.
Tried: Followed up with HR on Friday.
Need: Data owner confirmed by Monday 2 PM.
Decision owner: Operations Head


TRADE-OFFS
Urgent payroll format change added this week.
-> Mobile dashboard improvements moved to next week.


DECISIONS AND MANAGER ACTIONS
[ ] Operations Head: Confirm HR data owner              Due Mon
[ ] Manager: Approve revised payroll scope              Due Tue


> Capacity and context
> Supporting tasks and time logs
> Completed, pending, and stalled task inventory
```

## Recommended Information Hierarchy

### 1. Page Header

The header should establish that the page is for the current week's alignment.

Show:

- `Monday Alignment` or `Weekly Alignment` as the page title;
- the current week's date range;
- the employee's short weekly focus;
- `Edit Plan` as the main preparation action;
- `Start Meeting Mode` as the main presentation action;
- administrative utilities under a `More` menu.

Actions such as task creation, AI task parsing, effort correction, and time-log
catch-up should remain available, but they should not dominate the header.

### 2. Last Week - Outcomes

This section should answer:

> What meaningful outcomes were completed last week?

Each item should contain:

- a short outcome statement;
- its customer, team, or business impact;
- linked tasks as optional supporting evidence;
- a neutral outcome state such as `Completed`, `Partially completed`, or
  `Replanned`;
- context and a revised commitment when an outcome was not completed.

The report should not treat the number of closed tasks as the main measure of a
successful week. One important result may matter more than many small task
closures.

### 3. This Week - Important Commitments

This should be the most prominent section on the page.

Limit the primary list to approximately three to five important commitments. A
commitment should describe a result, not merely repeat a task title.

Each commitment should show:

- outcome or commitment statement;
- definition of done;
- target date;
- confidence: `On track`, `At risk`, `Blocked`, or `Needs decision`;
- optional short context;
- linked tasks;
- optional planned sequence or priority.

Example:

```text
Launch employee directory by Thursday
Done when: HR imports and verifies all active employees.
Confidence: At risk
Linked tasks: PT-184, PT-191
```

Planning a commitment should not automatically change task status, dates, logged
hours, or other execution data.

### 4. Risks, Blockers, and Support Needed

This section should appear immediately after the week's commitments rather than
leaving stalled work near the bottom of the report.

For each exception, capture only information that helps somebody act:

- what is blocked or at risk;
- expected impact;
- what has already been tried;
- what decision, resource, or help is needed;
- who needs to act;
- when the response is required;
- revised commitment, when applicable.

Reporting a risk early should use constructive, neutral styling. It should look
like responsible ownership, not a public failure marker.

When there are no exceptions, show a small message such as:

```text
No current risks or decisions needed.
```

Do not require repetitive narrative updates for work that is proceeding normally.

### 5. Trade-Offs and Priority Changes

This section should make changes in scope visible.

When urgent work is introduced, prompt the user or manager to record:

- what was added;
- why it was added;
- who changed the priority;
- which existing commitment was stopped, delayed, or reduced.

This prevents new work from being silently added on top of an already agreed
weekly plan.

Example:

```text
Added: Urgent payroll bank-format change
Reason: Bank specification changed on Thursday
Trade-off: Mobile dashboard improvements moved to next week
```

### 6. Decisions and Manager Actions

The report should make management follow-through visible alongside employee
commitments.

Each requested decision or manager action should have:

- clear action or decision required;
- owner;
- requested date;
- target response date;
- state: `Open`, `Decided`, or `Overdue`;
- short resolution note.

An unresolved manager decision should be as visible as an employee blocker. This
creates shared accountability for delivery.

### 7. Capacity and Context

Capacity information is useful context but should not be the report's primary
performance signal.

Keep it in a collapsed section containing:

- leave and holidays;
- production incidents;
- customer support work;
- unplanned requests;
- material changes in workload;
- available capacity;
- booked effort, when operationally useful.

Booked hours and booked percentage should not appear as headline success metrics.
If time data is incomplete, show a private utility notice to the employee rather
than presenting it as a prominent meeting result.

### 8. Supporting Evidence and Task Inventory

Preserve the existing detailed information in collapsed sections:

- worked last week;
- completed tasks;
- pending tasks;
- stalled tasks;
- task descriptions;
- planned and actual effort;
- time logs and comments.

These sections should be opened when evidence or investigation is needed. They
should not be read row by row during every Monday meeting.

## Current-to-Proposed Mapping

| Current element | Recommended treatment |
|---|---|
| Booked hours and booked percentage as headline cards | Move under collapsed `Capacity and context` |
| Missing hours and catch-up panel near the top | Show as a private utility warning outside Meeting Mode |
| `Last Week Closed` count | Replace with actual outcomes and their impact |
| AI Work Summary | Generate an outcome-oriented draft automatically and let the employee correct it |
| `This Week Plan` task table | Replace the primary view with three to five commitment cards |
| Focus field mixing focus, risk, and support | Separate into `Weekly Focus`, `Risks`, and `Support Needed` |
| Pending and stalled tables | Surface exceptions near the top; keep complete inventories collapsed |
| Long task-by-task review | Add a focused Meeting Mode showing only the five agenda sections |
| Employee-only accountability | Add manager decisions and actions with owners and due dates |
| Red danger styling for old tasks | Use neutral `Needs attention` language with context and revised commitment |

## Meeting Mode

Add a `Start Meeting Mode` action that hides administrative controls and presents
only the information needed for alignment.

Meeting Mode should show:

1. last week's outcomes;
2. this week's commitments;
3. risks and blockers;
4. support and decisions needed;
5. priority changes and trade-offs;
6. actions captured during the meeting.

It should hide by default:

- time-entry catch-up controls;
- AI task creation;
- missing-hour prompts;
- detailed task actions;
- full task inventories;
- task-level time-log comments.

During the meeting, users should be able to record decisions and actions inline.
At the end, the system should retain a concise meeting record that can be copied or
shared without producing a separate manual presentation.

## Interaction Rules

### Outcome-oriented commitments

A weekly commitment should describe what will be achieved and how completion will
be recognized.

Weak:

```text
Work on employee directory
```

Better:

```text
Launch the employee directory for HR validation by Thursday.
Done when all active employee records are imported and HR signs off.
```

### Exception-based updates

Require additional context only when:

- work is at risk;
- work is blocked;
- a commitment has moved;
- scope has materially changed;
- urgent work was introduced;
- a decision or resource is required.

### Early disclosure

Employees should be able to mark a commitment `At risk` or `Needs decision` in one
click. The interface should encourage early warnings and ask what support is
needed.

### Shared accountability

Every blocker or requested decision should have an action owner. The owner may be
the employee, a manager, another team, or a stakeholder.

### Context before conclusions

Allow users to record relevant context such as:

- leave;
- incidents;
- dependency delays;
- changing priorities;
- support work;
- work that was not fully represented in the system.

The report should not turn one weak week or one incomplete update into a
performance conclusion.

### No hidden scoring

Do not display:

- employee rankings;
- unexplained performance scores;
- booking percentage as a proxy for performance;
- task count as a proxy for contribution;
- red/green employee ratings based on one week.

## Suggested Status Language

Use states that help the meeting decide what to do:

| State | Meaning |
|---|---|
| `On track` | No intervention currently required |
| `At risk` | Delivery is still possible, but something needs attention |
| `Blocked` | Progress cannot continue without a dependency or action |
| `Needs decision` | A specific decision is required from another owner |
| `Replanned` | The commitment changed and a new date or scope was agreed |
| `Completed` | The agreed definition of done was met |

Avoid language that implies personal failure when the actual issue may be unclear
priorities, dependencies, capacity, or delayed management decisions.

## Automation Opportunities

The system should reuse existing task and time-log data wherever possible.

It can automatically draft:

- completed outcomes from closed and worked tasks;
- linked evidence for each outcome;
- commitments carried from the previous plan;
- potentially at-risk commitments based on dates and stalled dependencies;
- leave and incident context;
- changes between the original plan and the current plan.

AI should help summarize existing evidence, but the employee should be able to
edit and correct the result before it becomes the meeting summary.

## Recommended V1 Scope

The first release should:

1. Add an outcome-based `Last Week` summary near the top.
2. Convert the primary `This Week Plan` display into commitment cards.
3. Add separate `Risks and Support Needed` fields.
4. Add a `Trade-Offs and Priority Changes` section.
5. Add decision and action ownership, including manager actions.
6. Collapse hours, time-log catch-up, and detailed task tables under supporting
   details.
7. Add `Start Meeting Mode` to hide administrative controls.
8. Preserve existing task, planning, and time-log functionality underneath the
   new information hierarchy.

V1 should not introduce:

- performance scoring;
- employee ranking;
- manager approval of every weekly plan;
- automatic negative flags based on one week;
- new mandatory daily narratives;
- duplicated updates across the application, chat, email, and presentations.

## Rollout Approach

Run the upgraded layout as a four-week experiment.

### Week 1

- Introduce the new top-level alignment sections.
- Explain that hours and detailed tasks remain available as supporting evidence.
- Measure how long preparation and the Monday meeting take.

### Week 2

- Stop reading task tables line by line.
- Use Meeting Mode and capture decisions and actions inline.
- Collect feedback about missing or unnecessary information.

### Weeks 3-4

- Observe whether commitments, risks, and ownership remain clear.
- Track whether blockers are reported earlier and resolved faster.
- Avoid adding further reporting requirements during the experiment.

### End of Week 4

- Keep changes that reduced effort without reducing delivery clarity.
- Restore only controls whose absence caused a specific observable problem.
- Select the next small improvement based on employee and manager feedback.

Useful experiment measures include:

- average report preparation time;
- average Monday meeting duration;
- number and age of unresolved decisions;
- whether risks were raised before commitments were missed;
- employee rating: `The Monday meeting helps resolve blockers and priorities`;
- employee rating: `The performance process feels fair and useful`.

## Expected Result

The upgraded Monday Report should make it possible to understand, within a few
minutes:

- what meaningful outcomes were delivered;
- what matters most this week;
- what may prevent delivery;
- who needs to make a decision or provide support;
- what priorities changed and what was moved as a result.

It should preserve accountability and delivery visibility while reducing
administrative work, surveillance signals, and public task-by-task status
interrogation.
