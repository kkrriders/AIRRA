<#
.SYNOPSIS
  Steady light HTTP load on the AI platform so 'api' has a real metric baseline.

.DESCRIPTION
  AIRRA's anomaly detector needs >=3 non-degenerate points in a 5-min window
  before it will score a series. Container healthchecks alone give a nearly-flat
  ~0.07 req/s baseline; this keeps 'api' request_rate lightly but genuinely
  varying so a surge (chaos.ps1 -Scenario api-traffic-surge) reads as anomalous
  against something real rather than against noise.

  This does NOT drive LangGraph runs (those need a Supabase JWT). It only
  exercises the FastAPI 'api' service via /health and a 401 on /projects.

.EXAMPLE
  ./traffic.ps1                 # 10 min, ~1 req/s
  ./traffic.ps1 -Forever        # until Ctrl+C
  ./traffic.ps1 -Rps 3 -DurationSec 120
#>
[CmdletBinding()]
param(
    [string]$PlatformUrl = 'http://localhost:8010',
    [double]$Rps = 1.0,
    [int]$DurationSec = 600,
    [switch]$Forever
)

$ErrorActionPreference = 'Continue'
$delayMs = [math]::Max(1, [int](1000 / [math]::Max(0.1, $Rps)))
$sw = [Diagnostics.Stopwatch]::StartNew()
$n = 0

Write-Host "Light load on $PlatformUrl at ~$Rps rps. $(if($Forever){'Ctrl+C to stop.'}else{"Stops after ${DurationSec}s."})"
while ($Forever -or $sw.Elapsed.TotalSeconds -lt $DurationSec) {
    try { $null = Invoke-WebRequest "$PlatformUrl/health" -TimeoutSec 3 -UseBasicParsing } catch {}
    # alternate a 401 so 'api' sees a non-2xx status class too
    if ($n % 5 -eq 0) {
        try { $null = Invoke-WebRequest "$PlatformUrl/projects" -TimeoutSec 3 -UseBasicParsing } catch {}
    }
    $n++
    if ($n % 30 -eq 0) { Write-Host "  $n requests, $([math]::Round($sw.Elapsed.TotalSeconds,0))s elapsed" }
    Start-Sleep -Milliseconds $delayMs
}
Write-Host "Done. $n requests in $([math]::Round($sw.Elapsed.TotalSeconds,1))s."
