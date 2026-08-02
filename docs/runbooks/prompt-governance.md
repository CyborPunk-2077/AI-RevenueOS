# Prompt governance

Prompt versions live at `prompts/<task>/v<n>.yaml`. A committed version is
immutable: changing its content hash is rejected, so edits require a new version.
Every file carries a versioned gold set. The release gate runs:

```bash
cd backend
python src/scripts/run_ai_evals.py --fail-under 0.85 --report ai-evals.json
```

This runner is deliberately offline. It evaluates prompt contracts and the real
input guard, records `provider_called: false`, and makes no model-quality claim.
Provider/model quality requires a separately approved sandbox evaluation and must
not be inferred from this report.

Only a global service principal with `actor_type=platform` can mutate the registry.
Every mutation also requires an `Idempotency-Key`:

1. `POST /v1/ai/prompts/sync` mirrors the Git files and gold sets as drafts.
2. Run the offline evaluator and submit each prompt's compact case results to
   `POST /v1/ai/prompts/{task}/v{version}/evaluations`.
3. Promote only its returned passing run through
   `POST /v1/ai/prompts/{task}/v{version}/promote`.
4. Roll back through `POST /v1/ai/prompts/{task}/rollback`; the target must retain
   passing evaluation evidence from its earlier promotion.

Sync, evaluation, promotion, and rollback commit their state, tenant-visible
platform audit record, durable idempotency result, and internal outbox event in one
transaction. Tenant owners cannot promote prompts even though owners otherwise
have the broad built-in permission set. Templates are never returned by the API.
If a task has no promoted prompt or the registry is unavailable, the product does
not call a provider and returns the truthful `prompt_not_promoted` manual fallback.
