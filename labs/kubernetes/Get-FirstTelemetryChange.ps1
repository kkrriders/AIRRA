function Get-FirstTelemetryChange {
    param(
        [string]$PrometheusUrl = 'http://localhost:9091',
        [string]$Query = 'sum(kube_pod_container_status_restarts_total{namespace="airra-lab",pod=~"payment-service-.*"})',
        [double]$BaselineValue,
        [DateTime]$StartTime,
        [int]$TimeoutSec = 90,
        [int]$StepSec = 5
    )

    # Get-Date -UFormat %s does NOT convert Unspecified/Local-kind DateTimes to UTC in
    # Windows PowerShell 5.1 -- it treats the wall-clock numbers as if they were already
    # UTC, producing an epoch offset by the local UTC offset (5.5h wrong on an IST
    # machine, silently returning zero results). Convert explicitly instead.
    $epoch1970 = [DateTime]::new(1970, 1, 1, 0, 0, 0, [DateTimeKind]::Utc)
    function ToUnixSeconds([DateTime]$dt) {
        return [int64]([Math]::Floor(($dt.ToUniversalTime() - $epoch1970).TotalSeconds))
    }

    $deadline = $StartTime.AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $end = Get-Date
        $uri = "$PrometheusUrl/api/v1/query_range" +
            "?query=$([uri]::EscapeDataString($Query))" +
            "&start=$(ToUnixSeconds $StartTime)" +
            "&end=$(ToUnixSeconds $end)" +
            "&step=${StepSec}s"
        try {
            $resp = Invoke-RestMethod -Uri $uri -TimeoutSec 10
            $series = $resp.data.result
            if ($series -and $series.Count -gt 0) {
                foreach ($point in $series[0].values) {
                    # point = [ <unix_ts>, "<value_string>" ]
                    $value = [double]$point[1]
                    if ($value -gt $BaselineValue) {
                        return [DateTimeOffset]::FromUnixTimeSeconds([long]$point[0]).UtcDateTime
                    }
                }
            }
        } catch {
            Write-Warning "Prometheus query failed, retrying: $($_.Exception.Message)"
        }
        Start-Sleep -Seconds $StepSec
    }
    return $null
}
