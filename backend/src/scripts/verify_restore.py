"""Restore an RDS PITR copy, reconcile it, prove RLS, then safely remove it.

This script must run from a private, in-VPC DR runner. It writes a machine-readable
artifact but never edits repository evidence or claims that an unexecuted drill passed.
"""

from __future__ import annotations

import json
import math
import os
import re
import secrets
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote_plus

import boto3
import psycopg
from psycopg import sql

RPO_LIMIT_SECONDS = 15 * 60
RTO_LIMIT_SECONDS = 4 * 60 * 60
TARGET_PREFIX = "airevenueos-dr-"
COUNT_TABLES = {
    "tenants": "app.tenants",
    "contacts": "app.contacts",
    "leads": "app.leads",
    "payments": "app.payments",
    "consent_records": "audit.consent_records",
}


class RdsClient(Protocol):
    def describe_db_instances(self, **kwargs: Any) -> dict[str, Any]: ...
    def restore_db_instance_to_point_in_time(self, **kwargs: Any) -> dict[str, Any]: ...
    def list_tags_for_resource(self, **kwargs: Any) -> dict[str, Any]: ...
    def delete_db_instance(self, **kwargs: Any) -> dict[str, Any]: ...
    def get_waiter(self, name: str) -> Any: ...


class SecretsClient(Protocol):
    def get_secret_value(self, **kwargs: Any) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class RestoreConfig:
    source_instance_id: str
    subnet_group: str
    security_group_ids: tuple[str, ...]
    database_name: str | None
    instance_class: str
    secret_arn: str | None
    target_instance_id: str
    region: str
    count_tolerance_percent: float
    count_tolerance_absolute: int
    keep_failed_restore: bool
    evidence_path: Path


@dataclass(slots=True)
class DrillEvidence:
    status: str
    source_instance_id: str
    target_instance_id: str
    started_at: str
    latest_restorable_time: str | None = None
    rpo_seconds: int | None = None
    restore_seconds: int | None = None
    rto_seconds: int | None = None
    source_counts: dict[str, int] | None = None
    restored_counts: dict[str, int] | None = None
    migration_head_verified: bool = False
    rls_suite_verified: bool = False
    cleanup_status: str = "not_started"
    error: str | None = None


def load_config(
    environ: dict[str, str] | None = None, *, now: datetime | None = None
) -> RestoreConfig:
    env = environ or dict(os.environ)
    required = {
        "SOURCE_DB_INSTANCE_ID": env.get("SOURCE_DB_INSTANCE_ID", "").strip(),
        "RESTORE_DB_SUBNET_GROUP": env.get("RESTORE_DB_SUBNET_GROUP", "").strip(),
        "RESTORE_DB_SECURITY_GROUP_IDS": env.get("RESTORE_DB_SECURITY_GROUP_IDS", "").strip(),
    }
    missing = sorted(name for name, value in required.items() if not value)
    if missing:
        raise ValueError(f"missing restore configuration: {', '.join(missing)}")

    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%d%H%M%S")
    target = env.get("RESTORE_DB_INSTANCE_ID", f"{TARGET_PREFIX}{stamp}").strip().lower()
    if not re.fullmatch(r"airevenueos-dr-[a-z0-9-]{1,48}", target):
        raise ValueError(
            "RESTORE_DB_INSTANCE_ID must start with airevenueos-dr- and contain only "
            "lowercase letters, numbers and hyphens"
        )
    security_groups = tuple(required["RESTORE_DB_SECURITY_GROUP_IDS"].split())
    if not all(re.fullmatch(r"sg-[0-9a-f]+", group) for group in security_groups):
        raise ValueError("RESTORE_DB_SECURITY_GROUP_IDS contains an invalid security group id")
    return RestoreConfig(
        source_instance_id=required["SOURCE_DB_INSTANCE_ID"],
        subnet_group=required["RESTORE_DB_SUBNET_GROUP"],
        security_group_ids=security_groups,
        database_name=env.get("RESTORE_DATABASE_NAME") or None,
        instance_class=env.get("RESTORE_DB_INSTANCE_CLASS", "db.t4g.medium"),
        secret_arn=env.get("SOURCE_DATABASE_SECRET_ARN") or None,
        target_instance_id=target,
        region=env.get("AWS_REGION", env.get("AWS_DEFAULT_REGION", "ap-south-1")),
        count_tolerance_percent=float(env.get("ROW_COUNT_TOLERANCE_PERCENT", "1")),
        count_tolerance_absolute=int(env.get("ROW_COUNT_TOLERANCE_ABSOLUTE", "100")),
        keep_failed_restore=env.get("KEEP_FAILED_RESTORE", "false").lower() == "true",
        evidence_path=Path(env.get("DR_EVIDENCE_PATH", "dr-evidence.json")).resolve(),
    )


def assert_counts_within_tolerance(
    source: dict[str, int],
    restored: dict[str, int],
    *,
    percent: float,
    absolute: int,
) -> None:
    failures: list[str] = []
    for name in COUNT_TABLES:
        source_count = source[name]
        restored_count = restored[name]
        tolerance = max(absolute, math.ceil(source_count * percent / 100))
        delta = source_count - restored_count
        if delta < 0 or delta > tolerance:
            failures.append(
                f"{name}: source={source_count}, restored={restored_count}, "
                f"allowed_delta=0..{tolerance}"
            )
    if failures:
        raise RuntimeError("row-count reconciliation failed: " + "; ".join(failures))


def _instance(rds: RdsClient, identifier: str) -> dict[str, Any]:
    rows = rds.describe_db_instances(DBInstanceIdentifier=identifier).get("DBInstances", [])
    if len(rows) != 1:
        raise RuntimeError(f"RDS instance {identifier!r} was not found uniquely")
    return dict(rows[0])


def _load_credentials(secrets_client: SecretsClient, *, secret_arn: str) -> tuple[str, str]:
    response = secrets_client.get_secret_value(SecretId=secret_arn)
    value = json.loads(response.get("SecretString") or "{}")
    username = str(value.get("username") or "")
    password = str(value.get("password") or "")
    if not username or not password:
        raise RuntimeError("database secret must contain username and password")
    return username, password


def _database_url(
    *, driver: str, username: str, password: str, host: str, port: int, database: str
) -> str:
    ssl_query = "ssl=require" if driver == "asyncpg" else "sslmode=require"
    return (
        f"postgresql+{driver}://{quote_plus(username)}:{quote_plus(password)}@"
        f"{host}:{port}/{quote_plus(database)}?{ssl_query}"
    )


def _psycopg_dsn(*, username: str, password: str, host: str, port: int, database: str) -> str:
    return (
        f"host={host} port={port} dbname={database} user={username} "
        f"password={password} sslmode=require connect_timeout=15"
    )


def _row_counts(dsn: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        for name, table in COUNT_TABLES.items():
            schema, relation = table.split(".", maxsplit=1)
            cursor.execute(
                sql.SQL("SELECT count(*) FROM {}.{}").format(
                    sql.Identifier(schema), sql.Identifier(relation)
                )
            )
            counts[name] = int(cursor.fetchone()[0])  # type: ignore[index]
    return counts


def _create_runtime_role(dsn: str, run_id: str) -> tuple[str, str]:
    role = f"airev_restore_{re.sub(r'[^a-z0-9]', '', run_id)[-24:]}"
    password = secrets.token_urlsafe(32)
    with psycopg.connect(dsn, autocommit=True) as connection, connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOBYPASSRLS IN ROLE airevenueos_app").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
    return role, password


def _run_database_gates(*, admin_url: str, runtime_url: str) -> None:
    repository = Path(__file__).resolve().parents[3]
    backend = repository / "backend"
    base_env = dict(os.environ)
    base_env.pop("ADMIN_DATABASE_URL", None)
    base_env["ALEMBIC_DATABASE_URL"] = admin_url
    base_env["DATABASE_URL"] = runtime_url
    base_env["TEST_DATABASE_URL"] = runtime_url
    base_env["PYTHONPATH"] = str(backend / "src")
    subprocess.run(
        [sys.executable, "-m", "alembic", "current", "--check-heads"],
        cwd=backend,
        env=base_env,
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/integration/test_rls_isolation.py",
            "-q",
        ],
        cwd=backend,
        env=base_env,
        check=True,
    )


def _safe_cleanup(rds: RdsClient, target_id: str, run_id: str) -> None:
    target = _instance(rds, target_id)
    arn = str(target.get("DBInstanceArn") or "")
    tags = {
        str(item.get("Key")): str(item.get("Value"))
        for item in rds.list_tags_for_resource(ResourceName=arn).get("TagList", [])
    }
    if tags.get("purpose") != "restore-verification" or tags.get("run-id") != run_id:
        raise RuntimeError("refusing to delete an RDS instance without exact drill ownership tags")
    rds.delete_db_instance(
        DBInstanceIdentifier=target_id,
        SkipFinalSnapshot=True,
        DeleteAutomatedBackups=True,
    )
    rds.get_waiter("db_instance_deleted").wait(
        DBInstanceIdentifier=target_id,
        WaiterConfig={"Delay": 30, "MaxAttempts": 120},
    )


def run_drill(
    config: RestoreConfig,
    *,
    rds: RdsClient | None = None,
    secrets_client: SecretsClient | None = None,
) -> DrillEvidence:
    rds_client = rds or boto3.client("rds", region_name=config.region)
    secret_client = secrets_client or boto3.client("secretsmanager", region_name=config.region)
    started = datetime.now(timezone.utc)
    started_clock = time.monotonic()
    run_id = config.target_instance_id.removeprefix(TARGET_PREFIX)
    evidence = DrillEvidence(
        status="running",
        source_instance_id=config.source_instance_id,
        target_instance_id=config.target_instance_id,
        started_at=started.isoformat(),
    )
    created = False
    failure: BaseException | None = None
    try:
        source = _instance(rds_client, config.source_instance_id)
        latest = source.get("LatestRestorableTime")
        if not isinstance(latest, datetime):
            raise RuntimeError("source instance did not report LatestRestorableTime")
        latest = latest.astimezone(timezone.utc)
        rpo_seconds = max(0, int((datetime.now(timezone.utc) - latest).total_seconds()))
        evidence.latest_restorable_time = latest.isoformat()
        evidence.rpo_seconds = rpo_seconds
        if rpo_seconds > RPO_LIMIT_SECONDS:
            raise RuntimeError(
                f"latest recovery point is {rpo_seconds}s old; RPO limit is {RPO_LIMIT_SECONDS}s"
            )

        source_secret = config.secret_arn or str(
            (source.get("MasterUserSecret") or {}).get("SecretArn") or ""
        )
        if not source_secret:
            raise RuntimeError(
                "SOURCE_DATABASE_SECRET_ARN is required when RDS has no managed master secret"
            )
        username, password = _load_credentials(secret_client, secret_arn=source_secret)
        database = config.database_name or str(source.get("DBName") or "postgres")
        source_endpoint = source.get("Endpoint") or {}
        source_dsn = _psycopg_dsn(
            username=username,
            password=password,
            host=str(source_endpoint["Address"]),
            port=int(source_endpoint["Port"]),
            database=database,
        )
        evidence.source_counts = _row_counts(source_dsn)

        restore_started = time.monotonic()
        rds_client.restore_db_instance_to_point_in_time(
            SourceDBInstanceIdentifier=config.source_instance_id,
            TargetDBInstanceIdentifier=config.target_instance_id,
            UseLatestRestorableTime=True,
            DBInstanceClass=config.instance_class,
            DBSubnetGroupName=config.subnet_group,
            VpcSecurityGroupIds=list(config.security_group_ids),
            MultiAZ=False,
            PubliclyAccessible=False,
            BackupRetentionPeriod=0,
            DeletionProtection=False,
            CopyTagsToSnapshot=False,
            Tags=[
                {"Key": "purpose", "Value": "restore-verification"},
                {"Key": "run-id", "Value": run_id},
                {"Key": "owner", "Value": "platform-team"},
            ],
        )
        created = True
        rds_client.get_waiter("db_instance_available").wait(
            DBInstanceIdentifier=config.target_instance_id,
            WaiterConfig={"Delay": 30, "MaxAttempts": 240},
        )
        evidence.restore_seconds = int(time.monotonic() - restore_started)
        target = _instance(rds_client, config.target_instance_id)
        endpoint = target.get("Endpoint") or {}
        target_dsn = _psycopg_dsn(
            username=username,
            password=password,
            host=str(endpoint["Address"]),
            port=int(endpoint["Port"]),
            database=database,
        )
        evidence.restored_counts = _row_counts(target_dsn)
        assert_counts_within_tolerance(
            evidence.source_counts,
            evidence.restored_counts,
            percent=config.count_tolerance_percent,
            absolute=config.count_tolerance_absolute,
        )

        runtime_user, runtime_password = _create_runtime_role(target_dsn, run_id)
        admin_url = _database_url(
            driver="psycopg",
            username=username,
            password=password,
            host=str(endpoint["Address"]),
            port=int(endpoint["Port"]),
            database=database,
        )
        runtime_url = _database_url(
            driver="asyncpg",
            username=runtime_user,
            password=runtime_password,
            host=str(endpoint["Address"]),
            port=int(endpoint["Port"]),
            database=database,
        )
        _run_database_gates(admin_url=admin_url, runtime_url=runtime_url)
        evidence.migration_head_verified = True
        evidence.rls_suite_verified = True
        evidence.rto_seconds = int(time.monotonic() - started_clock)
        if evidence.rto_seconds > RTO_LIMIT_SECONDS:
            raise RuntimeError(
                f"restore verification took {evidence.rto_seconds}s; "
                f"RTO limit is {RTO_LIMIT_SECONDS}s"
            )
        evidence.status = "passed"
    except BaseException as exc:
        failure = exc
        evidence.status = "failed"
        evidence.error = f"{type(exc).__name__}: {exc}"[:2000]
    finally:
        if created and not (failure and config.keep_failed_restore):
            try:
                _safe_cleanup(rds_client, config.target_instance_id, run_id)
                evidence.cleanup_status = "deleted"
            except BaseException as cleanup_error:
                evidence.cleanup_status = "failed"
                evidence.status = "failed"
                evidence.error = f"cleanup failed: {type(cleanup_error).__name__}: {cleanup_error}"[
                    :2000
                ]
                failure = cleanup_error
        elif created:
            evidence.cleanup_status = "retained_by_configuration"
        config.evidence_path.parent.mkdir(parents=True, exist_ok=True)
        config.evidence_path.write_text(
            json.dumps(asdict(evidence), indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
    if failure is not None:
        raise failure
    return evidence


def main() -> int:
    try:
        evidence = run_drill(load_config())
    except Exception as exc:
        sys.stderr.write(f"restore verification failed: {type(exc).__name__}: {exc}\n")
        return 1
    sys.stdout.write(
        "restore verification passed: "
        f"RPO={evidence.rpo_seconds}s RTO={evidence.rto_seconds}s "
        f"cleanup={evidence.cleanup_status}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
