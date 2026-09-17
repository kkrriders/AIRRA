<#
.SYNOPSIS
  Runs benchmark-run.ps1 N times against the AI Engineering Platform (via
  airra-mesh), resets state between runs, and aggregates MTTD/analysis/MTTR
  into a Stage/Time table -- the platform-originated-fault counterpart to
  labs/kubernetes/benchmark-repeat.ps1.
#>
[CmdletBinding()]
param(
    [int]$Runs = 6,
    # Same 5-min lookback_minutes baseline requirement as the kind-lab
    # benchmark (app.services.prometheus_client.py) -- a shorter gap leaves
    # the previous run's spike inside the detector's own baseline window and
    # silently kills detection on the next run. Reusing the same proven value.
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
    # benchmark-run.ps1 auto-names its own output files (no -OutFile param) --
    # grab whichever *-benchmark.json lands after invoking it.
    $before = Get-ChildItem $OutDir -Filter '*-benchmark.json' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name
    & "$PSScriptRoot\benchmark-run.ps1" | Out-Host
    $newFile = Get-ChildItem $OutDir -Filter '*-benchmark.json' |
        Where-Object { $before -notcontains $_.Name } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $newFile) { Write-Warning "  run $i produced no output file, skipping"; continue }
    $record = Get-Content $newFile.FullName -Raw | ConvertFrom-Json
    $runRecords += $record
    Write-Host "  success=$($record.success) failure_stage=$($record.failure_stage) mttd=$($record.airra.mttd_seconds)s analysis=$($record.airra.analysis_seconds)s mttr=$($record.airra.mttr_seconds_inject_to_execute)s remediation_available=$($record.airra.remediation_available)"

    if ($i -lt $Runs) {
        Write-Host "  cooling down ${QuietSec}s before next run (clears the detector's 5-min baseline window)..."
        Start-Sleep -Seconds $QuietSec
    }
}

$successful = $runRecords | Where-Object success
$successRate = if ($runRecords.Count -gt 0) { [math]::Round($successful.Count / $runRecords.Count, 2) } else { 0 }
$withRemediation = $successful | Where-Object { $_.airra.remediation_available }
$remediationRate = if ($successful.Count -gt 0) { [math]::Round($withRemediation.Count / $successful.Count, 2) } else { 0 }

$stats = [ordered]@{
    mttd_seconds      = Get-Stats -values ($successful | ForEach-Object { $_.airra.mttd_seconds })
    analysis_seconds  = Get-Stats -values ($successful | ForEach-Object { $_.airra.analysis_seconds })
    mttr_seconds      = Get-Stats -values ($withRemediation | ForEach-Object { $_.airra.mttr_seconds_inject_to_execute })
    top_confidence    = Get-Stats -values ($successful | ForEach-Object { $_.airra.top_confidence })
    task_success_rate = Get-Stats -values ($runRecords | ForEach-Object { $_.task_success_rate })
}

$stamp = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$summary = [ordered]@{
    run_at              = (Get-Date).ToUniversalTime().ToString('o')
    total_runs          = $runRecords.Count
    successful_runs     = $successful.Count
    success_rate        = $successRate
    failure_stages      = ($runRecords | Where-Object { -not $_.success } | Group-Object failure_stage | ForEach-Object { @{ stage = $_.Name; count = $_.Count } })
    remediation_available_runs = $withRemediation.Count
    remediation_available_rate = $remediationRate
    stats               = $stats
}
$jsonPath = Join-Path $OutDir "$stamp-repeat-summary.json"
@{ summary = $summary; runs = $runRecords } | ConvertTo-Json -Depth 8 | Set-Content -Encoding utf8 $jsonPath

$mdPath = Join-Path $OutDir "$stamp-repeat-summary.md"
@"
# AIRRA <-> AI Engineering Platform benchmark (repeated) - $stamp

Platform-originated fault (node-crash on ``orchestrator``) chased through AIRRA's
full detect -> analyze -> approve -> execute pipeline over airra-mesh,
$($runRecords.Count) runs, $($successful.Count) successful ($($successRate * 100)%).
Failure stages: $(if ($summary.failure_stages) { ($summary.failure_stages | ForEach-Object { "$($_.stage) x$($_.count)" }) -join ', ' } else { 'none' }).
Remediation action generated in $($withRemediation.Count)/$($successful.Count)
successful runs ($($remediationRate * 100)%) -- AIRRA's k8s-backed
action_selector doesn't always produce an action for a Docker-Compose-only
service, depending on which hypothesis the LLM ranks top; MTTR is only
meaningful over the runs where one existed. Stage stats below are computed
over successful runs only.

| Metric | Mean | Median | Min | Max | Stdev | n |
|---|---|---|---|---|---|---|
| MTTD (inject -> detected) | $($stats.mttd_seconds.mean)s | $($stats.mttd_seconds.median)s | $($stats.mttd_seconds.min)s | $($stats.mttd_seconds.max)s | $($stats.mttd_seconds.stdev)s | $($stats.mttd_seconds.n) |
| Analysis time | $($stats.analysis_seconds.mean)s | $($stats.analysis_seconds.median)s | $($stats.analysis_seconds.min)s | $($stats.analysis_seconds.max)s | $($stats.analysis_seconds.stdev)s | $($stats.analysis_seconds.n) |
| MTTR (inject -> executed) | $($stats.mttr_seconds.mean)s | $($stats.mttr_seconds.median)s | $($stats.mttr_seconds.min)s | $($stats.mttr_seconds.max)s | $($stats.mttr_seconds.stdev)s | $($stats.mttr_seconds.n) |
| Top hypothesis confidence | $($stats.top_confidence.mean) | $($stats.top_confidence.median) | $($stats.top_confidence.min) | $($stats.top_confidence.max) | $($stats.top_confidence.stdev) | $($stats.top_confidence.n) |
| Task success rate (5-task throughput) | $($stats.task_success_rate.mean) | $($stats.task_success_rate.median) | $($stats.task_success_rate.min) | $($stats.task_success_rate.max) | $($stats.task_success_rate.stdev) | $($stats.task_success_rate.n) |

## Per-run detail

| Run | Success | Failure stage | MTTD | Analysis | MTTR | Top confidence | Remediation available | Task success rate |
|---|---|---|---|---|---|---|---|---|
$(($runRecords | ForEach-Object { "| $($_.run_at) | $($_.success) | $($_.failure_stage) | $($_.airra.mttd_seconds) | $($_.airra.analysis_seconds) | $($_.airra.mttr_seconds_inject_to_execute) | $($_.airra.top_confidence) | $($_.airra.remediation_available) | $($_.task_success_rate) |" }) -join "`n")
"@ | Set-Content -Encoding utf8 $mdPath

Write-Host "`nWrote $jsonPath"
Write-Host "Wrote $mdPath"
