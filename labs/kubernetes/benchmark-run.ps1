<#
.SYNOPSIS
  One fault-injection cycle against the airra-lab kind cluster, timestamped
  at every pipeline stage: inject -> first telemetry change -> AIRRA
  incident -> diagnosis -> approval -> remediation -> recovery verified.
#>
[CmdletBinding()]
param(
    [string]$AirraUrl = 'http://localhost:8000',
    [string]$AirraApiKey = $env:AIRRA_API_KEY,
    [string]$AirraEnvFile = "$HOME\AIRRA\.env",
    [string]$PrometheusUrl = 'http://localhost:9091',
    [string]$Namespace = 'airra-lab',
    [string]$TargetService = 'payment-service',
    [string]$OutFile = $null
)

$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\Get-FirstTelemetryChange.ps1"

function Get-EnvValue([string]$file, [string]$key) {
    if (-not (Test-Path $file)) { return $null }
    $m = Select-String -Path $file -Pattern "^$key=(.+)$"
    if ($m) { return $m[0].Matches.Groups[1].Value.Trim() }
    return $null
}
if (-not $AirraApiKey) { $AirraApiKey = Get-EnvValue $AirraEnvFile 'AIRRA_API_KEY' }
if (-not $AirraApiKey) { throw "AIRRA_API_KEY not found. Pass -AirraApiKey or check -AirraEnvFile." }

function Invoke-AirraApi([string]$Method, [string]$Path, [object]$Body = $null) {
    $headers = @{ 'X-API-Key' = $AirraApiKey }
    if ($Body) {
        return Invoke-RestMethod "$AirraUrl$Path" -Method $Method -Headers $headers `
            -ContentType 'application/json' -Body ($Body | ConvertTo-Json)
    }
    return Invoke-RestMethod "$AirraUrl$Path" -Method $Method -Headers $headers
}
function Iso($dt) { if ($null -eq $dt) { return $null }; return $dt.ToUniversalTime().ToString('o') }
function DeltaSec($from, $to) { if ($null -eq $to) { return $null }; return [math]::Round(($to - $from).TotalSeconds, 1) }

$runId = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$stages = [ordered]@{
    fault_injected_at = $null; first_telemetry_at = $null; incident_detected_at = $null
    diagnosis_complete_at = $null; approved_at = $null; remediation_executed_at = $null
    recovery_verified_at = $null
}
$success = $false
$failureStage = $null
$executionMode = $null
$incidentId = $null

try {
    # --- Baseline (for the telemetry-change detector) ---
    $baselineQuery = "sum(kube_pod_container_status_restarts_total{namespace=`"$Namespace`",pod=~`"$TargetService-.*`"})"
    $baselineResp = Invoke-RestMethod "$PrometheusUrl/api/v1/query?query=$([uri]::EscapeDataString($baselineQuery))"
    $baseline = if ($baselineResp.data.result) { [double]$baselineResp.data.result[0].value[1] } else { 0 }

    # --- Stage 1: inject ---
    $t0 = Get-Date
    $stages.fault_injected_at = Iso $t0
    & "$PSScriptRoot\chaos.ps1" crashloop | Out-Host

    # --- Stage 2: first telemetry change ---
    $telemetryAt = Get-FirstTelemetryChange -PrometheusUrl $PrometheusUrl -Query $baselineQuery `
        -BaselineValue $baseline -StartTime $t0 -TimeoutSec 90
    if (-not $telemetryAt) { $failureStage = 'first_telemetry'; throw "No telemetry change observed within 90s." }
    $stages.first_telemetry_at = Iso $telemetryAt

    # --- Stage 3: AIRRA incident created ---
    # Filter on affected_service + recency + a pod_restart_count evidence key so an
    # unrelated request_rate/latency false-positive on the same service (this lab's
    # load-generator produces some ambient noise, see labs/kubernetes/RESULTS.md)
    # can't be mistaken for the incident this run actually caused.
    $incident = $null
    for ($i = 0; $i -lt 24; $i++) {
        Start-Sleep -Seconds 5
        $list = Invoke-AirraApi -Method Get -Path "/api/v1/incidents?page=1"
        $items = if ($list.items) { $list.items } elseif ($list.data) { $list.data } else { $list }
        $found = $items | Where-Object {
            $_.affected_service -eq $TargetService -and
            ([DateTime]::Parse($_.detected_at).ToUniversalTime()) -gt $t0.ToUniversalTime() -and
            $_.metrics_snapshot.PSObject.Properties.Name -contains 'pod_restart_count'
        } | Select-Object -First 1
        if ($found) { $incident = $found; break }
    }
    if (-not $incident) { $failureStage = 'incident_detected'; throw "AIRRA did not create a pod_restart_count incident within 2 minutes." }
    $incidentId = $incident.id
    $stages.incident_detected_at = Iso ([DateTime]::Parse($incident.detected_at).ToUniversalTime())

    # --- Stage 4: diagnosis complete (pending_approval) ---
    # Analysis auto-triggers on detection in this environment (anomaly_monitor's
    # _create_incident_row auto-enqueues analyze_incident) -- by the time we poll
    # here the incident may already be past DETECTED, and POST /analyze 400s on
    # any status other than DETECTED. Only call it if still needed.
    if ($incident.status -eq 'detected') {
        try { $null = Invoke-AirraApi -Method Post -Path "/api/v1/incidents/$($incident.id)/analyze" }
        catch { Write-Warning "  /analyze returned an error (likely already auto-triggered): $($_.Exception.Message)" }
    }
    $analyzed = $null
    for ($i = 0; $i -lt 24; $i++) {
        Start-Sleep -Seconds 5
        $cur = Invoke-AirraApi -Method Get -Path "/api/v1/incidents/$($incident.id)"
        if ($cur.status -eq 'pending_approval') { $analyzed = $cur; break }
    }
    if (-not $analyzed) { $failureStage = 'diagnosis_complete'; throw "Analysis did not reach pending_approval within 2 minutes." }
    $stages.diagnosis_complete_at = Iso (Get-Date)

    if (-not $analyzed.actions -or $analyzed.actions.Count -eq 0) {
        $failureStage = 'approved'; throw "No remediation action generated -- cannot continue to approval/execution."
    }
    $actionId = $analyzed.actions[0].id

    # --- Stage 5: approved ---
    $null = Invoke-AirraApi -Method Post -Path "/api/v1/approvals/$actionId/approve" -Body @{ approved_by = 'benchmark-harness' }
    $stages.approved_at = Iso (Get-Date)

    # --- Stage 6: remediation executed ---
    $executed = Invoke-AirraApi -Method Post -Path "/api/v1/actions/$actionId/execute"
    $stages.remediation_executed_at = Iso (Get-Date)
    $executionMode = $executed.execution_mode

    # --- Stage 7: recovery verified (wait out verify_action_task's stabilization window, then confirm still RESOLVED) ---
    Start-Sleep -Seconds 35   # settings.verification_stabilization_seconds default (30s) + buffer
    $final = Invoke-AirraApi -Method Get -Path "/api/v1/incidents/$($incident.id)"
    if ($final.status -ne 'resolved') {
        $failureStage = 'recovery_verified'
        throw "Incident did not stay resolved after verification window (status: $($final.status))."
    }
    $stages.recovery_verified_at = Iso (Get-Date)
    $success = $true
}
catch {
    # Record the failure instead of letting it escape -- a caller looping this
    # script (benchmark-repeat.ps1) needs one run's failure to produce a
    # success:false record, not crash the whole loop.
    if (-not $failureStage) { $failureStage = 'unknown' }
    Write-Warning "Run failed at stage '$failureStage': $($_.Exception.Message)"
}
finally {
    # chaos.ps1 recover removes the CRASH_LOOP env var, which itself triggers a
    # rolling update to fresh pods -- an explicit `kubectl delete pod` here is
    # redundant and, worse, adds an extra artificial restart-count discontinuity
    # into Prometheus's history right when the detector's 5-min lookback window
    # (prometheus_client.py's default lookback_minutes=5) is trying to settle.
    & "$PSScriptRoot\chaos.ps1" recover | Out-Host
    try { docker exec airra-redis redis-cli DEL "airra:anomaly_dedup:$TargetService" | Out-Null } catch {}
}

if (-not $stages.fault_injected_at) {
    # Failed before injection even happened (e.g. Prometheus unreachable for the
    # baseline query) -- nothing to compute deltas from, still emit a record.
    if (-not $failureStage) { $failureStage = 'fault_injected' }
    $record = [ordered]@{
        run_id = $runId; success = $false; failure_stage = $failureStage
        incident_id = $incidentId; execution_mode = $executionMode; stages = $stages; deltas_seconds = $null
    }
    if ($OutFile) {
        New-Item -ItemType Directory -Force -Path (Split-Path $OutFile) | Out-Null
        $record | ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8 $OutFile
    }
    $record | ConvertTo-Json -Depth 6
    return
}

$t0Parsed = [DateTime]::Parse($stages.fault_injected_at)
$deltas = [ordered]@{
    first_telemetry     = DeltaSec $t0Parsed ($(if ($stages.first_telemetry_at) { [DateTime]::Parse($stages.first_telemetry_at) }))
    incident_detected   = DeltaSec $t0Parsed ($(if ($stages.incident_detected_at) { [DateTime]::Parse($stages.incident_detected_at) }))
    diagnosis_complete  = DeltaSec $t0Parsed ($(if ($stages.diagnosis_complete_at) { [DateTime]::Parse($stages.diagnosis_complete_at) }))
    approved            = DeltaSec $t0Parsed ($(if ($stages.approved_at) { [DateTime]::Parse($stages.approved_at) }))
    remediation_executed = DeltaSec $t0Parsed ($(if ($stages.remediation_executed_at) { [DateTime]::Parse($stages.remediation_executed_at) }))
    recovery_verified   = DeltaSec $t0Parsed ($(if ($stages.recovery_verified_at) { [DateTime]::Parse($stages.recovery_verified_at) }))
}

$record = [ordered]@{
    run_id = $runId; success = $success; failure_stage = $failureStage
    incident_id = $incidentId; execution_mode = $executionMode; stages = $stages; deltas_seconds = $deltas
}

if ($OutFile) {
    New-Item -ItemType Directory -Force -Path (Split-Path $OutFile) | Out-Null
    $record | ConvertTo-Json -Depth 6 | Set-Content -Encoding utf8 $OutFile
}
$record | ConvertTo-Json -Depth 6
