<#
.SYNOPSIS
  Failure injection for the AIRRA <-> AI Engineering Platform integration (Phase A3).

.DESCRIPTION
  Injects a fault into the running AI platform stack so AIRRA's anomaly monitor
  (60s Celery-beat cycle, 'kubernetes' metric profile, namespace ai-platform)
  detects it and opens an incident.

  Scenarios:
    api-traffic-surge  HTTP flood on the platform's /health -> 'api' request_rate
                       spikes ~1000x baseline. Works with zero extra setup and is
                       the reliable detect -> approve -> resolve path.
    node-crash         Sets CHAOS_FAIL_NODE on the platform backend so one
                       LangGraph node raises on every run (status=500 -> 'error_rate'
                       on that node). Needs run traffic (labs/integration/run-traffic.ps1,
                       NOT traffic.ps1 - that one only pings /health and never
                       executes the graph). 'orchestrator' is the entrypoint and
                       fails before any Groq call; nodes after it still need a
                       working GROQ_API_KEY to be reached at all.
    qdrant-down        Stops the platform's qdrant container -> 'researcher'
                       service_dependency_failures_total{dependency="qdrant"}.
    llm-failure        Starts the mock-llm container, points the platform's
                       Groq base URL at it, and flips it to 500s (or 429s with
                       -Kind rate_limit) -> llm_gateway_errors_total across
                       every node that calls the LLM on the next run. Needs
                       run traffic (labs/integration/run-traffic.ps1).

  Actions: inject (default) | clear | status

.EXAMPLE
  ./chaos.ps1 -Scenario api-traffic-surge
  ./chaos.ps1 -Scenario node-crash -Node orchestrator
  ./chaos.ps1 -Scenario node-crash -Action clear
  ./chaos.ps1 -Scenario qdrant-down -Action status
  ./chaos.ps1 -Scenario llm-failure -Kind rate_limit
  ./chaos.ps1 -Scenario llm-failure -Action clear
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('api-traffic-surge', 'node-crash', 'qdrant-down', 'llm-failure')]
    [string]$Scenario,

    [ValidateSet('inject', 'clear', 'status')]
    [string]$Action = 'inject',

    # node-crash only
    [ValidateSet('orchestrator', 'researcher', 'tool_runner', 'executor', 'verifier')]
    [string]$Node = 'orchestrator',

    # api-traffic-surge only
    [int]$DurationSec = 90,
    [int]$Rps = 40,

    # llm-failure only
    [ValidateSet('5xx', 'rate_limit')]
    [string]$Kind = '5xx',

    [string]$PlatformCompose = "$HOME\Multi Agent Intelligence Platform\docker-compose.yml",
    [string]$PlatformUrl = 'http://localhost:8010',
    [string]$PrometheusUrl = 'http://localhost:9090',
    [string]$AirraUrl = 'http://localhost:8000',
    [string]$AirraApiKey = $env:AIRRA_API_KEY,
    [string]$MockLlmUrl = 'http://localhost:4001'
)

$ErrorActionPreference = 'Stop'

function Assert-PlatformUp {
    try { $null = Invoke-RestMethod "$PlatformUrl/health" -TimeoutSec 5 }
    catch { throw "Platform not reachable at $PlatformUrl/health. Bring the stack up first." }
}

function Get-ApiRequestRate {
    $q = 'sum(rate(http_requests_total{service="api",namespace="ai-platform"}[1m]))'
    try {
        $r = Invoke-RestMethod "$PrometheusUrl/api/v1/query?query=$([uri]::EscapeDataString($q))" -TimeoutSec 5
        if ($r.data.result.Count -gt 0) { return [double]$r.data.result[0].value[1] }
    } catch {}
    return $null
}

function Invoke-ApiTrafficSurge {
    Assert-PlatformUp
    $before = Get-ApiRequestRate
    $beforeTxt = if ($null -eq $before) { 'no data' } else { "$([math]::Round($before, 4)) req/s" }
    Write-Host "api request_rate before: $beforeTxt"
    Write-Host "Flooding $PlatformUrl/health at ~$Rps rps for ${DurationSec}s ..."
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $sent = 0; $errs = 0
    $delayMs = [math]::Max(1, [int](1000 / [math]::Max(1, $Rps)))
    while ($sw.Elapsed.TotalSeconds -lt $DurationSec) {
        try { $null = Invoke-WebRequest "$PlatformUrl/health" -TimeoutSec 3 -UseBasicParsing; $sent++ }
        catch { $errs++ }
        Start-Sleep -Milliseconds $delayMs
    }
    $sw.Stop()
    Write-Host "Sent $sent requests ($errs failed) in $([math]::Round($sw.Elapsed.TotalSeconds,1))s."
    $after = Get-ApiRequestRate
    if ($null -ne $after) { Write-Host "api request_rate after: $([math]::Round($after,4)) req/s" }
    Write-Host "AIRRA's anomaly monitor runs every 60s - watch for an incident on 'api':"
    Write-Host "  ./chaos.ps1 -Scenario api-traffic-surge -Action status   # or:"
    Write-Host "  curl -s -H `"X-API-Key: `$env:AIRRA_API_KEY`" $AirraUrl/api/v1/incidents?page=1"
}

function Get-RecentIncidents {
    if (-not $AirraApiKey) { Write-Host "(set `$env:AIRRA_API_KEY to list incidents)"; return }
    try {
        $r = Invoke-RestMethod "$AirraUrl/api/v1/incidents?page=1" -Headers @{ 'X-API-Key' = $AirraApiKey } -TimeoutSec 5
        $items = if ($r.data) { $r.data } elseif ($r.items) { $r.items } else { $r }
        $items | Select-Object -First 6 | ForEach-Object {
            Write-Host ("  {0}  {1,-16} {2,-14} {3}" -f $_.id.Substring(0,8), $_.status, $_.affected_service, $_.title)
        }
    } catch { Write-Host "  (incident list failed: $($_.Exception.Message))" }
}

function Wait-PlatformHealthy {
    # container Recreated != app ready - callers that immediately drive traffic
    # (run-traffic.ps1) would otherwise race a backend still starting up.
    for ($i = 0; $i -lt 15; $i++) {
        try { $null = Invoke-RestMethod "$PlatformUrl/health" -TimeoutSec 2; return } catch { Start-Sleep -Milliseconds 500 }
    }
    throw "platform backend didn't come back healthy at $PlatformUrl/health after recreate"
}

function Invoke-DockerCompose([string[]]$ComposeArgs) {
    # ponytail: docker compose's normal stderr status lines ("Container X
    # Running") get promoted to a terminating NativeCommandError under this
    # script's $ErrorActionPreference = 'Stop' (PowerShell 5.1 quirk, not an
    # actual docker failure) -- relax it just for this call and rely on
    # $LASTEXITCODE (checked by every caller) instead.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & docker compose -f $PlatformCompose @ComposeArgs 2>&1 | Out-Host }
    finally { $ErrorActionPreference = $prev }
}

function Set-ChaosFailNode([string]$value) {
    # compose interpolates ${CHAOS_FAIL_NODE:-} at parse time from this process's env
    if ([string]::IsNullOrEmpty($value)) { $env:CHAOS_FAIL_NODE = '' }
    else { $env:CHAOS_FAIL_NODE = $value }
    Invoke-DockerCompose @('up', '-d', 'backend')
    if ($LASTEXITCODE -ne 0) { throw "docker compose up -d backend failed" }
    Wait-PlatformHealthy
}

function Get-ComposeContainer([string]$svc) {
    $id = (& docker compose -f $PlatformCompose ps -q $svc).Trim()
    if (-not $id) { throw "compose service '$svc' has no container (stack down?)" }
    return $id
}

function Set-GroqBaseUrl([string]$value) {
    # compose interpolates ${GROQ_BASE_URL:-} at parse time from this process's env
    if ([string]::IsNullOrEmpty($value)) { $env:GROQ_BASE_URL = '' }
    else { $env:GROQ_BASE_URL = $value }
    Invoke-DockerCompose @('up', '-d', 'backend')
    if ($LASTEXITCODE -ne 0) { throw "docker compose up -d backend failed" }
    Wait-PlatformHealthy
}

switch ("$Scenario/$Action") {

    'api-traffic-surge/inject' { Invoke-ApiTrafficSurge }
    'api-traffic-surge/clear'  { Write-Host "Nothing to clear - the surge is transient. Incident (if any) stays until you resolve it in AIRRA." }
    'api-traffic-surge/status' {
        $rate = Get-ApiRequestRate
        if ($null -eq $rate) { Write-Host "api request_rate: no data (is the ai-platform scrape target up?)" }
        else { Write-Host "api request_rate now: $([math]::Round($rate,4)) req/s  (baseline is ~0.05-0.1)" }
        Write-Host "recent AIRRA incidents:"
        Get-RecentIncidents
    }

    'node-crash/inject' {
        Set-ChaosFailNode $Node
        Write-Host "CHAOS_FAIL_NODE=$Node - every run now 500s at '$Node'."
        Write-Host "Drive traffic so the node executes:  ./run-traffic.ps1"
        Write-Host "Clear with:  ./chaos.ps1 -Scenario node-crash -Action clear"
    }
    'node-crash/clear' {
        Set-ChaosFailNode ''
        Write-Host "CHAOS_FAIL_NODE cleared - platform backend recreated clean."
    }
    'node-crash/status' {
        $c = Get-ComposeContainer 'backend'
        $v = (& docker exec $c printenv CHAOS_FAIL_NODE) 2>$null
        if ([string]::IsNullOrWhiteSpace($v)) { Write-Host "CHAOS_FAIL_NODE: (not set) - platform healthy" }
        else { Write-Host "CHAOS_FAIL_NODE: $v - node '$v' is being forced to fail" }
    }

    'qdrant-down/inject' {
        $c = Get-ComposeContainer 'qdrant'
        & docker stop $c | Out-Host
        Write-Host "qdrant stopped. 'researcher' dependency failures will climb on the next run."
    }
    'qdrant-down/clear' {
        $c = Get-ComposeContainer 'qdrant'
        & docker start $c | Out-Host
        Write-Host "qdrant started."
    }
    'qdrant-down/status' {
        $running = (& docker compose -f $PlatformCompose ps --status running --services) -split "`n"
        if ($running -contains 'qdrant') { Write-Host "qdrant: running" } else { Write-Host "qdrant: STOPPED" }
    }

    'llm-failure/inject' {
        Invoke-DockerCompose @('--profile', 'chaos', 'up', '-d', '--build', 'mock-llm')
        if ($LASTEXITCODE -ne 0) { throw "docker compose up -d mock-llm failed" }
        # container start != uvicorn ready - poll /health rather than racing the first request
        $up = $false
        for ($i = 0; $i -lt 15; $i++) {
            try { $null = Invoke-RestMethod "$MockLlmUrl/health" -TimeoutSec 2; $up = $true; break } catch { Start-Sleep -Milliseconds 500 }
        }
        if (-not $up) { throw "mock-llm didn't come up at $MockLlmUrl/health" }
        $body = @{ mode = 'error'; kind = $Kind } | ConvertTo-Json
        $null = Invoke-RestMethod "$MockLlmUrl/mode" -Method Post -ContentType 'application/json' -Body $body
        Set-GroqBaseUrl 'http://mock-llm:4000'
        Write-Host "mock-llm mode=error kind=$Kind, platform GROQ_BASE_URL -> mock-llm."
        Write-Host "Drive traffic so a node calls the LLM:  ./run-traffic.ps1"
        Write-Host "Clear with:  ./chaos.ps1 -Scenario llm-failure -Action clear"
    }
    'llm-failure/clear' {
        Set-GroqBaseUrl ''
        try { $null = Invoke-RestMethod "$MockLlmUrl/mode" -Method Post -ContentType 'application/json' -Body '{"mode":"healthy"}' } catch {}
        Write-Host "GROQ_BASE_URL cleared - platform backend recreated clean, back on real Groq."
    }
    'llm-failure/status' {
        try {
            $m = Invoke-RestMethod "$MockLlmUrl/mode" -TimeoutSec 5
            Write-Host "mock-llm: mode=$($m.mode) kind=$($m.kind)"
        } catch { Write-Host "mock-llm: not reachable at $MockLlmUrl (not started, or -Action clear already ran)" }
        $c = Get-ComposeContainer 'backend'
        $v = (& docker exec $c printenv GROQ_BASE_URL) 2>$null
        if ([string]::IsNullOrWhiteSpace($v)) { Write-Host "platform GROQ_BASE_URL: (not set) - using real Groq" }
        else { Write-Host "platform GROQ_BASE_URL: $v" }
    }

    default { throw "unhandled: $Scenario/$Action" }
}
