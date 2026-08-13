<#
.SYNOPSIS
    Destroy the local demo database and start again from an empty schema.

.DESCRIPTION
    This is the only thing in the repository that deletes local data. It is a
    separate script, and not a switch on the launcher, on purpose: `-Reset` sat
    one keystroke away from the everyday command, and a flag that silently drops
    a volume is the kind of thing that eventually costs someone an afternoon.

    Removes the `pgdata` volume, which holds every tenant, user and lead created
    locally. Redis is dropped too, but that is uninteresting -- it holds
    rate-limit counters and revoked token ids, all of which are meant to be
    ephemeral.

    Requires typing the word `reset` unless -Force is given.

.PARAMETER Force
    Skip the confirmation prompt. For scripted use only.

.EXAMPLE
    .\scripts\reset-demo.ps1
#>
[CmdletBinding()]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '',
    Justification = 'Interactive console script; the output is for a human.')]
param([switch]$Force)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot

try {
    & docker version --format '{{.Server.Version}}' 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Docker Desktop is not running.' -ForegroundColor Red
        exit 1
    }

    Write-Host ''
    Write-Host '  This deletes the local demo database.' -ForegroundColor Yellow
    Write-Host '  Every tenant, user and lead created locally will be gone.' -ForegroundColor Yellow
    Write-Host '  Nothing outside this project is touched.'
    Write-Host ''

    # How much genuine, non-sample data is about to be destroyed. A founder now
    # keeps real prospects in this database, and a command called "reset demo"
    # must not quietly take them with it. Counting requires the stack to be up; if
    # it is not, the answer is unknown and unknown is treated as "there is some".
    $founderRecords = -1
    $running = (& docker compose ps --status running --services 2>$null) -join ' '
    if ($running -match 'postgres') {
        $reported = (& docker compose exec -T api python src/scripts/founder_data_report.py --count 2>$null | Select-Object -Last 1)
        if ($reported -match '^\d+$') { $founderRecords = [int]$reported }
    }

    if ($founderRecords -ne 0) {
        $describe = if ($founderRecords -gt 0) { "$founderRecords genuine (non-sample) record(s)" }
                    else { 'an unknown amount of genuine data (the database is not running, so it could not be checked)' }
        Write-Host "  This workspace holds $describe." -ForegroundColor Red
        Write-Host '  Those are real prospects, not demonstration data. They will be destroyed.' -ForegroundColor Red
        Write-Host ''
        Write-Host '  If you only want the sample businesses rebuilt, this is the wrong command.' -ForegroundColor Yellow
        Write-Host '  Use the demo refresh instead - it cannot touch real records:' -ForegroundColor Yellow
        Write-Host '      docker compose exec api python src/scripts/seed_sangam.py --refresh'
        Write-Host ''

        if ($Force) {
            Write-Host '  -Force does not apply when genuine records are present.' -ForegroundColor Red
            Write-Host '  Run without -Force and confirm deliberately.' -ForegroundColor Red
            exit 1
        }

        # A different sentence from the empty case on purpose: muscle memory for
        # typing "reset" must not carry somebody through this one.
        $phrase = 'delete real data'
        $answer = Read-Host "  Type '$phrase' to destroy them, or anything else to cancel"
        if ($answer -ne $phrase) {
            Write-Host '  Cancelled. Nothing was removed.' -ForegroundColor Green
            exit 0
        }
    }
    elseif (-not $Force) {
        $answer = Read-Host '  Type "reset" to confirm, or anything else to cancel'
        if ($answer -ne 'reset') {
            Write-Host '  Cancelled. Nothing was removed.' -ForegroundColor Green
            exit 0
        }
    }

    # A snapshot even here, where the intent is destruction: it is the difference
    # between a deliberate wipe and an unrecoverable one.
    if ($running -match 'postgres') {
        Write-Host ''
        Write-Host '==> Taking a safety snapshot first' -ForegroundColor Cyan
        & docker compose exec -T api python src/scripts/backup_local.py --reason before-reset
        if ($LASTEXITCODE -ne 0) {
            Write-Host '    The snapshot failed, so nothing was deleted.' -ForegroundColor Red
            Write-Host '    Fix the backup before resetting.' -ForegroundColor Red
            exit 1
        }
    }

    Write-Host ''
    Write-Host '==> Removing containers and the pgdata volume' -ForegroundColor Cyan
    & docker compose down -v
    if ($LASTEXITCODE -ne 0) {
        Write-Host '    docker compose down failed; nothing further was attempted.' -ForegroundColor Red
        exit 1
    }

    Write-Host '    Removed.' -ForegroundColor Green
    Write-Host ''
    Write-Host '  Start again with RUN_DEMO.cmd -- it will migrate and seed a fresh database.'
    Write-Host ''
}
finally {
    Pop-Location
}
