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

.PARAMETER SkipBuild
    Reuse existing images instead of rebuilding.

.PARAMETER TimeoutSeconds
    How long to wait for each service. Default 300: the dev server compiles the
    route on first request, which is slow on a cold Docker Desktop.

.EXAMPLE
    .\scripts\demo.ps1

.EXAMPLE
    .\scripts\demo.ps1 -Password 'my-local-passphrase'

.NOTES
    This never destroys data. Stopping and restarting keeps every lead, user and
    tenant, because the database lives in the named `pgdata` volume and nothing
    here removes it. To start from an empty schema, run the separate, explicitly
    confirmed `RESET_DEMO.cmd` (or `scripts/reset-demo.ps1`).
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
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingPlainTextForPassword', 'DemoPassword',
    Justification = 'Same local demo credential, handed to Test-DemoLogin.')]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSReviewUnusedParameter', 'TimeoutSeconds',
    Justification = 'Used as the default for the Timeout parameter of Wait-ForUrl.')]
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSUseShouldProcessForStateChangingFunctions', '',
    Justification = 'New-DemoPassword returns a string and changes nothing.')]
param(
    [string]$Password,
    [switch]$SkipBuild,
    # Opening a browser is right for the double-click path and wrong for CI and
    # for the browser tests, which drive their own.
    [switch]$NoBrowser,
    [int]$TimeoutSeconds = 300
)

$ErrorActionPreference = 'Stop'

# Windows PowerShell 5.1 does not load System.Net.Http by default, and the
# readiness probe needs HttpClient - see Get-HttpStatus for why Invoke-WebRequest
# is not usable here. PowerShell 7 already has it, so this is a no-op there.
Add-Type -AssemblyName System.Net.Http

# Run from the repository root regardless of where this was invoked.
$RepoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $RepoRoot

$ApiUrl   = 'http://localhost:8000'
$WebUrl   = 'http://localhost:3000'
# The whole stack. Compose resolves the actual ordering from depends_on +
# healthchecks; this list is what gets started, not the order it happens in.
# Postgres and Redis gate the API and every worker pool; a worker pool gates Beat;
# the API gates the web app.
$Services = @(
    'postgres', 'redis', 'api',
    'worker-comms', 'worker-ai', 'worker-general', 'worker-bulk',
    'beat', 'web'
)
# Services that report health to Docker. Beat has no probe of its own -- Celery
# Beat exposes nothing to check -- so it is verified as running, not healthy.
$HealthyServices = @(
    'postgres', 'redis', 'api', 'worker-comms', 'worker-ai', 'worker-general', 'worker-bulk'
)

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

function Get-HttpStatus {
    <#
        One bounded HTTP GET. Returns the status code, or 0 with the reason in
        $script:LastProbeError when the request did not complete.

        This uses HttpClient rather than Invoke-WebRequest for one specific
        reason. `Invoke-WebRequest -TimeoutSec n` sets HttpWebRequest.Timeout,
        which bounds only the wait for the *response headers*. The response body
        is governed by ReadWriteTimeout, which -TimeoutSec does not touch and
        which defaults to 300 seconds on this platform. A server that returns
        headers immediately and then streams the body slowly - exactly what the
        Next.js dev server does while it is compiling a route - therefore blocks
        the call for up to five minutes regardless of the timeout that was asked
        for, and the polling loop around it cannot re-check its own deadline
        while that is happening.

        HttpClient.Timeout bounds the whole operation, and ResponseHeadersRead
        means the status line is enough: readiness is "the app answered", not
        "the app finished streaming its HTML".
    #>
    param(
        [Parameter(Mandatory)][string]$Url,
        [Parameter(Mandatory)][int]$TimeoutSec
    )

    $client = [System.Net.Http.HttpClient]::new()
    try {
        $client.Timeout = [TimeSpan]::FromSeconds([Math]::Max(1, $TimeoutSec))
        $request = [System.Net.Http.HttpRequestMessage]::new(
            [System.Net.Http.HttpMethod]::Get, $Url)
        $response = $client.SendAsync(
            $request, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead
        ).GetAwaiter().GetResult()
        try {
            return [int]$response.StatusCode
        } finally {
            $response.Dispose()
        }
    } catch {
        # Connection refused, DNS failure, or the bounded timeout elapsed. All of
        # them mean "not ready yet"; the reason is kept for the final message.
        #
        # Unwrapped to the innermost exception on purpose: PowerShell wraps this
        # as 'Exception calling "GetResult" with "0" argument(s)', which tells an
        # operator nothing. The inner message is the one that says whether the
        # port refused the connection or the request timed out - and those two
        # need completely different things done about them.
        $inner = $_.Exception
        while ($inner.InnerException) { $inner = $inner.InnerException }
        $script:LastProbeError = if ($inner -is [System.Threading.Tasks.TaskCanceledException]) {
            # Deliberately does not guess whether the connection was established:
            # from here the two are indistinguishable, and claiming one would send
            # somebody looking in the wrong place.
            "no answer within ${TimeoutSec}s"
        } else {
            $inner.Message
        }
        return 0
    } finally {
        $client.Dispose()
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

        **The per-attempt window is deliberately generous.** It used to be five
        seconds, which is shorter than a cold Next.js dev server takes to compile
        `/login` for the first time - so every attempt aborted the compile, the
        next attempt started it again, and the launcher could sit there while a
        browser in another window loaded the same URL perfectly well, because a
        browser waits. A long window costs nothing when the service is genuinely
        down: an unavailable port refuses the connection immediately rather than
        hanging, so the loop still spins fast and still reaches its deadline.

        Every attempt is individually bounded and the deadline is re-checked
        between attempts, so the total wall-clock time cannot exceed $Timeout by
        more than one attempt window.
    #>
    param(
        [Parameter(Mandatory)][string]$Url,
        [Parameter(Mandatory)][string]$Name,
        [int]$Timeout = $TimeoutSeconds,
        # Long enough for a first compile, short enough that the operator sees
        # the deadline honoured rather than a frozen spinner.
        [int]$AttemptTimeout = 30
    )

    $started = Get-Date
    $deadline = $started.AddSeconds($Timeout)
    $script:LastProbeError = 'no attempt completed'

    while ($true) {
        $remaining = [int][Math]::Ceiling(($deadline - (Get-Date)).TotalSeconds)
        if ($remaining -le 0) { break }

        # Never let a single attempt run past the deadline.
        $status = Get-HttpStatus -Url $Url -TimeoutSec ([Math]::Min($AttemptTimeout, $remaining))

        # Anything the app answered itself counts. A 4xx from /login is the app
        # replying; only 5xx and "no answer at all" mean it is not up yet.
        if ($status -ge 200 -and $status -lt 500) {
            Write-Host "`r    $Name is up ($Url)                                        " -ForegroundColor Green
            return
        }

        $waited = [int]((Get-Date) - $started).TotalSeconds
        Write-Host "`r    waiting for $Name - ${waited}s elapsed, ${remaining}s left    " -NoNewline

        # Do not sleep past the deadline: the operator asked for a bound and the
        # last thing they should see is the script honouring it.
        $left = ($deadline - (Get-Date)).TotalSeconds
        if ($left -le 0) { break }
        Start-Sleep -Seconds ([Math]::Min(2, [Math]::Ceiling($left)))
    }

    Write-Host ''
    Write-Err "$Name did not respond at $Url within $Timeout seconds."
    Write-Err "Last probe result: $script:LastProbeError"
    Write-Err 'Last 40 log lines:'
    # Out-Host keeps this off the output stream, for the reason described above.
    & docker compose logs --tail=40 $Name 2>&1 | Out-Host
    throw "$Name did not become ready within $Timeout seconds."
}

function Wait-ForStack {
    <#
        Wait until every named service reports healthy, and throw if it does not.

        Workers and Beat expose no HTTP endpoint, so polling a URL cannot tell you
        whether the tier came up. This reads Docker's own health state instead.

        Bounded, and it gives up early rather than spinning: a container that has
        already exited will never become healthy, so waiting the full timeout for
        it only delays showing the operator the logs that explain why.
    #>
    param(
        [Parameter(Mandatory)][string[]]$Names,
        [int]$Timeout = $TimeoutSeconds
    )
    $deadline = (Get-Date).AddSeconds($Timeout)
    while ((Get-Date) -lt $deadline) {
        $pending = @()
        $dead = @()
        foreach ($name in $Names) {
            $state = (& docker inspect --format '{{.State.Health.Status}}' "airevenueos-$name-1" 2>$null)
            if ($LASTEXITCODE -ne 0 -or -not $state) {
                # No health block, or the container is not there yet.
                $running = (& docker inspect --format '{{.State.Status}}' "airevenueos-$name-1" 2>$null)
                if ($running -eq 'exited' -or $running -eq 'dead') { $dead += $name } else { $pending += $name }
                continue
            }
            switch ($state.Trim()) {
                'healthy'   { }
                'unhealthy' { $dead += $name }
                default     { $pending += $name }
            }
        }

        if ($dead.Count -gt 0) {
            Write-Host ''
            Write-Err "These services failed to start: $($dead -join ', ')"
            foreach ($name in $dead) {
                Write-Warn "--- $name ---"
                & docker compose logs --tail=30 $name 2>&1 | Out-Host
            }
            throw "$($dead -join ', ') did not start"
        }
        if ($pending.Count -eq 0) {
            Write-Host "`r    all services healthy                                   " -ForegroundColor Green
            return
        }
        Write-Host "`r    waiting for $($pending -join ', ')          " -NoNewline
        Start-Sleep -Seconds 3
    }

    Write-Host ''
    Write-Err "Timed out after $Timeout seconds waiting for the stack. Recent logs:"
    & docker compose ps 2>&1 | Out-Host
    foreach ($name in $Names) { & docker compose logs --tail=15 $name 2>&1 | Out-Host }
    throw "the stack did not become healthy within $Timeout seconds"
}


function Invoke-ComposeCapture {
    <#
        Runs docker compose, shows the output, and returns it as well.

        `Invoke-Compose` writes straight to the host, which is right for every
        other call. This one needs the text too, and the seed's own progress must
        still appear as it happens rather than arriving in a silent block at the
        end.
    #>
    param([Parameter(Mandatory)][string[]]$ComposeArgs)

    $lines = & docker compose @ComposeArgs 2>&1 | ForEach-Object {
        Write-Host $_
        $_
    }
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose $($ComposeArgs -join ' ') failed with exit code $LASTEXITCODE"
    }
    return ($lines | Out-String)
}

function Get-PasswordAppliesTo {
    <#
        Which accounts the seed actually applied the supplied password to.

        `seed_sangam.py` prints one machine-readable line for this. An empty list
        is the normal answer on any run after the first, and means the password
        this script generated was set on nobody - so there is nothing it may
        legitimately verify with.

        A missing line is treated the same way. An older container image would not
        print it, and guessing is exactly the failure this replaces.
    #>
    param([Parameter(Mandatory)][AllowEmptyString()][string]$SeedOutput)

    $match = [regex]::Match($SeedOutput, 'SANGAM_PASSWORD_APPLIES_TO=([^\r\n]*)')
    if (-not $match.Success) { return @() }
    return $match.Groups[1].Value.Split(',') |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ }
}

function Select-VerifiableAccount {
    <#
        One account whose password this run genuinely knows, or $null.

        Prefers the founder because that is the account the printed instructions
        send people to, but any account the password was applied to proves the
        same path: the same seed, the same hash, the same BFF, the same cookie.
    #>
    param([string[]]$AppliesTo)

    if (-not $AppliesTo -or $AppliesTo.Count -eq 0) { return $null }
    if ($AppliesTo -contains 'abhishek@sangam.co.in') { return 'abhishek@sangam.co.in' }
    return $AppliesTo[0]
}

function Test-DemoLogin {
    <#
        Sign in as a demo user through the web app, the way the browser does.

        This exists because a previous release printed credentials that could not
        log in: the API answered 400 "Invalid host header" to every call from the
        BFF, while its own health check -- which uses localhost -- kept reporting
        the container healthy. A launcher that only waits for health is therefore
        not evidence of anything. This is.
    #>
    param(
        [Parameter(Mandatory)][string]$Email,
        [Parameter(Mandatory)][string]$DemoPassword
    )
    $body = @{ email = $Email; password = $DemoPassword } | ConvertTo-Json -Compress
    try {
        $response = Invoke-WebRequest -Uri "$WebUrl/api/auth/login" -Method POST `
            -ContentType 'application/json' -Body $body -UseBasicParsing -TimeoutSec 30
    } catch {
        # Invoke-WebRequest throws on any non-2xx, so read the real status out.
        $status = 'no response'
        $detail = $_.Exception.Message
        # PowerShell 7 puts the response body here; Windows PowerShell 5.1 leaves it
        # on the stream, so both are handled.
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            $detail = $_.ErrorDetails.Message
        }
        if ($_.Exception.Response) {
            $status = [int]$_.Exception.Response.StatusCode
            if (-not ($_.ErrorDetails -and $_.ErrorDetails.Message)) {
                try {
                    $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
                    $detail = $reader.ReadToEnd()
                    $reader.Close()
                } catch { $null = $_ }
            }
        }
        Write-Err "$Email could not sign in (HTTP $status): $detail"
        Write-Err 'The API rejected the request the web app made. Check the upstream status:'
        & docker compose logs --tail=30 web 2>&1 | Out-Host
        throw "demo login failed for $Email"
    }
    if ($response.StatusCode -ne 200) {
        throw "demo login for $Email returned HTTP $($response.StatusCode)"
    }
    Write-Ok "$Email signs in"
}

function Find-DockerDesktop {
    <#
        Where Docker Desktop is installed, or $null if it is not.

        The registry is asked first because it is where the installer records the
        real location, which is not always Program Files. The fixed paths are a
        fallback for installs that did not write that key.
    #>
    $candidates = @()
    foreach ($key in @(
            'HKLM:\SOFTWARE\Docker Inc.\Docker\1.0',
            'HKLM:\SOFTWARE\WOW6432Node\Docker Inc.\Docker\1.0')) {
        try {
            $path = (Get-ItemProperty -Path $key -Name AppPath -ErrorAction Stop).AppPath
            if ($path) { $candidates += (Join-Path $path 'Docker Desktop.exe') }
        } catch { $null = $_ }
    }
    $candidates += @(
        (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Docker\Docker\Docker Desktop.exe'),
        (Join-Path $env:LOCALAPPDATA 'Docker\Docker Desktop.exe')
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) { return $candidate }
    }
    return $null
}

function Test-DockerEngine {
    <#
        The engine version string when the daemon answers, otherwise $null.

        `docker version --format '{{.Server.Version}}'` is the right probe: it
        talks to the daemon. `docker --version` reports only the client and
        succeeds happily while Docker Desktop is still starting.

        The error handling is not defensive padding. This script runs under
        `$ErrorActionPreference = 'Stop'`, and Windows PowerShell wraps a native
        command's stderr in an ErrorRecord - so when the daemon is down, docker
        writing "cannot find the pipe" to stderr became a *terminating* error and
        killed the launcher on the very line whose job is to discover that the
        daemon is down. Silencing the preference locally and reading $LASTEXITCODE
        is what makes "not running" an answer instead of a crash.
    #>
    param([int]$TimeoutMs = 10000)

    # Bounded, because `docker version` does not always fail fast. While Docker
    # Desktop is starting the named pipe can exist but never answer, and the CLI
    # then blocks indefinitely - which made the launcher look frozen at "Starting
    # it for you" rather than waiting visibly. Anything that has not answered
    # inside the timeout is treated as "not ready yet", and the caller tries again.
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = 'docker'
    $info.Arguments = 'version --format {{.Server.Version}}'
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true

    $process = $null
    try {
        $process = [System.Diagnostics.Process]::Start($info)
        if (-not $process.WaitForExit($TimeoutMs)) {
            try { $process.Kill() } catch { $null = $_ }
            return $null
        }
        if ($process.ExitCode -ne 0) { return $null }
        $text = $process.StandardOutput.ReadToEnd().Trim()
        if (-not $text) { return $null }
        return $text
    } catch {
        # `docker` not on PATH lands here, and is a legitimate "no engine".
        return $null
    } finally {
        if ($process) { $process.Dispose() }
        $Error.Clear()
    }
}

function Start-DockerEngine {
    <#
        Bring the Docker daemon up, starting Docker Desktop if it is not running.

        The owner should not have to know what a daemon is, so this does the whole
        job: it launches Docker Desktop, waits for the engine to actually answer,
        and only gives up with a plain-English message. It never touches
        containers or volumes belonging to other projects - starting the engine is
        the entire scope.
    #>
    param([int]$Timeout = 240)

    $version = Test-DockerEngine
    if ($version) {
        Write-Ok "Docker engine $version"
        return
    }

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw @'
Docker Desktop does not appear to be installed on this computer.

Sangam runs inside Docker, so it is needed once. Install Docker Desktop from
https://www.docker.com/products/docker-desktop/ , restart the computer if it asks
you to, then double-click RUN_DEMO.cmd again. Nothing else is required.
'@
    }

    $exe = Find-DockerDesktop
    if (-not $exe) {
        throw @'
The docker command exists but Docker Desktop could not be found to start it.

Start Docker Desktop from the Start menu, wait for the whale icon to stop
animating, then double-click RUN_DEMO.cmd again.
'@
    }

    Write-Warn 'Docker Desktop is not running yet. Starting it for you.'
    try {
        Start-Process -FilePath $exe -ArgumentList '-Autostart' -ErrorAction Stop | Out-Null
    } catch {
        throw "Could not start Docker Desktop automatically: $($_.Exception.Message)"
    }

    # First start after a reboot genuinely takes a couple of minutes, so this
    # waits patiently and says so rather than looking frozen.
    $deadline = (Get-Date).AddSeconds($Timeout)
    $frames = @('|', '/', '-', '\')
    $i = 0
    while ((Get-Date) -lt $deadline) {
        Write-Host "`r    waiting for Docker to finish starting $($frames[$i % 4])" -NoNewline
        $i = $i + 1
        # Short probe timeout inside the loop so the spinner keeps moving and the
        # overall deadline is respected even when the CLI is hanging.
        $version = Test-DockerEngine -TimeoutMs 5000
        if ($version) {
            Write-Host "`r    Docker engine $version                              " -ForegroundColor Green
            return
        }
        Start-Sleep -Seconds 2
    }
    Write-Host ''
    throw @"
Docker Desktop was started but its engine did not come up within $Timeout seconds.

This usually means it is still finishing a first-time setup or an update. Give it
another minute, then double-click RUN_DEMO.cmd again.
"@
}

function Open-Sangam {
    <#
        Open the app in the default browser. Best-effort by design: a machine with
        no default browser must not turn a working demo into a failed run.
    #>
    param([Parameter(Mandatory)][string]$Url)
    try {
        Start-Process $Url -ErrorAction Stop | Out-Null
        Write-Ok "Opened $Url in your browser"
    } catch {
        Write-Warn "Could not open a browser automatically. Go to $Url yourself."
    }
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
    Start-DockerEngine

    if (-not $Password) {
        $Password = New-DemoPassword
        $generated = $true
    } elseif ($Password.Length -lt 12) {
        Write-Err 'The demo password must be at least 12 characters; the account policy rejects shorter ones.'
        exit 1
    }

    # --- build -------------------------------------------------------------
    if (-not $SkipBuild) {
        Write-Step 'Building images (api, web) - several minutes on a first run'
        Invoke-Compose -ComposeArgs @('build')
        Write-Ok 'Images built'
    }

    # --- start -------------------------------------------------------------
    Write-Step "Starting $($Services -join ', ')"
    Invoke-Compose -ComposeArgs (@('up', '-d') + $Services)
    Write-Ok 'Containers started'

    Write-Step 'Waiting for the API'
    Wait-ForUrl -Url "$ApiUrl/health/liveness" -Name 'api'

    Write-Step 'Waiting for the worker tier and scheduler'
    Wait-ForStack -Names $HealthyServices

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

    # The founders' own workspace, filled with realistic Bengaluru prospects.
    # Additive and idempotent: if it already holds prospects nothing is rewritten,
    # because this tenant is meant to be used for real prospecting. Rebuild the
    # synthetic rows deliberately with:
    #   docker compose exec api python src/scripts/seed_sangam.py --refresh
    #
    # The output is captured as well as shown, because one line of it -
    # SANGAM_PASSWORD_APPLIES_TO - is the only thing that can tell this script
    # which accounts the password it just printed was actually set on. Existing
    # people deliberately keep their own passwords, so on every run after the
    # first that list is empty.
    Write-Step 'Seeding the Sangam workspace'
    $seedOutput = Invoke-ComposeCapture -ComposeArgs @(
        'exec', '-T', '-e', "DEMO_PASSWORD=$Password", 'api', 'python', 'src/scripts/seed_sangam.py'
    )
    $passwordAppliesTo = Get-PasswordAppliesTo -SeedOutput $seedOutput
    Write-Ok 'Sangam workspace seeded'

    # --- wait for the web app ---------------------------------------------
    Write-Step 'Waiting for the web app (first request compiles the route)'
    Wait-ForUrl -Url "$WebUrl/login" -Name 'web'

    # --- prove the printed credentials actually work -----------------------
    # One verification, not three. Sign-in is rate limited to five attempts per IP
    # per fifteen minutes, and every attempt the launcher spends is one the person
    # at the keyboard no longer has - verifying all three accounts left them able
    # to sign in twice before being locked out of their own demo. One successful
    # sign-in proves the whole credential path: same password, same seed, same
    # cookie handling.
    #
    # **Only an account the password was actually applied to.** This used to test
    # abhishek@sangam.co.in unconditionally. That account normally already exists,
    # normally keeps the password it already had - which is the correct, deliberate
    # behaviour of the seed - and so the launcher was signing in with a credential
    # that had never been set on it. A perfectly healthy stack failed on a 401, and
    # the failure pointed at credentials, which sent people to RESET_DEMO to fix a
    # problem that did not exist.
    #
    # A verification that cannot be performed is not a failure. It is simply
    # unavailable, and the honest thing is to say so and carry on.
    $verifyAccount = Select-VerifiableAccount -AppliesTo $passwordAppliesTo
    if ($verifyAccount) {
        Write-Step 'Verifying the sign-in through the web app'
        Test-DemoLogin -Email $verifyAccount -DemoPassword $Password
    } else {
        Write-Step 'Sign-in verification'
        Write-Warn 'Skipped: every demo account already existed, so this run set no password'
        Write-Warn 'it could test with. Their existing passwords are unchanged and still work.'
        Write-Warn 'The API, workers and web app were all verified above.'
    }

    # --- done --------------------------------------------------------------
    $rule = ('=' * 68)
    Write-Host ''
    Write-Host $rule -ForegroundColor Green
    Write-Host '  Sangam is ready' -ForegroundColor Green
    Write-Host $rule -ForegroundColor Green
    Write-Host ''
    Write-Host "  Open        $WebUrl"
    Write-Host "  API docs    $ApiUrl/v1/docs"
    Write-Host ''
    Write-Host '  START HERE - the Sangam workspace:' -ForegroundColor Cyan
    Write-Host '    abhishek@sangam.co.in   sees everything (owner)'
    Write-Host '    priya@sangam.co.in      sees her team''s prospects (manager)'
    Write-Host '    kiran@sangam.co.in      sees only his own (salesperson)'
    Write-Host ''
    # Say who the printed password is actually for.
    #
    # It used to be printed as a single fact under every account on the screen,
    # which was true on a first run and wrong on every one after it: the Sangam
    # accounts keep their own passwords by design, so somebody reading this was
    # told a credential for accounts it had never been set on.
    if ($passwordAppliesTo.Count -gt 0) {
        Write-Host "  Password    $Password" -ForegroundColor Yellow
        Write-Host "              applies to the $($passwordAppliesTo.Count) account(s) created on this run:"
        foreach ($account in $passwordAppliesTo) { Write-Host "                $account" }
        if ($generated) {
            Write-Host '              generated for this run and stored nowhere;'
            Write-Host '              pass -Password to choose your own'
        }
    } else {
        Write-Host '  Password    unchanged - every account above already existed' -ForegroundColor Yellow
        Write-Host '              and kept the password it already had.'
        Write-Host '              To set a known one for the Sangam demo accounts:'
        Write-Host '                docker compose exec -e DEMO_PASSWORD=your-passphrase api \'
        Write-Host '                  python src/scripts/seed_sangam.py --reset-passwords'
    }
    Write-Host ''
    Write-Host '  Also available, for the tenant-isolation check:' -ForegroundColor Cyan
    Write-Host '    asha@acme.test     tenant acme    (a few sample leads)'
    Write-Host '    ravi@globex.test   tenant globex  (empty, which is the point)'
    Write-Host "    both use: $Password" -ForegroundColor Yellow
    Write-Host ''
    Write-Host '  Sign in as abhishek@sangam.co.in and start on Today. The guide is'
    Write-Host '  in docs\OWNER-TEST-GUIDE.md and takes about ten minutes.'
    Write-Host ''
    Write-Host '  Stop        docker compose down'
    Write-Host '  Logs        docker compose logs -f api web'
    Write-Host $rule -ForegroundColor Green
    Write-Host ''

    # Last, so the credentials are already on screen when the browser appears.
    if (-not $NoBrowser) { Open-Sangam -Url $WebUrl }
}
catch {
    Write-Host ''
    Write-Err $_.Exception.Message
    # The container hints only help once there is a daemon to ask. Printing
    # "docker compose logs" at somebody who has just been told Docker is not
    # installed is how a clear message becomes a confusing one.
    if (Test-DockerEngine) {
        Write-Host ''
        Write-Warn 'Troubleshooting:'
        Write-Warn '  docker compose logs api web      show what failed'
        Write-Warn '  RESET_DEMO.cmd                   start from an empty database (destructive)'
    }
    Write-Host ''
    exit 1
}
finally {
    Pop-Location
}
