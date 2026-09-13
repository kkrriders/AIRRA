<#
.SYNOPSIS
  Runs benchmark-run.ps1 N times against the airra-lab kind cluster, resets
  state between runs, and aggregates per-stage timing into a Stage/Time table.
#>
[CmdletBinding()]
param(
    [int]$Runs = 12,
    # Must clear app.services.prometheus_client.py's default lookback_minutes=5 --
    # a shorter gap leaves the previous run's spike inside the detector's own
    # baseline window and silently kills detection on the next run (confirmed
    # live: a 4-5 min gap was NOT enough, see benchmark-run.ps1's commit message).
    [int]$QuietSec = 330,
    [string]$OutDir = "$PSScriptRoot\results"
)

function Get-Stats([double[]]$values) {
    # Manual implementation: Windows PowerShell 5.1's Measure-Object has no -StandardDeviation.
    $clean = $values | Where-Object { $null -ne $_ }
    if ($clean.Count -eq 0) { return [ordered]@{ n = 0; mean = $null; median = $null; min = $null; max = $null; stdev = $null } }
    $n = $clean.Count
    $mean = ($clean | Measure-Object -Average).Average
    $sorted = $clean | Sort-Object
    $median = if ($n % 2 -eq 1) { $sorted[[int](($n - 1) / 2)] } else { (($sorted[$n / 2 - 1] + $sorted[$n / 2]) / 2) }
    $variance = if ($n -gt 1) { (($clean | ForEach-Object { [math]::Pow($_ - $mean, 2) } | Measure-Object -Sum).Sum) / ($n - 1) } else { 0 }
    [ordered]@{
        n = $n; mean = [math]::Round($mean, 1); median = [math]::Round($median, 1)
        min = [math]::Round(($clean | Measure-Object -Minimum).Minimum, 1)
        max = [math]::Round(($clean | Measure-Object -Maximum).Maximum, 1)
        stdev = [math]::Round([math]::Sqrt($variance), 1)
    }
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$runRecords = @()

for ($i = 1; $i -le $Runs; $i++) {
    Write-Host "`n=== Run $i / $Runs ===" -ForegroundColor Cyan
    $runFile = Join-Path $OutDir "run-$i.json"
    & "$PSScriptRoot\benchmark-run.ps1" -OutFile $runFile | Out-Null
    $record = Get-Content $runFile -Raw | ConvertFrom-Json
    $runRecords += $record
    Write-Host "  success=$($record.success) failure_stage=$($record.failure_stage) detected=$($record.deltas_seconds.incident_detected)s executed=$($record.deltas_seconds.remediation_executed)s"

    if ($i -lt $Runs) {
        Write-Host "  cooling down ${QuietSec}s before next run (clears the detector's 5-min baseline window)..."
        Start-Sleep -Seconds $QuietSec
    }
}

$successful = $runRecords | Where-Object success
$successRate = if ($runRecords.Count -gt 0) { [math]::Round($successful.Count / $runRecords.Count, 2) } else { 0 }

$stageKeys = @('first_telemetry', 'incident_detected', 'diagnosis_complete', 'approved', 'remediation_executed', 'recovery_verified')
$stats = [ordered]@{}
foreach ($key in $stageKeys) {
    $values = $successful | ForEach-Object { $_.deltas_seconds.$key } | Where-Object { $null -ne $_ }
    $stats[$key] = Get-Stats -values $values
}

$stamp = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$summary = [ordered]@{
    run_at = (Get-Date).ToUniversalTime().ToString('o')
    total_runs = $runRecords.Count
    successful_runs = $successful.Count
    success_rate = $successRate
    execution_mode_observed = ($runRecords | Where-Object { $_.execution_mode } | Select-Object -First 1 -ExpandProperty execution_mode)
    stage_stats_seconds = $stats
    failure_stages = ($runRecords | Where-Object { -not $_.success } | Group-Object failure_stage | ForEach-Object { @{ stage = $_.Name; count = $_.Count } })
}
$jsonPath = Join-Path $OutDir "$stamp-summary.json"
@{ summary = $summary; runs = $runRecords } | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 $jsonPath

$mdPath = Join-Path $OutDir "$stamp-summary.md"
@"
# AIRRA MTTD/MTTR-by-stage benchmark - $stamp

Kind lab (``airra-lab``), ``crashloop`` fault on ``payment-service``, $($runRecords.Count) runs, $($successful.Count) successful ($($successRate * 100)%).
Execution mode observed: **$($summary.execution_mode_observed)**.

| Stage | Mean T+ | Median T+ | Min | Max | Stdev | n |
|---|---|---|---|---|---|---|
$(($stageKeys | ForEach-Object { $s = $stats[$_]; "| $_ | $($s.mean)s | $($s.median)s | $($s.min)s | $($s.max)s | $($s.stdev)s | $($s.n) |" }) -join "`n")

## Per-run detail

| Run | Success | Failure stage | Detected | Diagnosed | Approved | Executed | Verified |
|---|---|---|---|---|---|---|---|
$(($runRecords | ForEach-Object { "| $($_.run_id) | $($_.success) | $($_.failure_stage) | $($_.deltas_seconds.incident_detected) | $($_.deltas_seconds.diagnosis_complete) | $($_.deltas_seconds.approved) | $($_.deltas_seconds.remediation_executed) | $($_.deltas_seconds.recovery_verified) |" }) -join "`n")
"@ | Set-Content -Encoding utf8 $mdPath

Write-Host "`nWrote $jsonPath"
Write-Host "Wrote $mdPath"
