param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("crashloop", "database-latency", "redis-outage", "recover")]
    [string]$Scenario
)

$namespace = "airra-lab"

switch ($Scenario) {
    "crashloop" {
        kubectl -n $namespace set env deployment/payment-service CRASH_LOOP=true
        Write-Host "Injected bad config. payment-service will enter CrashLoopBackOff."
    }
    "database-latency" {
        kubectl -n $namespace set env deployment/api-service DATABASE_DELAY_MS=1500
        kubectl -n $namespace set env deployment/order-service DATABASE_DELAY_MS=1500
        kubectl -n $namespace set env deployment/payment-service DATABASE_DELAY_MS=1500
        Write-Host "Injected 1.5s PostgreSQL latency into the request path."
    }
    "redis-outage" {
        kubectl -n $namespace scale deployment/redis --replicas=0
        Write-Host "Redis scaled to zero. Dependent services will return 503."
    }
    "recover" {
        kubectl -n $namespace set env deployment/payment-service CRASH_LOOP-
        kubectl -n $namespace set env deployment/api-service DATABASE_DELAY_MS-
        kubectl -n $namespace set env deployment/order-service DATABASE_DELAY_MS-
        kubectl -n $namespace set env deployment/payment-service DATABASE_DELAY_MS-
        kubectl -n $namespace scale deployment/redis --replicas=1
        Write-Host "Removed injected faults and restored Redis."
    }
}
