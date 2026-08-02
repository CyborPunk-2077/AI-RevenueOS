# Mutation testing

The nightly Linux runner mutates `backend/src/domain`, including the auth policy
module, and runs the focused unit suite. The release floor is 75%. Untested,
timed-out, suspicious and crashed mutants count against the score; skipped
mutants are excluded. Missing, interrupted or incomplete results fail closed.

Run from a Linux host (or WSL with fork support):

```bash
cd backend
python -m pip install --require-hashes --no-deps -r requirements-dev.lock
mutmut run
mutmut export-cicd-stats
python src/scripts/check_mutation_score.py --fail-under 0.75
```

Inspect survivors with `mutmut results` or `mutmut browse`, add a focused test,
and rerun the affected mutant. Preserve `mutants/mutmut-cicd-stats.json` as the
raw result. Do not claim the target from a configured workflow alone: only a
completed stats artifact is score evidence.
