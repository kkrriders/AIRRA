<#
.SYNOPSIS
  Resume-metrics benchmark: 5 real tasks against the AI platform, one injected
  node failure mid-run, full AIRRA detect -> analyze -> approve -> execute
  loop, all metrics from both sides written to labs/integration/results/.

.DESCRIPTION
  1. Sends 5 distinct real task prompts to the platform (POST /runs), timing
     each one.
  2. After task 2, injects a node-crash on 'researcher' (chaos.ps1) so tasks
     3-5 run against a live failure, then clears it.
  3. Polls AIRRA for the resulting incident, runs it through analyze ->
     approve -> execute (the same API calls labs/integration/README.md's
     manual demo uses, scripted so it doesn't wait on the 30-min Beat timer),
     and records timestamps at each stage.
  4. Writes a JSON results file + a markdown summary under ./results/.

.EXAMPLE
  ./benchmark-run.ps1
#>
[CmdletBinding()]
param(
    [string]$PlatformUrl = 'http://localhost:8010',
    [string]$PlatformEnvFile = "$HOME\Multi Agent Intelligence Platform\backend\.env",
    [string]$AirraUrl = 'http://localhost:8000',
    [string]$AirraApiKey = $env:AIRRA_API_KEY,
    [string]$AirraEnvFile = "$HOME\AIRRA\.env",
    [string]$SupabaseUrl,
    [string]$SupabaseAnonKey,
    [string]$Email = 'anshuman.aroraak+airra-traffic@gmail.com',
    [string]$Password = 'hunter2-hunter2',
    [string]$ProjectName = 'airra-benchmark',
    # orchestrator is the unconditional graph entrypoint (every run hits it
    # first, regardless of the LLM's routing decisions) -- researcher/executor/
    # verifier are only visited when the orchestrator's own LLM call decides
    # a query needs them, so well-formed Q&A prompts can silently bypass a
    # crashed researcher/executor while generic filler text (run-traffic.ps1)
    # cannot. orchestrator has no such ambiguity.
    [string]$FailNode = 'orchestrator',
    [string]$OutDir = "$HOME\AIRRA\labs\integration\results"
)

$ErrorActionPreference = 'Stop'

function Get-EnvValue([string]$file, [string]$key) {
    if (-not (Test-Path $file)) { return $null }
    $m = Select-String -Path $file -Pattern "^$key=(.+)$"
    if ($m) { return $m[0].Matches.Groups[1].Value.Trim() }
    return $null
}

if (-not $AirraApiKey) { $AirraApiKey = Get-EnvValue $AirraEnvFile 'AIRRA_API_KEY' }
if (-not $AirraApiKey) { throw "AIRRA_API_KEY not found. Pass -AirraApiKey or check -AirraEnvFile ($AirraEnvFile)." }

if (-not $SupabaseUrl) { $SupabaseUrl = Get-EnvValue $PlatformEnvFile 'SUPABASE_URL' }
if (-not $SupabaseAnonKey) { $SupabaseAnonKey = Get-EnvValue $PlatformEnvFile 'SUPABASE_ANON_KEY' }
if (-not $SupabaseUrl -or -not $SupabaseAnonKey) {
    throw "SUPABASE_URL / SUPABASE_ANON_KEY not found. Pass -SupabaseUrl/-SupabaseAnonKey or check -PlatformEnvFile ($PlatformEnvFile)."
}

function Invoke-SupabaseSignIn {
    $body = @{ email = $Email; password = $Password } | ConvertTo-Json
    Invoke-RestMethod "$SupabaseUrl/auth/v1/token?grant_type=password" -Method Post `
        -Headers @{ apikey = $SupabaseAnonKey; 'Content-Type' = 'application/json' } -Body $body
}

function Get-SupabaseToken {
    try { return Invoke-SupabaseSignIn }
    catch {
        $body = @{ email = $Email; password = $Password } | ConvertTo-Json
        try {
            Invoke-RestMethod "$SupabaseUrl/auth/v1/signup" -Method Post `
                -Headers @{ apikey = $SupabaseAnonKey; 'Content-Type' = 'application/json' } -Body $body | Out-Null
        } catch {}
        return Invoke-SupabaseSignIn
    }
}

Write-Host "Authenticating as $Email ..."
$session = Get-SupabaseToken
$token = $session.access_token
function Get-AuthHeaders { @{ Authorization = "Bearer $token" } }

Write-Host "Creating project '$ProjectName' ..."
$project = Invoke-RestMethod "$PlatformUrl/projects" -Method Post -Headers (Get-AuthHeaders) `
    -ContentType 'application/json' -Body (@{ name = $ProjectName } | ConvertTo-Json)
$conversation = Invoke-RestMethod "$PlatformUrl/projects/$($project.id)/conversations" -Method Post `
    -Headers (Get-AuthHeaders) -ContentType 'application/json' -Body '{}'
Write-Host "  project: $($project.id)  conversation: $($conversation.id)"

$tasks = @(
    "Summarize the key benefits of vector databases for RAG systems."
    "What are three best practices for prompt engineering in production LLM apps?"
    "Explain the CAP theorem in simple terms."
    "List common causes of LLM hallucination and how to mitigate them."
    "Compare REST and GraphQL API design tradeoffs."
)

function Send-Task([string]$prompt, [int]$index) {
    $start = Get-Date
    $result = [ordered]@{
        index = $index; prompt = $prompt
        started_at = $start.ToUniversalTime().ToString('o')
        success = $false; duration_sec = $null; error = $null
    }
    try {
        # The platform caches responses by input text -- a repeated prompt
        # skips the graph entirely (no node metrics, no crash exposure).
        # Nonce every request so each one genuinely executes, same as
        # run-traffic.ps1 already does.
        $uniqueInput = "$prompt [run $(Get-Date -Format 'o') #$index]"
        $null = Invoke-RestMethod "$PlatformUrl/conversations/$($conversation.id)/runs" -Method Post `
            -Headers (Get-AuthHeaders) -ContentType 'application/json' -TimeoutSec 90 `
            -Body (@{ input = $uniqueInput } | ConvertTo-Json)
        $result.success = $true
    } catch {
        $result.error = $_.Exception.Message
    }
    $result.duration_sec = [math]::Round(((Get-Date) - $start).TotalSeconds, 1)
    Write-Host "  task $index : success=$($result.success) ($($result.duration_sec)s) $prompt"
    return $result
}

$taskResults = @()
Write-Host "`n--- Tasks 1-2 (baseline, before failure) ---"
$taskResults += Send-Task $tasks[0] 1
$taskResults += Send-Task $tasks[1] 2

Write-Host "`n--- Injecting node-crash on '$FailNode' ---"
$injectedAt = Get-Date
& "$HOME\AIRRA\labs\integration\chaos.ps1" -Scenario node-crash -Node $FailNode | Out-Host

Write-Host "`n--- Tasks 3-5 (during failure, paced) ---"
$taskResults += Send-Task $tasks[2] 3
Start-Sleep -Seconds 12
$taskResults += Send-Task $tasks[3] 4
Start-Sleep -Seconds 12
$taskResults += Send-Task $tasks[4] 5

# chaos.ps1's node-crash recreates the platform container to set
# CHAOS_FAIL_NODE, which resets its Prometheus histogram counters. Since the
# crashed node fails instantly, EVERY post-recreate sample is a crash-state
# reading -- there is no in-container healthy baseline left to diff against.
# Worse, AIRRA's latency_p95 query is histogram_quantile(rate(...[1m])): once
# 60s pass with no new request, that rate window empties and the metric goes
# NaN, leaving at most one valid data point -- not enough to compute a
# baseline at all. A quick task burst then silence reproduces this exactly.
# Fix: keep sending light nonced keepalive traffic through the whole
# detection wait so the rate window stays populated continuously, same as
# every proven scenario in this harness (which all use a paced traffic loop,
# never a one-shot burst).
function Send-Keepalive {
    try {
        $null = Invoke-RestMethod "$PlatformUrl/conversations/$($conversation.id)/runs" -Method Post `
            -Headers (Get-AuthHeaders) -ContentType 'application/json' -TimeoutSec 20 `
            -Body (@{ input = "benchmark keepalive [$(Get-Date -Format 'o')]" } | ConvertTo-Json)
    } catch {}
}

function Get-AirraIncidents {
    $r = Invoke-RestMethod "$AirraUrl/api/v1/incidents?page=1" -Headers @{ 'X-API-Key' = $AirraApiKey }
    if ($r.items) { return $r.items } elseif ($r.data) { return $r.data } else { return $r }
}
function Clear-Fault {
    Write-Host "`n--- Clearing failure ---"
    & "$HOME\AIRRA\labs\integration\chaos.ps1" -Scenario node-crash -Action clear | Out-Host
}

Write-Host "`n--- Waiting for AIRRA to detect the '$FailNode' incident (keepalive traffic + up to 2 min) ---"
$incident = $null
try {
    for ($i = 0; $i -lt 24; $i++) {
        Start-Sleep -Seconds 5
        if ($i % 2 -eq 0) { Send-Keepalive }  # every ~10s -- keeps the rate([1m]) window fed
        $found = Get-AirraIncidents | Where-Object {
            $_.affected_service -eq $FailNode -and $_.detected_at -gt $injectedAt.ToUniversalTime().ToString('o')
        } | Select-Object -First 1
        if ($found) { $incident = $found; break }
    }
} finally {
    # Fault stays live only long enough to get detected -- clear it now
    # regardless of outcome so we never leave the platform crashed.
    Clear-Fault
}
if (-not $incident) { throw "AIRRA did not detect a '$FailNode' incident within 2 minutes. Check dedup/baseline state and retry." }

$detectedAt = [DateTime]::Parse($incident.detected_at).ToUniversalTime()
$mttdSec = [math]::Round(($detectedAt - $injectedAt.ToUniversalTime()).TotalSeconds, 1)
Write-Host "  detected: $($incident.id)  MTTD=${mttdSec}s  confidence-context: $($incident.context.max_deviation)"

function Invoke-AirraApi([string]$Method, [string]$Path, [object]$Body = $null) {
    $headers = @{ 'X-API-Key' = $AirraApiKey }
    if ($Body) {
        return Invoke-RestMethod "$AirraUrl$Path" -Method $Method -Headers $headers `
            -ContentType 'application/json' -Body ($Body | ConvertTo-Json)
    }
    return Invoke-RestMethod "$AirraUrl$Path" -Method $Method -Headers $headers
}

Write-Host "`n--- Triggering analysis ---"
$analyzeStart = Get-Date
$null = Invoke-AirraApi -Method Post -Path "/api/v1/incidents/$($incident.id)/analyze"

$analyzed = $null
for ($i = 0; $i -lt 24; $i++) {
    Start-Sleep -Seconds 5
    $cur = Invoke-AirraApi -Method Get -Path "/api/v1/incidents/$($incident.id)"
    if ($cur.status -eq 'pending_approval') { $analyzed = $cur; break }
}
if (-not $analyzed) { throw "Analysis did not reach pending_approval within 2 minutes." }
$analysisDoneAt = Get-Date
$mttaSec = [math]::Round(($analysisDoneAt - $analyzeStart).TotalSeconds, 1)
$hypothesisCount = ($analyzed.hypotheses | Measure-Object).Count
$topConfidence = ($analyzed.hypotheses | Sort-Object confidence_score -Descending | Select-Object -First 1).confidence_score
Write-Host "  analyzed in ${mttaSec}s: $hypothesisCount hypotheses, top confidence=$topConfidence"

# Remediation actions come from AIRRA's k8s-backed action_selector -- the AI
# platform runs in plain Docker Compose in this integration phase (no k8s
# executor for these services yet, that's Phase C), so it's expected that
# analysis can legitimately produce zero actions here. Only approve/execute
# when one actually exists rather than forcing it.
$mttrSec = $null
$finalStatus = $analyzed.status
if ($analyzed.actions -and $analyzed.actions.Count -gt 0) {
    Write-Host "`n--- Approving + executing remediation ---"
    $actionId = $analyzed.actions[0].id
    $null = Invoke-AirraApi -Method Post -Path "/api/v1/approvals/$actionId/approve" -Body @{ approved_by = 'benchmark-harness' }
    $executeAt = Get-Date
    $executed = Invoke-AirraApi -Method Post -Path "/api/v1/actions/$actionId/execute"
    $mttrSec = [math]::Round(($executeAt.ToUniversalTime() - $injectedAt.ToUniversalTime()).TotalSeconds, 1)
    $finalStatus = $executed.status
    Write-Host "  final incident status: $finalStatus  MTTR (inject->execute)=${mttrSec}s"
} else {
    Write-Host "`n--- No remediation action generated (no k8s executor for '$FailNode' in this integration phase) ---"
    Write-Host "  incident stays at: $finalStatus"
}

# --- Assemble report ---
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$stamp = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$report = [ordered]@{
    run_at = (Get-Date).ToUniversalTime().ToString('o')
    fail_node = $FailNode
    tasks = $taskResults
    task_success_rate = [math]::Round((@($taskResults | Where-Object success).Count / $taskResults.Count), 2)
    task_success_during_failure = [math]::Round((@($taskResults[2..4] | Where-Object success).Count / 3), 2)
    airra = [ordered]@{
        incident_id = $incident.id
        injected_at = $injectedAt.ToUniversalTime().ToString('o')
        detected_at = $incident.detected_at
        mttd_seconds = $mttdSec
        analysis_seconds = $mttaSec
        hypothesis_count = $hypothesisCount
        top_confidence = $topConfidence
        final_status = $finalStatus
        mttr_seconds_inject_to_execute = $mttrSec
        remediation_available = [bool]($analyzed.actions -and $analyzed.actions.Count -gt 0)
    }
}
$jsonPath = "$OutDir\$stamp-benchmark.json"
$report | ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8 $jsonPath

$mdPath = "$OutDir\$stamp-benchmark.md"
@"
# AIRRA / AI Platform benchmark - $stamp

**Scenario:** 5 real tasks against the AI Engineering Platform; node-crash injected on ``$FailNode`` after task 2, cleared after task 5.

## Task throughput
| # | Prompt | Success | Duration (s) |
|---|--------|---------|---------------|
$(($taskResults | ForEach-Object { "| $($_.index) | $($_.prompt) | $($_.success) | $($_.duration_sec) |" }) -join "`n")

- Overall success rate: **$($report.task_success_rate * 100)%**
- Success rate during the live failure (tasks 3-5): **$($report.task_success_during_failure * 100)%**

## AIRRA incident response
- Incident: ``$($incident.id)`` on ``$FailNode``
- **MTTD** (inject -> detected): **${mttdSec}s**
- Analysis time (analyze -> pending_approval): **${mttaSec}s**, $hypothesisCount hypotheses, top confidence $topConfidence
$(if ($mttrSec) { "- **MTTR** (inject -> executed): **${mttrSec}s**" } else { "- No remediation action generated -- AIRRA's k8s-backed action_selector has no executor for '$FailNode' in this Docker-Compose integration phase (Phase C adds kind/k8s)." })
- Final status: **$finalStatus**
"@ | Set-Content -Encoding utf8 $mdPath

Write-Host "`nWrote $jsonPath"
Write-Host "Wrote $mdPath"
