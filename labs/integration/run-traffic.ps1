<#
.SYNOPSIS
  Drives real LangGraph runs against the AI platform (Phase A3 follow-up).

.DESCRIPTION
  traffic.ps1 only pings /health - it never executes the graph, so the 5 node
  metrics (orchestrator/researcher/tool_runner/executor/verifier) stay at zero
  and node-crash has nothing to show. This script does the real thing:

    1. Mint a Supabase session JWT (password grant against the real hosted
       Supabase project - there is no local/dev auth bypass, see
       backend/app/auth.py). Signs up a fixed test user on first use.
    2. Create one project + one conversation.
    3. Loop POSTing /conversations/{id}/runs with a unique input each time
       (the platform caches responses by input+context - a repeated input
       skips the graph entirely and produces no node metrics).

  Each run is synchronous and blocks until the graph finishes, so this loops
  request-after-request with a small delay rather than targeting an Rps.

  Pair with chaos.ps1 -Scenario node-crash: set CHAOS_FAIL_NODE first, then
  run this so the graph actually reaches (and fails) that node.

.EXAMPLE
  ./run-traffic.ps1                                   # 5 min, ~1 run/3s
  ./run-traffic.ps1 -Forever
  ../../labs/integration/chaos.ps1 -Scenario node-crash -Node tool_runner
  ./run-traffic.ps1 -DurationSec 120
#>
[CmdletBinding()]
param(
    [int]$DurationSec = 300,
    [switch]$Forever,
    [double]$DelaySec = 3,

    [string]$PlatformUrl = 'http://localhost:8010',
    [string]$PlatformEnvFile = "$HOME\Multi Agent Intelligence Platform\backend\.env",
    [string]$SupabaseUrl,
    [string]$SupabaseAnonKey,

    # fixed test user - plus-addressed off the real project owner's inbox so
    # signup/login works against the real hosted Supabase project with no
    # separate mailbox to manage. ponytail: one shared test user is enough
    # for a traffic generator; add per-run users only if runs need isolation.
    [string]$Email = 'anshuman.aroraak+airra-traffic@gmail.com',
    [string]$Password = 'hunter2-hunter2',
    [string]$ProjectName = 'airra-traffic-gen'
)

$ErrorActionPreference = 'Stop'

function Get-EnvValue([string]$file, [string]$key) {
    if (-not (Test-Path $file)) { return $null }
    $m = Select-String -Path $file -Pattern "^$key=(.+)$"
    if ($m) { return $m[0].Matches.Groups[1].Value.Trim() }
    return $null
}

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
    try {
        return Invoke-SupabaseSignIn
    } catch {
        Write-Host "Sign-in failed, signing up test user $Email ..."
        $body = @{ email = $Email; password = $Password } | ConvertTo-Json
        try {
            Invoke-RestMethod "$SupabaseUrl/auth/v1/signup" -Method Post `
                -Headers @{ apikey = $SupabaseAnonKey; 'Content-Type' = 'application/json' } -Body $body | Out-Null
        } catch {
            Write-Host "Signup call errored (may already exist): $($_.Exception.Message)"
        }
        try {
            return Invoke-SupabaseSignIn
        } catch {
            throw "Still can't sign in after signup. If the Supabase project requires email confirmation, disable it for this dev project (Auth settings) or confirm $Email manually, then retry. Original error: $($_.Exception.Message)"
        }
    }
}

Write-Host "Authenticating as $Email against $SupabaseUrl ..."
$session = Get-SupabaseToken
$token = $session.access_token
$tokenIssued = Get-Date
Write-Host "Got session token, expires in $($session.expires_in)s."

function Get-AuthHeaders { @{ Authorization = "Bearer $token" } }

function Assert-TokenFresh {
    # ponytail: re-mint 5 min before expiry rather than wiring refresh_token rotation
    if (((Get-Date) - $tokenIssued).TotalSeconds -gt ($session.expires_in - 300)) {
        Write-Host "Token nearing expiry, re-authenticating ..."
        $script:session = Get-SupabaseToken
        $script:token = $session.access_token
        $script:tokenIssued = Get-Date
    }
}

Write-Host "Creating project '$ProjectName' ..."
$project = Invoke-RestMethod "$PlatformUrl/projects" -Method Post -Headers (Get-AuthHeaders) `
    -ContentType 'application/json' -Body (@{ name = $ProjectName } | ConvertTo-Json)
Write-Host "  project: $($project.id)"

$conversation = Invoke-RestMethod "$PlatformUrl/projects/$($project.id)/conversations" -Method Post `
    -Headers (Get-AuthHeaders) -ContentType 'application/json' -Body '{}'
Write-Host "  conversation: $($conversation.id)"

Write-Host "Driving runs at ~1 per ${DelaySec}s. $(if($Forever){'Ctrl+C to stop.'}else{"Stops after ${DurationSec}s."})"
$sw = [Diagnostics.Stopwatch]::StartNew()
$n = 0; $ok = 0; $failed = 0
while ($Forever -or $sw.Elapsed.TotalSeconds -lt $DurationSec) {
    Assert-TokenFresh
    $n++
    $input = "AIRRA traffic-gen run $(Get-Date -Format o) #$n"
    try {
        $null = Invoke-RestMethod "$PlatformUrl/conversations/$($conversation.id)/runs" -Method Post `
            -Headers (Get-AuthHeaders) -ContentType 'application/json' -TimeoutSec 60 `
            -Body (@{ input = $input } | ConvertTo-Json)
        $ok++
    } catch {
        $failed++
        Write-Host "  run #$n failed: $($_.Exception.Message)"
    }
    if ($n % 5 -eq 0) { Write-Host "  $n runs ($ok ok, $failed failed), $([math]::Round($sw.Elapsed.TotalSeconds,0))s elapsed" }
    Start-Sleep -Seconds $DelaySec
}
Write-Host "Done. $n runs ($ok ok, $failed failed) in $([math]::Round($sw.Elapsed.TotalSeconds,1))s."
