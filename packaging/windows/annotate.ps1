# Put the telling part of a log into one GitHub Actions error annotation, so a failed
# build can be read from the run's summary (the full logs need a sign-in; the summary
# doesn't). An annotation holds about 4,000 characters, so this picks the lines that
# matter (failures, errors, tracebacks) and the end of the log.
#
#     pwsh packaging/windows/annotate.ps1 smoke.log "Test suite failed"
param([string]$log, [string]$title)
$lines = @()
if (Test-Path $log) { $lines = @(Get-Content $log) }
$telling = @($lines | Select-String -Pattern "^FAIL|Traceback|Error|Exception|^\s+File |failed|not found|No module" | ForEach-Object { $_.Line } | Select-Object -First 40)
$tail = @($lines | Select-Object -Last 12)
$text = (($telling + @("--- end of log ---") + $tail) | ForEach-Object { $_ -replace "%", "%25" }) -join "%0A"
if ($text.Length -gt 3800) { $text = $text.Substring(0, 3800) }
Write-Output "::error::$title%0A$text"
