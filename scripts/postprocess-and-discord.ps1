param(
  [int]$Top = 10,
  [string]$Webhook = $env:DISCORD_WEBHOOK
)

# Resolve paths from this script's location
$scriptsDir = Split-Path -Parent $PSCommandPath
$repoRoot   = Split-Path -Parent $scriptsDir
$runsDir    = Join-Path $repoRoot "runs"
$postScript = Join-Path $scriptsDir "post-to-discord.ps1"

if (-not $Webhook) { throw "No webhook provided. Set DISCORD_WEBHOOK or pass -Webhook." }
if (-not (Test-Path $runsDir)) { New-Item -ItemType Directory -Force -Path $runsDir | Out-Null }

# Pick the latest *-scan.log
$latestScan = Get-ChildItem (Join-Path $runsDir "*-scan.log") -ErrorAction SilentlyContinue |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1

if (-not $latestScan) {
  throw "No scan logs found in '$runsDir'. Run the scanner first to create a *-scan.log."
}

$scanLog = $latestScan.FullName

# Read log lines
$allLines = (Get-Content -Raw $scanLog -Encoding UTF8 -ErrorAction Stop) -split "`r?`n"

# Try to anchor on the table; else, take the last 120 lines
$tableAnchor = ($allLines | Select-String -Pattern '^-{5,}|^Name\s+APY%.*' -SimpleMatch | Select-Object -First 1)
if ($tableAnchor) {
  $startIndex = $tableAnchor.LineNumber - 1
  $sliceCount = 50 + (5 * $Top)
  $endIndex = [Math]::Min($allLines.Count - 1, $startIndex + $sliceCount)
  $tail = $allLines[$startIndex..$endIndex]
} else {
  $take = [Math]::Min(120, $allLines.Count)
  $tail = $allLines[($allLines.Count - $take)..($allLines.Count - 1)]
}

# Build outputs
$timestamp  = (Get-Date).ToString("yyyy-MM-dd-HHmm")
$reportPath = Join-Path $runsDir "$timestamp-report.md"
$discordTxt = Join-Path $runsDir "$timestamp-discord.txt"

# Markdown report (ASCII-only)
$report = @()
$report += "# Yield Flow - Report ($timestamp)"
$report += ""
$report += "Latest scan log: `"$($latestScan.Name)`""
$report += ""
$report += '```'
$report += ($tail -join "`n")
$report += '```'

$report -join "`n" | Set-Content -Encoding UTF8 $reportPath
Write-Output ("Wrote " + (Resolve-Path $reportPath -ErrorAction SilentlyContinue))

# Concise Discord text
$header = "Yield Flow - Top $Top from $($latestScan.Name)"
$bodyLines = @()
foreach ($ln in $tail) {
  if ($ln -match '^\s*-{3,}\s*$') { continue }
  if ($ln.Trim().Length -eq 0) { continue }
  $bodyLines += $ln
  if ($bodyLines.Count -ge (5 + $Top)) { break }
}

($header + "`n" + ($bodyLines -join "`n")) | Set-Content -Encoding UTF8 $discordTxt
Write-Output ("Wrote " + (Resolve-Path $discordTxt -ErrorAction SilentlyContinue))

# Post to Discord
if (-not (Test-Path $postScript)) {
  throw "Cannot find poster script at: $postScript"
}

& $postScript -Webhook $Webhook -TextFile $discordTxt
