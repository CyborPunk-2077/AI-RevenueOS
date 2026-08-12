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

So the root is *located* rather than assumed - by walking up for a marker that only
the real checkout has - and when it cannot be found these tests **skip with a
reason** instead of failing. A skip is the truthful outcome: the assets are absent,
so the assertion was never evaluated. Nothing is weakened, because the host
verification path (`make verify`, or pytest from the repository root) still finds
the checkout and still runs every one of them.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pytest

# Files that exist only at the top of a real checkout. `pnpm-workspace.yaml` is
# the most distinctive; `.git` is absent from an exported tree, which is why it is
# not the only marker.
_ROOT_MARKERS = ("pnpm-workspace.yaml", "turbo.json")


@lru_cache(maxsize=1)
def find_repository_root() -> Path | None:
    """The checkout root, or None when the tests run somewhere without one."""
    for candidate in Path(__file__).resolve().parents:
        if all((candidate / marker).exists() for marker in _ROOT_MARKERS):
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
