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

    if (-not $Force) {
        $answer = Read-Host '  Type "reset" to confirm, or anything else to cancel'
        if ($answer -ne 'reset') {
            Write-Host '  Cancelled. Nothing was removed.' -ForegroundColor Green
            exit 0
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
