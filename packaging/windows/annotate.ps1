# Put the end of a log into one GitHub Actions error annotation, so a failed build can be
# read from the run's summary (the full logs need a sign-in; the summary doesn't).
#
#     pwsh packaging/windows/annotate.ps1 smoke.log "Test suite failed"
param([string]$log, [string]$title)
$lines = @()
if (Test-Path $log) { $lines = Get-Content $log | Select-Object -Last 60 }
$body = ($lines | ForEach-Object { $_ -replace "%", "%25" }) -join "%0A"
Write-Output "::error::$title%0A$body"
