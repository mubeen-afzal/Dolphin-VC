# Frontend integration contract

The API does not assume React, Next.js, Vue, mobile, or any other client. Generate types from `openapi.json` and use the base URL `/api/v1`.

## Authentication

```http
POST /api/v1/auth/login
Content-Type: application/json

{"email":"demo@vcbrain.local","password":"Demo-password-42!"}
```

Send the returned access token on protected requests:

```http
Authorization: Bearer <access_token>
```

Keep browser access tokens in memory. For browser refresh, use credentials-enabled requests and copy the readable `vcbrain_csrf` cookie into `X-CSRF-Token`. Native/CLI clients can submit the refresh token in JSON.

When the API returns `TOKEN_EXPIRED`, refresh once and retry. `TOKEN_REVOKED` or `UNAUTHENTICATED` requires a new login.

## Application upload

```javascript
const form = new FormData();
form.append("company_name", "Dolphin Systems");
form.append("deck", file); // PDF or PPTX
form.append("website", "https://example.com"); // optional when a deck exists

const response = await fetch(`${api}/applications`, {
  method: "POST",
  headers: {
    Authorization: `Bearer ${accessToken}`,
    "Idempotency-Key": crypto.randomUUID(),
  },
  body: form,
});
```

Do not manually set `Content-Type` for `FormData`; the client must add its boundary.

## Job progress

The application response contains `job_id`. Poll `GET /jobs/{id}` or consume SSE:

```text
GET /api/v1/jobs/{job_id}/events
Authorization: Bearer …
Last-Event-ID: 4
```

Event kinds are `step` and `done`, with heartbeat comments. Reconnect with `Last-Event-ID`; do not restart the job.

## Opportunity rendering

The `axes` object always has the keys `founder`, `market`, and `idea_vs_market`. A value may be `null` if that axis could not be scored. Never create an averaged score in the client. Render:

- each axis score, confidence, trend, rationale, and market stance where applicable;
- `thesis_fit` separately;
- founder score with its `[ci_low, ci_high]` interval and cold-start badge;
- SLA deadline, hours remaining, at-risk state, and breach state;
- claim status/trust and evidence links;
- memo gaps as visible unknowns.

Use `If-Match: <version>` when editing opportunities, theses, or memos. On `STALE_VERSION`, refetch and ask the user to reconcile.

## Errors

Every error has this stable shape:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "The request is invalid.",
    "field_errors": [],
    "details": {},
    "retryable": false,
    "retry_after_s": null,
    "request_id": "...",
    "docs": "..."
  }
}
```

Use `error.code`, never English message parsing. Display `request_id` in support/debug views.

## CORS

Set `FRONTEND_ORIGINS` to an exact comma-separated list. Credentials and wildcard origins cannot be combined. Add each local development origin explicitly.

## Client generation

Examples:

```bash
npx openapi-typescript docs/openapi.json -o src/api/vcbrain.ts
# or
openapi-generator-cli generate -i docs/openapi.json -g kotlin -o generated/kotlin
```

The committed OpenAPI snapshot is checked in CI, so an unreviewed backend contract change becomes a build failure.

