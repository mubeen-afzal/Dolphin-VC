# Testing strategy

## Fast local verification

```bash
cd backend
pip install -e '.[dev]'
./scripts/run_tests.sh
```

This runs pytest with coverage, Ruff, and strict mypy on `services/` and `schemas/`.

## Docker integration verification

```bash
docker compose -f docker-compose.test.yml up \
  --build --abort-on-container-exit --exit-code-from tests tests
```

This uses real PostgreSQL/pgvector and Redis. HTTP providers remain mocked or disabled.

## Test layers

| Layer | Location | What it proves |
|---|---|---|
| Unit | `tests/unit` | Deterministic scoring/trust math, snippet gate, connector normalization. |
| Contract | `tests/contract` | OpenAPI paths/shapes, no overall score, protected-route auth coverage. |
| Integration | `tests/integration` | Database-backed auth, application pipeline, idempotency, durable founder history. |
| Security | `tests/security` | Tenant isolation, SSRF ranges, refresh reuse, pass-decision evidence guard. |
| Resilience | `tests/resilience` | Machine-readable provider degradation and fault boundaries. |
| Smoke | `scripts/smoke_test.py` | A deployed service is alive, authenticates, lists resources, and publishes OpenAPI. |

## Key invariant tests

- `test_no_overall_score_in_contract`
- `test_snippet_is_literal_substring_of_source`
- `test_founder_score_never_resets`
- `test_cold_start_widens_interval_not_lowers_mean`
- `test_application_to_evidence_backed_memo`
- `test_pass_decision_cites_non_absence_reason`
- `test_cross_org_opportunity_is_404`
- `test_all_non_public_api_routes_declare_auth`

## Manual acceptance test

1. Start Compose and seed.
2. Log in as the demo user.
3. Submit a four-slide PPTX containing a product sentence, ARR, customers, and TAM.
4. Watch the job SSE stream to `done`.
5. Confirm the opportunity has three separate axes and no overall score.
6. Open each claim and verify its snippet exists literally in its deck page.
7. Confirm missing memo sections say “Not disclosed” and appear in `gaps`.
8. Attempt a pass on an evidence-free manual opportunity; expect `COLD_START_INSUFFICIENT_EVIDENCE`.
9. Reuse a rotated refresh token; expect the entire token family to be revoked.
10. Read an opportunity using a user from a second organization; expect 404.

## Smoke test

```bash
python backend/scripts/smoke_test.py \
  --base-url http://localhost:8000 \
  --email demo@vcbrain.local \
  --password 'Demo-password-42!'
```

