# Tracking backend contract

Tracking is independently enabled with `tracking.enabled=true`. It requires a
nonempty `tracking.admin-key` and a fixed `tracking.public-base-url`; production
uses HTTPS. The random login/session capabilities do not require a signing key.
SQL is in `sql/schema-tracking.sql` and migration `010-tracking-up.sql`.

## Public records

Public reads expose only explicitly reviewed, published versions. Feed pagination
orders versions by their public review time, exposed as `changedAt`; `publishedAt`
continues to mean the original source publication. Cursors are opaque. Source
occurrence may be unknown. Source dates without times are normalized to their
Korean calendar date and disclosed in `coverage`.

- `/api/v1/activities` supports personId/topic/billId/type/cursor/limit.
- `/api/v1/activities/{id}?version=...` opens an exact published version.
- `/api/v1/activities/{id}/history` lists up to 100 published versions with review
  dates, correction reasons and correction flags. Draft/rejected versions stay private.
- People, bills, issues, search and coverage follow the shared v1 web contract.
- Person/bill/issue detail activity lists are bounded to 100. Their linked feed
  pages allow cursor pagination. Bill votes come from those public activity
  records; canonical projection groups all participants of each vote into one event.

The 10 issue definitions are curated topics, with no invented political activity.
Coverage lists known sources even before any successful collection. A raw sync's
completion does not claim a verified publication contract or complete coverage.

## Operator workflow

All routes under `/admin/tracking` require `X-Parliament-Ingestion-Key`.
`POST /events` imports the Activity JSON contract as a draft. Its `(id,version)`
content is immutable; identical replays succeed and changed content with the same
version returns 409. Derived changedAt/corrected metadata is excluded from import
identity. Imported summaries never publish automatically.

`GET /review` lists pending drafts. Review with
`POST /events/{id}/versions/{version}/review` and
`{approved,reviewer,correctionReason}`. Replacing a published version requires a
correction reason. Three free-text explanations per Korean calendar day can be
approved; null-summary structured facts do not use that quota.

`POST /project` reads existing staged records without contacting a remote API.
The operator must first verify the real source response and supply:
`{sourceKey,kind,verifiedContract,fields,stageMap,voteMap,personNamespace,topics,limit,cursor}`.
`fields` maps logical `id,title,url,publishedAt,occurredAt,stage,billId,personId,
sessionId,voteResult` to verified uppercase raw JSON field names. There is no
best-guess field mapping or automatic source contract. Unknown status/result
stays unknown; absent rows never become abstention or absence.

Projection returns `{imported,skipped,notes,nextCursor}`. Pass nextCursor back as
cursor with the same source/kind to backfill subsequent stable key ranges. Null
cursor starts a new historical scan, including reprocessing changed rows. Bill
projection limits raw rows to 500 per request. Vote projection limits requests
to 20 groups, fetches the complete bill/session group up to 500 source rows, and
creates one immutable event containing every verified participant and evidence
version. Oversized, conflicting or unidentified groups remain unavailable;
notes explain skipped groups. Rows lacking a bill/session key cannot be grouped.
Explicit source collection scheduling and source response certification remain
operator workflows; projection itself is not an automatic synchronization job.

Derived activity versions hash the normalized display payload, explicit mapper
revision and effective source contract. Changed field/identity/status mappings
create new draft versions even when the raw source hash is unchanged. Vote groups
also include member projection versions. Cursor/limit and public review metadata
do not affect versions, and arrays are normalized before import so retries remain
identical. Evidence keeps the original raw source version. A changed draft still
requires review and a correction reason before replacing a published version.

## Authentication and queued mail

`POST /api/v1/auth/request-link {email}` returns generic 202. It creates a hashed,
15-minute, one-use login token and DB mail spool entry. Limits are five requests
per email and 60 per direct backend client per hour; proxy deployments share the
backend client limit unless trusted infrastructure supplies a separate limiter.
No login token is returned by an API. `/auth/verify {token}` requires the configured
Origin and creates a 30-day HttpOnly/SameSite=Lax session cookie; production cookies
are Secure. Request-link also requires the configured Origin.

`GET /api/v1/me` returns authenticated/csrfToken/follows/frequency. Follows and
logout require both a valid session, exact configured Origin and X-CSRF-Token.
At most 20 real person/bill/issue/topic targets can be followed. Interests are not
used to infer political orientation or sold for targeting.

`POST /admin/tracking/digests/build {frequency,from,to}` creates version-deduplicated
spool entries for verified, opted-in users. It handles at most 100 recipients and
100 latest matching activities per recipient per invocation. Corrections are
eligible by public review time, and every mail links its exact activity version.
The queue builder does not send email. A separate authorized sender must implement
queue retry/delivery and recipient eligibility checks; disabled delivery must not
be presented as a working public email service.

Unsubscribe links hold a durable random per-user capability, restricted to turning
off email. The hash verifies the capability; its persisted random value allows
queue construction across process restarts without key-rotation failures. The
unsubscribe route disables future digest creation and cancels already queued
digests. Login links and unsubscribe capabilities appear only in restricted DB mail
payloads, never public responses or logs. DB/mail spool access needs appropriate
permissions. A queued sender must recheck eligibility before actual delivery.

## Verification

Tests cover immutable/replayed/conflicting imports, private drafts/rejections,
published correction history, review quota, verified participant mapping, all 300
vote participants, unknown vote preservation, source timestamps, change recency,
cursors, auth Origin/CSRF, one-use login, opt-in digest dedupe and unsubscribe.
MySQL repository tests use an isolated Testcontainers MySQL 8.4 database. No
production API, live email service or AWS deployment is contacted by tests.
