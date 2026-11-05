# Integration API

Use `Authorization: Bearer TOKEN` with `INTEGRATION_API_TOKEN`. Browser sessions
are not API credentials, and API tokens cannot invoke browser administration or
scan actions. Credentials belong in headers, never URL query strings. Responses
have `Cache-Control: no-store` and describe observations, not action authority.

| Route | Purpose |
| --- | --- |
| `/api/v1/readiness` | Selected tracking/API readiness and supported routes |
| `/api/v1/summary` | Saved tracking counts and unresolved-operation indication |
| `/api/v1/audit-status` | Running/queued state, recorded result, next schedule and limits |
| `/api/v1/titles/oldest-waiting` | Up to ten oldest saved Waiting records |
| `/api/v1/titles/leaving-soon` | Up to ten saved Holding records |
| `/api/v1/coverage` | Opt-in aggregate folder/date coverage |
| `/api/v1/scan-history` | Filtered, paginated recent recorded scans |
| `/api/v1/proposals` | Latest recorded proposal counts, separate from active work |
| `/api/v1/backup-status` | Integrity of an explicitly selected JSON backup packet |

Title routes require `INTEGRATION_API_TITLE_DETAILS=true` and accept
`library=Movies` or `library=TV`. Optional media enrichment requires
`INTEGRATION_API_MEDIA=true`. Do not infer current disk presence or deletion
eligibility from a saved date or title link. API calls never trigger scans.

Coverage requires `INTEGRATION_API_COVERAGE=true`; inaccessible directories remain
unknown, and a source change during observation rejects the response.
Scan history accepts `page` (at least one), `page_size` (one through twenty), and
`outcome` (`all`, `completed`, `review`, `unknown`). Missing historical details
remain unknown. Persistent history survives restarts.

Backup status requires all of `INTEGRATION_API_BACKUP_DIRECTORY`,
`INTEGRATION_API_BACKUP_IDENTITY` (`device:inode`) and
`INTEGRATION_API_BACKUP_FINGERPRINT`. No request parameter can choose a file.
The reader validates the receipt and both tracking/settings payload hashes. It
returns no packet contents, private paths, credentials or restore permission.
