from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


def test_python_dependency_graph_is_hash_locked_for_runtime_and_development() -> None:
    runtime_lock = (BACKEND_ROOT / "requirements.lock").read_text(encoding="utf-8")
    development_lock = (BACKEND_ROOT / "requirements-dev.lock").read_text(encoding="utf-8")

    for dependency in ("fastapi==", "gunicorn==", "sqlalchemy=="):
        assert dependency in runtime_lock
        assert dependency in development_lock
    for dependency in ("pytest==", "bandit==", "pip-audit=="):
        assert dependency in development_lock
        assert dependency not in runtime_lock
    assert "--hash=sha256:" in runtime_lock
    assert "--hash=sha256:" in development_lock


def test_images_and_ci_install_only_from_the_hash_locked_graph() -> None:
    dockerfile = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "requirements.lock" in dockerfile
    assert "requirements-dev.lock" in dockerfile
    assert dockerfile.count("pip install --require-hashes --no-deps") == 2
    assert 'pip install ".[dev]"' not in dockerfile
    assert "pip install -e" not in workflow
    assert workflow.count("requirements-dev.lock") == 4
    assert "--frozen-lockfile ||" not in workflow
