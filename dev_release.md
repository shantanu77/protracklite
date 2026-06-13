# Release Handoff Module

## Objective

Improve the Dev to QA handoff by adding a Releases area in ProTrack. Developers submit one release handoff per feature, fix, or change set. QA receives the handoff, tests it, records the result, and moves it toward release.

The first version should be a dedicated Releases module, not a generic workflow builder. The data model should still be simple enough to support configurable fields and workflow steps later.

## Recommended First Release

Add a `Releases` menu item where:

- developers create and submit release handoffs
- QA users see releases waiting for testing
- QA records test results, defects, and final outcome
- managers/admins see release status and history

This should start as a fixed release form with a small number of important fields. Avoid a large template in the first version because it will reduce adoption.

## Minimal Release Fields

| Field | Required | Default | Notes |
| --- | --- | --- | --- |
| Release Title | Yes | Task or feature name | Short human-readable title |
| Project | Yes | Current/default project | Reuse existing ProTrack project list |
| Related Tasks | No | Empty | Link one or more existing task IDs |
| Developer | Yes | Logged-in user | Auto-filled |
| QA Owner | No | Unassigned | QA can pick it up or manager can assign |
| Environment | Yes | QA | Options: Dev, QA, UAT, Production |
| Change Summary | Yes | Empty | What changed and why |
| Test Instructions | Yes | Empty | Steps QA should follow |
| Unit Test Cases | Yes | Empty upload/link | Developer uploads or links unit test cases |
| Risk Level | Yes | Medium | Options: Low, Medium, High |
| Target Release Date | No | Empty | Optional planning date |
| Notes | No | Empty | Extra context, known issues, rollback notes |

## Unit Test Case Handling

Developers should upload or link unit test cases with the release handoff. This should be treated as a required handoff item before QA starts testing.

Acceptable inputs:

- uploaded file
- link to test document
- link to repository test file
- link to CI/test report

The release record should store the uploaded file reference or URL, not only free text.

## Status Flow

Use a simple fixed workflow:

1. `Draft`
2. `Submitted to QA`
3. `QA In Progress`
4. `QA Failed`
5. `Rework Needed`
6. `Resubmitted`
7. `QA Passed`
8. `Ready for Release`
9. `Released`

Every status change should record:

- changed by
- changed at
- previous status
- new status
- comment

## Notifications

Start with basic notifications:

- when a release is submitted to QA, notify QA users or assigned QA owner
- when QA fails a release, notify the developer
- when QA passes a release, notify the developer and manager
- when a release is marked released, notify relevant stakeholders

## Roles

| Role | Capabilities |
| --- | --- |
| Developer | Create draft, edit own draft, submit to QA, resubmit after rework |
| QA | View submitted releases, assign self, start testing, pass/fail release, add test notes |
| Manager/Admin | View all releases, assign QA owner, move to ready/released, review history |

## Later Enhancements

After the team uses the fixed process for a few weeks, consider:

- custom release templates
- configurable workflow statuses
- required fields by release type
- QA checklist templates
- defect linkage
- CI integration
- release analytics by project, developer, QA owner, and cycle time

## Decision

Build a dedicated Releases module first with a small fixed form and fixed workflow. Keep the model structured enough to support configurable workflows later, but do not build a generic workflow engine in the first version.
