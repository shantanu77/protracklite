# Production Database Incident RCA

## Executive summary

On 27 July 2026, a test command executed on the production application server inherited the production `DATABASE_URL`. The test configuration used `os.environ.setdefault(...)`, which only supplies a test database URL when `DATABASE_URL` is absent. Because production already defined that variable, SQLAlchemy connected the tests to the live MySQL database.

The test cleanup routine then iterated through the application tables and deleted their rows. This removed production application data while leaving the database schema intact. The website subsequently appeared to have crashed: list data disappeared, existing authentication stopped behaving normally, and an application restart recreated only default seed records.

The deleted rows were recovered from MySQL's row-based binary logs. Recovery was first performed in a separate database, validated, backed up, and then promoted to the live `protracklite` database. A hard test isolation guard was added so tests now force an in-memory SQLite connection and abort if the resolved engine is not SQLite.

## Incident classification

- Severity: Critical production data incident
- Affected system: ProTrackLite at `tasks.omnihire.in`
- Affected database: Production MySQL database `protracklite`
- Primary impact: Application data became unavailable
- Data recovery: Completed from MySQL binary logs
- Permanent data loss identified: None

## Timeline

All times below are on 27 July 2026.

| Time (UTC) | Time (IST) | Event |
|---|---|---|
| 13:02:52 | 18:32:52 | A production-side test run connected to the live MySQL database. Its cleanup transaction deleted rows across the application's mapped tables. |
| 13:02:53 | 18:32:53 | The destructive transaction committed. MySQL binary log positions were `5753743` through `6688544` in `binlog.000268`. |
| Approximately 13:05 | Approximately 18:35 | The user reported that the application had completely crashed. Requests were also being redirected because the existing browser session had expired. |
| 13:10:19 | 18:40:19 | The application was restarted while deploying a session-recovery improvement. Startup seeding recreated only the default organization/users, making the missing production data more visible. This restart did not cause the original deletion. |
| Approximately 13:17 | Approximately 18:47 | Database inspection confirmed that the application was connected to production MySQL at `10.0.0.3/protracklite` and that application tables were empty. |
| Approximately 13:18 | Approximately 18:48 | MySQL binary logging was confirmed enabled with row format and 30-day retention. The destructive transaction and its complete before-images were located. |
| Approximately 13:19–13:21 | Approximately 18:49–18:51 | Deleted rows were reconstructed into the separate database `protracklite_recovery_20260727`, test-only rows were removed, counts and relationships were validated, and a verified recovery dump was created. |
| Approximately 13:21 | Approximately 18:51 | The application was briefly stopped, the live database was replaced with the verified recovery copy, and the service was restarted. |
| 13:21:53 onward | 18:51:53 onward | Production verification confirmed the service was active, list data was restored, session renewal worked, and list 5 rendered successfully. |

## What happened technically

The affected tests attempted to configure an in-memory SQLite database like this:

```python
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
```

`setdefault` does not replace an existing environment variable. On the production server, `DATABASE_URL` was already set to the live MySQL connection. Therefore:

1. The test process imported the application's database module.
2. SQLAlchemy created its engine using the production MySQL URL.
3. Tests inserted temporary records into production.
4. Test teardown executed a cleanup loop across every SQLAlchemy model table:

   ```python
   for table in reversed(Base.metadata.sorted_tables):
       connection.execute(table.delete())
   ```

5. That cleanup deleted the live application rows and committed the transaction.

This was not caused by the list-page UI code, schema migration logic, MySQL failure, or the later service restart. The exact deletion was visible as a large row-based transaction in MySQL's binary log.

## Root cause

The direct root cause was unsafe test database initialization:

- Tests used `setdefault` instead of unconditionally selecting a test database.
- The cleanup routine was capable of deleting every row in all mapped tables.
- There was no assertion preventing tests from running against MySQL.
- A test command was run in a production environment containing production credentials.

The combination of these conditions allowed test cleanup code to operate on production.

## Contributing factors

1. **No environment safety interlock**

   The tests did not verify the active database dialect or database name before mutating data.

2. **Broad teardown behavior**

   Teardown deleted all rows from every mapped table rather than isolating and rolling back only data created by an individual test.

3. **Production credentials available to the test process**

   Running from the production application environment gave the process access to the live database.

4. **No scheduled logical database backup**

   Recovery depended on binary logs. Binary logs were sufficient, but a recent daily logical backup would have made recovery simpler and provided another independent recovery layer.

5. **No destructive-query alert**

   There was no alert for an unusually large multi-table deletion or sudden production row-count collapse.

6. **Concurrent authentication symptom**

   The user's seven-day session had expired and the old error handler redirected to a generic page. This made the incident initially resemble a page or authentication crash instead of immediate data loss.

## Impact

The committed transaction deleted 4,342 rows, including production rows and a small number of temporary test rows. The recovered production dataset, after removing test-only records, included:

- 1 organization
- 32 users
- 1,136 tasks
- 1,617 time logs
- 19 work lists
- 301 work-list items
- 56 work-list comments
- 17 work-list memberships
- Supporting departments, projects, activity mappings, leave records, holidays, releases, plans, summaries, settings, and notification-delivery records

Lists specifically checked during recovery:

| List ID | Title | Items | Comments |
|---:|---|---:|---:|
| 5 | devops work | 29 | 7 |
| 14 | RTL and Localization Release | 21 | 10 |
| 15 | Engineering Work Prioritisation | 11 | 2 |

## Recovery procedure

1. Confirmed that the running application used production MySQL at `10.0.0.3/protracklite`.
2. Confirmed all list tables were empty and inspected MySQL table timestamps.
3. Correlated the deletion time with the production-side test run.
4. Confirmed MySQL binary logging was:
   - Enabled
   - Row-based
   - Retained for 30 days
5. Located the destructive transaction in `binlog.000268`.
6. Decoded the full row before-images for every `DELETE`.
7. Reversed the deletion into a separate recovery database named `protracklite_recovery_20260727`.
8. Removed records created only by the test immediately before cleanup.
9. Validated:
   - Expected record counts
   - Presence and contents of lists 5, 14, and 15
   - Zero orphaned list, item, comment, membership, user, and organization relationships
   - MySQL table checks returned `OK`
10. Created both a post-incident backup and a verified recovery dump.
11. Stopped the application briefly to prevent writes during cutover.
12. Replaced the live database with the verified recovery copy.
13. Restarted the application and verified:
   - Service status was active
   - 19 lists, 301 items, and 56 comments were present
   - Session renewal returned the user to the requested list
   - List 5 returned HTTP 200
   - Expandable item details were present
   - Production response time was approximately 0.25 seconds

## Fixes completed

### Test isolation

Tests now overwrite `DATABASE_URL` with an in-memory SQLite URL rather than using `setdefault`.

Destructive test modules also abort immediately if the resolved SQLAlchemy engine is not SQLite:

```python
if engine.dialect.name != "sqlite":
    raise RuntimeError("Tests must never run against a non-SQLite database.")
```

### Session recovery

Expired browser access tokens can now be renewed from a valid refresh cookie. If renewal is impossible, the user is sent to the correct organization login page rather than the generic root page.

The default refresh-token lifetime was increased from 7 to 30 days.

### Database backups

A production database backup script and nightly cron schedule were added after this incident:

- Schedule: 02:00 IST every night
- Storage: `/var/backups/protracklite/daily`
- Format: Compressed MySQL logical dump
- Retention: 15 days
- Safety: Atomic file creation, lock against overlapping runs, gzip validation, restricted file permissions, and deletion only after a new backup succeeds

## Preventive controls and follow-up recommendations

The following controls should remain mandatory:

1. Never run tests with the production service environment loaded.
2. Keep the SQLite-only assertions in every database-mutating test module.
3. Prefer transaction rollback per test instead of table-wide teardown.
4. Use a dedicated test database account that cannot access production.
5. Keep MySQL binary logs enabled with at least 30 days of retention.
6. Monitor nightly backup completion and file age.
7. Perform periodic restore drills into a separate database.
8. Alert on unusually large deletion transactions or sudden table-count drops.
9. Consider database-host snapshots as a second backup layer.
10. Document and restrict access to production database credentials.

## Accountability

The incident was caused by an AI-initiated production-side test command. The command should not have been run with production database credentials available. The test configuration and teardown safety checks were insufficient, and the AI failed to verify database isolation before executing the tests.

Recovery succeeded because MySQL row-based binary logging retained complete before-images. The safeguards added after the incident are intended to prevent the same failure mode from recurring and to provide a simpler independent recovery path if another database incident occurs.
