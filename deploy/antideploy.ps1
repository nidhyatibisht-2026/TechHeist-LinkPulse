<#
.SYNOPSIS
  Deploy and inspect LinkPulse on Antideploy from Windows PowerShell, using a project key.

.DESCRIPTION
  A project key (starts with "ad_") belongs to exactly one Antideploy app:
    linkpulse      -> https://linkpulse.antideploy.app  (dashboard, frontend\)
    linkpulse-api  -> https://lnkp.antideploy.app       (API + short links, backend\)
  Put the key in the ANTIDEPLOY_KEY environment variable, never in a file inside the repo:
    setx ANTIDEPLOY_KEY "ad_..."      (then open a new PowerShell window)

  The script checks that the key belongs to the app you name, so the frontend can never be
  pushed into the API app by mistake.

.EXAMPLE
  .\deploy\antideploy.ps1 -App web -DryRun      # check key + pack the folder, upload nothing
  .\deploy\antideploy.ps1 -App web              # deploy the dashboard and wait for the result
  .\deploy\antideploy.ps1 -App web -Action status
  .\deploy\antideploy.ps1 -App web -Action logs
  .\deploy\antideploy.ps1 -App web -Action rollback
#>
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][ValidateSet("web", "api")][string]$App,
  [ValidateSet("deploy", "status", "history", "logs", "health", "metrics", "redeploy", "rollback")]
  [string]$Action = "deploy",
  [switch]$DryRun,   # deploy only: verify everything, upload nothing
  [switch]$Yes       # skip the confirmation prompt
)

$ErrorActionPreference = "Stop"
$Api = "https://antideploy.com/api/v1"
$Root = Split-Path -Parent $PSScriptRoot   # repo root (this file lives in deploy\)

$Targets = @{
  web = @{ Name = "linkpulse";     Folder = "frontend"; Url = "https://linkpulse.antideploy.app"
           # Dockerfile and nginx.conf are for docker compose; without them Antideploy builds a static site.
           Exclude = @("node_modules", "dist", ".env", "Dockerfile", "nginx.conf", ".antideploy.json") }
  api = @{ Name = "linkpulse-api"; Folder = "backend";  Url = "https://lnkp.antideploy.app"
           Exclude = @(".env", ".env.antideploy", ".venv", "*.db", "__pycache__", ".pytest_cache", ".antideploy.json") }
}
$T = $Targets[$App]

# ---------------------------------------------------------------- key
$Key = $env:ANTIDEPLOY_KEY
if (-not $Key) { $Key = [Environment]::GetEnvironmentVariable("ANTIDEPLOY_KEY", "User") }
if (-not $Key) {
  Write-Host "ANTIDEPLOY_KEY is not set. Run:  setx ANTIDEPLOY_KEY `"ad_...`"  then open a new PowerShell window." -ForegroundColor Red
  exit 1
}
$Headers = @{ Authorization = "Bearer $Key" }

function Invoke-Antideploy([string]$Method, [string]$Path, $Body = $null) {
  $params = @{ Method = $Method; Uri = "$Api$Path"; Headers = $Headers }
  if ($null -ne $Body) { $params.Body = ($Body | ConvertTo-Json -Depth 5); $params.ContentType = "application/json" }
  try { return Invoke-RestMethod @params }
  catch {
    $msg = $_.ErrorDetails.Message
    if (-not $msg) { $msg = $_.Exception.Message }
    Write-Host "Antideploy said: $msg" -ForegroundColor Red
    exit 1
  }
}

# The key decides the app; make sure it is the one we were asked for.
$apps = (Invoke-Antideploy GET "/applications").applications
if (-not $apps -or $apps.Count -ne 1 -or $apps[0].name -ne $T.Name) {
  $names = ($apps | ForEach-Object { $_.name }) -join ", "
  Write-Host "This key belongs to '$names', not '$($T.Name)'. Use the key for the $App app." -ForegroundColor Red
  exit 1
}
Write-Host "Key OK: app '$($T.Name)' -> $($T.Url)" -ForegroundColor Green

function Wait-Deploy([string]$TaskId) {
  Write-Host "Waiting for $TaskId ..."
  $deadline = (Get-Date).AddMinutes(15)
  do {
    Start-Sleep -Seconds 10
    $d = Invoke-Antideploy GET "/deployments/$TaskId"
    Write-Host "  status: $($d.status)"
  } until ($d.status -eq "succeeded" -or $d.status -eq "failed" -or (Get-Date) -gt $deadline)

  if ($d.status -eq "succeeded") {
    Write-Host $d.summary -ForegroundColor Green
    if ($d.hazards) { $d.hazards | ForEach-Object { Write-Host "  note: $($_.title)" -ForegroundColor Yellow } }
    Write-Host "Now open $($T.Url) and run the live checklist."
  } elseif ($d.status -eq "failed") {
    Write-Host "Deploy FAILED at step '$($d.failedStep)': $($d.error)" -ForegroundColor Red
    Write-Host "Read the logs:   .\deploy\antideploy.ps1 -App $App -Action logs"
    Write-Host "Undo it:         .\deploy\antideploy.ps1 -App $App -Action rollback"
    exit 1
  } else {
    Write-Host "Still running after 15 minutes. Check later with -Action status." -ForegroundColor Yellow
  }
}

# ---------------------------------------------------------------- actions
switch ($Action) {
  "deploy" {
    $folder = Join-Path $Root $T.Folder
    if (-not (Test-Path $folder)) { Write-Host "Folder not found: $folder" -ForegroundColor Red; exit 1 }
    $archive = Join-Path $env:TEMP "linkpulse-$App.tgz"
    $tarArgs = @("-czf", $archive, "-C", $folder)
    foreach ($e in $T.Exclude) { $tarArgs += "--exclude=$e" }
    $tarArgs += "."
    & tar.exe @tarArgs
    if ($LASTEXITCODE -ne 0) { Write-Host "tar.exe failed." -ForegroundColor Red; exit 1 }
    $sizeKb = [math]::Round((Get-Item $archive).Length / 1KB)
    Write-Host "Packed $($T.Folder)\ -> $archive ($sizeKb KB)"

    $leaked = & tar.exe -tzf $archive | Where-Object { $_ -match '(^|/)\.env(\.antideploy)?$|\.db$' }
    if ($leaked) { Write-Host "Refusing to upload, secrets found in the archive: $leaked" -ForegroundColor Red; exit 1 }

    if ($DryRun) { Write-Host "Dry run: nothing uploaded." -ForegroundColor Yellow; break }
    if (-not $Yes) {
      $answer = Read-Host "Deploy $($T.Folder)\ to $($T.Url)? Type yes to continue"
      if ($answer -ne "yes") { Write-Host "Cancelled."; break }
    }

    $raw = & curl.exe -s -X POST "$Api/deploy" -H "Authorization: Bearer $Key" -F "archive=@$archive"
    Remove-Item $archive -ErrorAction SilentlyContinue
    try { $res = $raw | ConvertFrom-Json } catch { Write-Host "Unexpected reply from Antideploy: $raw" -ForegroundColor Red; exit 1 }
    if ($res.status -eq "unchanged") { Write-Host "Code is the same as the live version; nothing was built." -ForegroundColor Yellow; break }
    if (-not $res.taskId) { Write-Host "Upload refused: $raw" -ForegroundColor Red; exit 1 }
    Wait-Deploy $res.taskId
  }
  "status" {
    (Invoke-Antideploy GET "/deployments").deployments | Select-Object -First 1 |
      Format-List status, startedAt, finishedAt, error, url
  }
  "history" { (Invoke-Antideploy GET "/deployments").deployments | Format-Table status, startedAt, finishedAt, error -AutoSize }
  "logs"    { (Invoke-Antideploy GET "/logs?limit=100").lines | ForEach-Object { "$($_.at)  $($_.text)" } }
  "health"  { Invoke-Antideploy GET "/health" | Format-List state, detail, recentErrors, consecutiveFailures, checkedAt }
  "metrics" { Invoke-Antideploy GET "/metrics" | ConvertTo-Json -Depth 6 }
  "redeploy" {
    if (-not $Yes -and (Read-Host "Rebuild $($T.Name) with its current variables? Type yes") -ne "yes") { break }
    $r = Invoke-Antideploy POST "/redeploy" @{}
    if ($r.taskId) { Wait-Deploy $r.taskId } else { $r | Format-List }
  }
  "rollback" {
    if (-not $Yes -and (Read-Host "Put back the previous live version of $($T.Name)? Type yes") -ne "yes") { break }
    $r = Invoke-Antideploy POST "/rollback" @{}
    if ($r.taskId) { Wait-Deploy $r.taskId } else { $r | Format-List }
  }
}
