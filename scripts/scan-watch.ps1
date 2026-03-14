param(
  [int]$IntervalSec = 300,                 # scan every N seconds
  [double]$MinAPY = 30.0,                  # trigger if APY >= this
  [double]$MinTVL = 10000,                 # and TVL >= this
  [double]$MaxAPY = 5000.0,                # ignore absurd APYs
  [string[]]$Chains = @("arbitrum","base","optimism","polygon","ethereum"),
  [string]$Webhook = $env:DISCORD_WEBHOOK, # optional: set env var to enable Discord posts
  [string]$ExcelPath = ".\YieldFlow_Tracker.xlsx",
  [switch]$PostToDiscord,
  [switch]$WriteToExcel
)

# ---------- helpers ----------
function Write-Log {
  param([string]$msg)
  $ts = (Get-Date).ToString("s")
  Write-Host "[$ts] $msg"
}

function Get-PoetryPath {
  $cmd = Get-Command poetry -ErrorAction SilentlyContinue
  if (-not $cmd) { throw "Poetry not found on PATH." }
  return $cmd.Source
}

# Build engine args from your params (add/remove flags your engine supports)
$engineArgs = @(
  "--source defillama",
  "--chains `"$($Chains -join ',')`"",
  "--min-tvl $MinTVL",
  "--max-apy $MaxAPY",
  "--top 50",
  "--stable-mode any"
) -join ' '

Write-Host "[scan-watch] engine args: $engineArgs"

# Run it and keep a copy of the raw table for debugging
$ts = Get-Date -Format "yyyy-MM-dd-HHmm"
$logPath = ".\runs\$ts-scan.raw.txt"
$raw = poetry run engine $engineArgs 2>&1 | Tee-Object -FilePath $logPath



function Run-Engine {
  param(
    [string[]]$Chains,
    [double]$MaxAPY
  )
  $poetry = Get-PoetryPath

  $args = @(
    "run","engine",
    "--source","defillama",
    "--chains", ($Chains -join ","),
    "--min-tvl","10000",
    "--max-apy", ("{0:F2}" -f $MaxAPY),
    "--top","100"
  )

  $pinfo = New-Object System.Diagnostics.ProcessStartInfo
  $pinfo.FileName = $poetry
  $pinfo.Arguments = ($args -join " ")
  $pinfo.UseShellExecute = $false
  $pinfo.RedirectStandardOutput = $true
  $pinfo.RedirectStandardError = $true

  $proc = New-Object System.Diagnostics.Process
  $proc.StartInfo = $pinfo
  [void]$proc.Start()

  if (-not $proc.WaitForExit(120000)) {
    try { $proc.Kill() } catch {}
    throw "engine timed out"
  }

  $out = $proc.StandardOutput.ReadToEnd()
  $err = $proc.StandardError.ReadToEnd()
  $code = $proc.ExitCode

  return [PSCustomObject]@{
    Out  = $out
    Err  = $err
    Code = $code
  }
}

function Parse-EngineTable {
  param([string]$text)
  $lines = $text -split "`r?`n"
  $rows  = @()

  foreach ($line in $lines) {
    if ($line -match '^(Name\s+APY|[-]{3,}|\s*$)') { continue }

    $parts = ($line -split '\s{2,}').Trim() | Where-Object { $_ -ne '' }
    if ($parts.Count -lt 4) { continue }

    $name=$null;$apy=$null;$tvl=$null;$chain=$null

    # Heuristic A: "Name | APY% | Source | TVL (USD) | Chain"
    if ($parts[1] -match '%$' -and $parts[3] -match '^[\d,]+$' -and $parts.Count -ge 5) {
      $name  = $parts[0]
      $apy   = $parts[1]
      $tvl   = $parts[3]
      $chain = $parts[4]
    }
    # Heuristic B: "APY% | TVL | Chain | Name"
    elseif ($parts[0] -match '%$' -and $parts[1] -match '^[\d,]+$' -and $parts[2] -match '^[A-Za-z\-]+$' -and $parts.Count -ge 4) {
      $name  = ($parts[3..($parts.Count-1)] -join ' ')
      $apy   = $parts[0]
      $tvl   = $parts[1]
      $chain = $parts[2]
    }
    else { continue }

    # normalize numbers
    $apyNum = 0.0
    $tvlNum = 0.0
    try {
      $apyNum = [double]($apy -replace '%','' -replace ',','.' -replace '[^\d\.]','')
    } catch {}
    try {
      $tvlNum = [double]($tvl -replace ',','' -replace '[^\d]','')
    } catch {}

    $rows += [PSCustomObject]@{
      Name  = $name
      APY   = $apyNum
      TVL   = $tvlNum
      Chain = ($chain -as [string])
      Raw   = $line
    }
  }

  return $rows
}

# de-dupe memory (in-memory, 60 min window)
$Seen = @{}   # key -> DateTime last seen

function Seen-Recently {
  param([string]$key, [int]$minutes = 60)
  if ($Seen.ContainsKey($key)) {
    $delta = (New-TimeSpan -Start $Seen[$key] -End (Get-Date)).TotalMinutes
    if ($delta -lt $minutes) { return $true }
  }
  $Seen[$key] = Get-Date
  return $false
}

function Post-Discord {
  param([string]$Webhook, [string]$content)
  if (-not $Webhook) { return }
  $body = @{ content = $content } | ConvertTo-Json -Compress
  try {
    Invoke-RestMethod -Uri $Webhook -Method Post -ContentType "application/json; charset=UTF-8" -Body $body | Out-Null
  } catch {
    Write-Log "Discord post failed: $($_.Exception.Message)"
  }
}

function Append-To-Excel {
  param([string]$ExcelPath, [Object[]]$rows)
  if (-not (Test-Path $ExcelPath)) {
    Write-Log "Excel not found at $ExcelPath (skipping write)."
    return
  }
  $tmp = Join-Path $env:TEMP "yf_last_scan.txt"
  try {
    $rows | ForEach-Object { $_.Raw } | Set-Content -Encoding UTF8 $tmp
  } catch {}
  try {
    $poetry = Get-PoetryPath
    & $poetry run python yf_ingest.py --input $tmp --workbook $ExcelPath | Out-Null
    Write-Log "Appended $(($rows | Measure-Object).Count) row(s) to Excel."
  } catch {
    Write-Log "Excel append failed: $($_.Exception.Message)"
  } finally {
    if (Test-Path $tmp) { Remove-Item $tmp -Force }
  }
}

# ---------- watcher loop ----------
Write-Log ("Starting watch: every {0}s; MinAPY={1}; MinTVL={2}; MaxAPY={3}; Chains={4}" -f `
  $IntervalSec, $MinAPY, $MinTVL, $MaxAPY, ($Chains -join ','))
if ($PostToDiscord -and -not $Webhook) { Write-Log "Note: -PostToDiscord set but no DISCORD_WEBHOOK env var." }

while ($true) {
  try {
    $res = Run-Engine -Chains $Chains -MaxAPY $MaxAPY
    if ($res.Code -ne 0) {
      Write-Log ("engine exit {0}. stderr: {1}" -f $res.Code, ($res.Err.Trim()))
    }

    $rows = Parse-EngineTable -text $res.Out

    # Normalize chain case for matching
    $hits = $rows | Where-Object {
      ($_.APY -ge $MinAPY) -and
      ($_.APY -le $MaxAPY) -and
      ($_.TVL -ge $MinTVL) -and
      ($Chains -contains ($_.Chain.ToString().ToLower()))
    }

    if ($hits.Count -gt 0) {
      foreach ($h in $hits) {
        $key = ("{0}|{1}" -f $h.Name, $h.Chain)
        if (Seen-Recently -key $key) { continue }

        # escape the literal $ for -f; use normal hyphens to avoid encoding issues
        $msg = ("HIT: {0} - {1:N2}% APY - `${2:N0} TVL - {3}" -f $h.Name, $h.APY, $h.TVL, $h.Chain)

        Write-Host ""
        Write-Host "==================== HIT ====================" -ForegroundColor Green
        Write-Host $msg -ForegroundColor Green
        Write-Host "============================================="
        Write-Host ""

        if ($PostToDiscord -and $Webhook) {
          Post-Discord -Webhook $Webhook -content (":zap: {0}" -f $msg)
        }
      }

      if ($WriteToExcel) {
        Append-To-Excel -ExcelPath $ExcelPath -rows $hits
      }
    } else {
      Write-Log ("no hits this round ({0} rows scanned)" -f (($rows | Measure-Object).Count))
    }
  }
  catch {
    Write-Log ("scan error: {0}" -f $_.Exception.Message)
  }

  Start-Sleep -Seconds $IntervalSec
}
