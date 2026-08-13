"""Finding the repository checkout, and saying so honestly when it is not there.

A handful of tests assert on things that live outside `backend/`: the Terraform
environments, the GitHub workflows, the Prometheus alert rules, the hash-locked
requirement files, the versioned prompt definitions. They are real tests and they
guard real things.

They also cannot run inside the API container, which mounts `backend/` at `/app`
and nothing else. Previously they resolved the repository root by counting
directories upwards, arrived at `/`, and failed on a missing `/backend/...` -
nineteen red tests that meant nothing except "you ran these in the wrong place".
Red tests that are expected to be red are worse than no tests: people stop reading
the output.

So the root is *located* rather than assumed. `REPO_ROOT` names it outright when
the checkout is mounted somewhere the source layout cannot imply - which is what
the `tests` service in `docker-compose.yml` does, mounting the checkout read-only
at `/repo`. That is the same reasoning as `PROMPT_ROOT`: state the path rather than
count directories upwards and land on `/`. Failing that, the root is found by
walking up for a marker only a real checkout has.

When it genuinely cannot be found these tests **skip with a reason** instead of
failing. A skip is the truthful outcome: the assets are absent, so the assertion
was never evaluated. That path is the fallback and not the plan: the documented way
to run the suite mounts the checkout, so these tests really do run.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import pytest

# Files that exist only at the top of a real checkout. `pnpm-workspace.yaml` is
# the most distinctive; `.git` is absent from an exported tree, which is why it is
# not the only marker.
_ROOT_MARKERS = ("pnpm-workspace.yaml", "turbo.json")


def _is_checkout(candidate: Path) -> bool:
    return all((candidate / marker).exists() for marker in _ROOT_MARKERS)


@lru_cache(maxsize=1)
def find_repository_root() -> Path | None:
    """The checkout root, or None when the tests run somewhere without one."""
    declared = os.environ.get("REPO_ROOT")
    if declared:
        # A checkout that was mounted deliberately and is not there is a wiring
        # mistake worth failing loudly on, rather than skipping quietly past.
        root = Path(declared).resolve()
        if not _is_checkout(root):
            raise RuntimeError(
                f"REPO_ROOT={declared} is not a repository checkout: "
                f"expected {' and '.join(_ROOT_MARKERS)} inside it."
            )
        return root
    for candidate in Path(__file__).resolve().parents:
        if _is_checkout(candidate):
            return candidate
    return None


def repository_root() -> Path:
    """The checkout root, skipping the calling test when there is not one."""
    root = find_repository_root()
    if root is None:
        pytest.skip(
            "needs the repository checkout: these assertions cover files outside "
            "backend/ (terraform, workflows, alert rules, lock files, prompts). "
            "Run pytest from the repository root on the host, or `make verify`.",
            allow_module_level=True,
        )
    return root


#: Decorator form, for tests that read the root inside the function body.
requires_repository_checkout = pytest.mark.skipif(
    find_repository_root() is None,
    reason=(
        "needs the repository checkout; these files live outside backend/. "
        "Run from the repository root on the host."
    ),
)
