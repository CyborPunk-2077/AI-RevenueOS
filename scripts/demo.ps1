<#
.SYNOPSIS
    Start the AI RevenueOS local demo on Windows. No GNU make required.

.DESCRIPTION
    Builds and starts PostgreSQL, Redis, the API and the web app, waits for them,
    applies migrations, seeds reference and demo data, then prints the URL and the
    sign-in details.

    Safe to re-run: the migrations and both seed scripts are idempotent.

    Targets Windows PowerShell 5.1 as shipped with Windows, so it also runs under
    PowerShell 7 without changes.

.PARAMETER Password
    The demo password. When omitted a random one is generated and shown once.

.PARAMETER Reset
    Delete the database volume first and start from an empty schema.

.PARAMETER SkipBuild
    Reuse existing images instead of rebuilding.

.PARAMETER TimeoutSeconds
    How long to wait for each service. Default 300: the dev server compiles the
    route on first request, which is slow on a cold Docker Desktop.

.EXAMPLE
    .\scripts\demo.ps1

.EXAMPLE
    .\scripts\demo.ps1 -Reset -Password 'my-local-passphrase'
#>
[CmdletBinding()]
# Write-Host is correct here: this is an interactive launcher whose output is for
# a human at a console, not a pipeline.
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '',
    Justification = 'Console launcher; the output is deliberately not pipeline data.')]
# The demo password is printed to the screen by design, and has to reach docker as
# plain text, so SecureString would buy nothing.
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingPlainTextForPassword', 'Password',
    Justification = 'Local demo credential that is displayed on purpose.')]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSReviewUnusedParameter', 'TimeoutSeconds',
    Justification = 'Used as the default for the Timeout parameter of Wait-ForUrl.')]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSUseShouldProcessForStateChangingFunctions', '',
    Justification = 'New-DemoPassword returns a string and changes nothing.')]
param(
    [string]$Password,
    [switch]$Reset,
    [switch]$SkipBuild,
    [int]$TimeoutSeconds = 300
)

$ErrorActionPreference = 'Stop'

# Run from the repository root regardless of where this was invoked.
$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot

$ApiUrl   = 'http://localhost:8000'
$WebUrl   = 'http://localhost:3000'
$Services = @('postgres', 'redis', 'api', 'web')

function Write-Step { param([string]$Text) Write-Host "==> $Text" -ForegroundColor Cyan }
function Write-Ok   { param([string]$Text) Write-Host "    $Text" -ForegroundColor Green }
function Write-Warn { param([string]$Text) Write-Host "    $Text" -ForegroundColor Yellow }
function Write-Err  { param([string]$Text) Write-Host "    $Text" -ForegroundColor Red }

function Invoke-Compose {
    <#
        Runs docker compose and throws on a non-zero exit code.

        The arguments arrive as one bound array rather than as remaining arguments,
        so tokens such as -T and -d are passed through to docker instead of being
        parsed as parameters of this function.
    #>
    param([Parameter(Mandatory)][string[]]$ComposeArgs)

    & docker compose @ComposeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose $($ComposeArgs -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Wait-ForUrl {
    <#
        Polls a URL until it answers, and throws if the timeout elapses.

        It throws rather than returning $false on purpose. An earlier version
        returned a boolean, but `docker compose logs` writes to the function's
        output stream, so the caller received @(<log lines>, $false) -- a non-empty
        array, which is truthy -- and sailed past the failure. Throwing cannot be
        swallowed that way, and the caller's catch block already reports it.
    #>
    param(
        [Parameter(Mandatory)][string]$Url,
        [Parameter(Mandatory)][string]$Name,
        [int]$Timeout = $TimeoutSeconds
    )
    $deadline = (Get-Date).AddSeconds($Timeout)
    $frames = @('|', '/', '-', '\')
    $i = 0
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                Write-Host "`r    $Name is up ($Url)                         " -ForegroundColor Green
                return
            }
        } catch {
            # Not listening yet, or still compiling. Keep waiting.
            $null = $_
        }
        Write-Host "`r    waiting for $Name $($frames[$i % 4])" -NoNewline
        $i = $i + 1
        Start-Sleep -Seconds 2
    }
    Write-Host ''
    Write-Err "$Name did not respond at $Url within $Timeout seconds. Last 40 log lines:"
    # Out-Host keeps this off the output stream, for the reason described above.
    & docker compose logs --tail=40 $Name 2>&1 | Out-Host
    throw "$Name did not become ready within $Timeout seconds."
}

function New-DemoPassword {
    # RandomNumberGenerator.Create().GetBytes works on both Windows PowerShell 5.1
    # and PowerShell 7; the newer static Fill() does not exist on 5.1.
    $bytes = New-Object 'System.Byte[]' 24
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    $raw = [Convert]::ToBase64String($bytes) -replace '[+/=]', ''
    return "demo-$($raw.Substring(0, [Math]::Min(20, $raw.Length)))"
}

$generated = $false

try {
    # --- preflight ---------------------------------------------------------
    Write-Step 'Checking Docker'
    $engine = & docker version --format '{{.Server.Version}}' 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Err 'Docker Desktop is not running. Start it, wait for the whale to settle, and run this again.'
        exit 1
    }
    Write-Ok "Docker engine $engine"

    if (-not $Password) {
        $Password = New-DemoPassword
        $generated = $true
    } elseif ($Password.Length -lt 12) {
        Write-Err 'The demo password must be at least 12 characters; the account policy rejects shorter ones.'
        exit 1
    }

    # --- reset -------------------------------------------------------------
    if ($Reset) {
        Write-Step 'Removing existing containers and the database volume'
        Invoke-Compose -ComposeArgs @('down', '-v')
        Write-Ok 'Previous state removed'
    }

    # --- build -------------------------------------------------------------
    if (-not $SkipBuild) {
        Write-Step 'Building images (api, web) - several minutes on a first run'
        Invoke-Compose -ComposeArgs @('build', 'api', 'web')
        Write-Ok 'Images built'
    }

    # --- start -------------------------------------------------------------
    Write-Step "Starting $($Services -join ', ')"
    Invoke-Compose -ComposeArgs (@('up', '-d') + $Services)
    Write-Ok 'Containers started'

    Write-Step 'Waiting for the API'
    Wait-ForUrl -Url "$ApiUrl/health/liveness" -Name 'api'

    # --- migrate and seed --------------------------------------------------
    # These run inside the api container. It carries ALEMBIC_DATABASE_URL, the
    # owner credential that migrations and reference-data seeding require: the
    # runtime role deliberately cannot create tables or write plans and templates.
    Write-Step 'Applying database migrations'
    Invoke-Compose -ComposeArgs @('exec', '-T', 'api', 'alembic', 'upgrade', 'head')
    Write-Ok 'Schema at head'

    Write-Step 'Seeding reference data (plans, permissions, industry templates)'
    Invoke-Compose -ComposeArgs @('exec', '-T', 'api', 'python', 'src/scripts/seed.py')
    Write-Ok 'Reference data seeded'

    Write-Step 'Seeding demo tenants'
    Invoke-Compose -ComposeArgs @(
        'exec', '-T', '-e', "DEMO_PASSWORD=$Password", 'api', 'python', 'src/scripts/seed_demo.py'
    )
    Write-Ok 'Demo tenants seeded'

    # --- wait for the web app ---------------------------------------------
    Write-Step 'Waiting for the web app (first request compiles the route)'
    Wait-ForUrl -Url "$WebUrl/login" -Name 'web'

    # --- done --------------------------------------------------------------
    $rule = ('=' * 68)
    Write-Host ''
    Write-Host $rule -ForegroundColor Green
    Write-Host '  AI RevenueOS demo is ready' -ForegroundColor Green
    Write-Host $rule -ForegroundColor Green
    Write-Host ''
    Write-Host "  Open        $WebUrl"
    Write-Host "  API docs    $ApiUrl/v1/docs"
    Write-Host ''
    Write-Host '  Sign in as either tenant:' -ForegroundColor Cyan
    Write-Host '    asha@acme.test     tenant acme    (has sample leads)'
    Write-Host '    ravi@globex.test   tenant globex  (empty, which is the point)'
    Write-Host ''
    Write-Host "  Password    $Password" -ForegroundColor Yellow
    if ($generated) {
        Write-Host '              generated for this run and stored nowhere;'
        Write-Host '              pass -Password to choose your own'
    }
    Write-Host ''
    Write-Host '  Sign in as acme, create a lead, open it, edit it, refresh.'
    Write-Host '  Then sign in as globex: none of acme''s records are visible.'
    Write-Host ''
    Write-Host '  Stop        docker compose down'
    Write-Host '  Logs        docker compose logs -f api web'
    Write-Host $rule -ForegroundColor Green
    Write-Host ''
}
catch {
    Write-Host ''
    Write-Err $_.Exception.Message
    Write-Host ''
    Write-Warn 'Troubleshooting:'
    Write-Warn '  docker compose logs api web      show what failed'
    Write-Warn '  .\scripts\demo.ps1 -Reset        start from an empty database'
    exit 1
}
finally {
    Pop-Location
}
