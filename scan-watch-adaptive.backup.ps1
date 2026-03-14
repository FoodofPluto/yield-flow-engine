[CmdletBinding()]
param(
  [switch]$PostToDiscord,
  [switch]$WriteToExcel,
  [string]$Source      = 'defillama',
  [string]$ChainsCsv   = 'arbitrum,base,optimism,polygon,ethereum',
  [int]$MinTVL         = 10000,
  [int]$MaxAPY         = 5000,
  [int]$Top            = 50,
  [ValidateSet('any','stable','volatile')][string]$StableMode = 'any',
  [string]$ScanDir
)

# --- housekeeping / paths ---
$timestamp = Get-Date -Format 'yyyy-MM-dd-HHmm'
if (-not $ScanDir) { $ScanDir = Join-Path $PSScriptRoot 'runs' }
if (-not (Test-Path $ScanDir)) { New-Item -ItemType Directory -Path $ScanDir | Out-Null }
$scanLog   = Join-Path $ScanDir "$timestamp-scan.log"

Write-Verbose ("[watch] ts={0} dir={1}" -f $timestamp, $ScanDir)

# ===== BEGIN: robust output capture + parser =====

function Invoke-YieldEngine {
  [CmdletBinding()]
  param([string]$ArgsLine)

  $cmd = "poetry run engine $ArgsLine"
  Write-Verbose "[watch] running: $cmd"

  # Capture all output (including Write-Host) as strings
  $out = & powershell -NoProfile -Command $cmd 2>&1 | ForEach-Object { "$_" }

  if ($PSBoundParameters['Debug']) {
    Write-Debug ("[watch] engine raw lines: " + ($out.Count))
    $out | Select-Object -First 12 | ForEach-Object { Write-Debug ("RAW: " + $_) }
  }
  return ,$out
}

# 1) Try to dot-source a shared parser if you have it
$helperPath = Join-Path $PSScriptRoot 'scripts\parse-engine.ps1'
if (Test-Path -LiteralPath $helperPath) {
  Write-Verbose "[watch] Loading parser helper: $helperPath"
  . $helperPath
}

# 2) Fallback robust regex parser
if (-not (Get-Command Parse-EngineTable -CommandType Function -ErrorAction SilentlyContinue)) {
  function Parse-EngineTable {
    [CmdletBinding()]
    param(
      [Parameter(Mandatory=$true, ValueFromPipeline=$true)]
      [string[]]$Lines
    )
    begin {
      $rows = New-Object System.Collections.Generic.List[object]

      # Layout A (engine): Name | APY% | Source | TVL (USD) | Chain
      $rxA = '^\s*(?<name>.+?)\s{2,}(?<apy>[-\d,\.]+)%?\s+(?<source>\S+)\s+(?<tvl>[\$\d,\.]+)\s+(?<chain>\S+)\s*$'

      # Layout B (discord): APY% | TVL | Chain | Name
      $rxB = '^\s*(?<apy>[-\d,\.]+)%?\s{2,}(?<tvl>[\$\d,\.]+)\s+(?<chain>\S+)\s{2,}(?<name>.+?)\s*$'
    }
    process {
      foreach ($line in $Lines) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }

        # Strip optional timestamp + [raw] markers; skip headers/rulers
        $clean = $line `
          -replace '^\[[^\]]*\]\s*\[raw\]\s*','' `
          -replace '^\[raw\]\s*',''
        if ($clean -match '^\s*-{3,}\s*$' -or $clean -match '^\s*Name\s+APY%') { continue }

        $m = [regex]::Match($clean, $rxA)
        if (-not $m.Success) { $m = [regex]::Match($clean, $rxB) }
        if (-not $m.Success) { continue }

        $name   = $m.Groups['name'].Value.Trim()
        $apyTxt = $m.Groups['apy'].Value
        $tvlTxt = $m.Groups['tvl'].Value
        $chain  = $m.Groups['chain'].Value.Trim()
        $source = if ($m.Groups['source'] -and $m.Groups['source'].Success) { $m.Groups['source'].Value } else { $null }

        $apyNum = ($apyTxt -replace '[^0-9\.\-]','') -as [double]
        $tvlNum = ($tvlTxt -replace '[^\d\.]','') -as [double]

        if ([string]::IsNullOrWhiteSpace($name) -or $null -eq $apyNum -or $null -eq $tvlNum -or [string]::IsNullOrWhiteSpace($chain)) {
          continue
        }

        $rows.Add([pscustomobject]@{
          Name   = $name
          APY    = $apyNum
          TVL    = $tvlNum
          Chain  = $chain
          Source = $source
        })
      }
    }
    end {
      if ($PSBoundParameters['Debug']) {
        Write-Debug ("[watch] parsed rows: " + $rows.Count)
        $rows | Select-Object -First 5 | ForEach-Object { Write-Debug ("ROW: " + ($_ | ConvertTo-Json -Compress)) }
      }
      $rows
    }
  }
}

function Show-ParseFailure {
  param([string[]]$Raw)
  Write-Warning "[watch] Parser returned 0 rows - dumping first 40 raw lines:"
  $Raw | Select-Object -First 40 | ForEach-Object { Write-Host ("  - " + $_) }
}

# ===== END: robust output capture + parser =====

# --- compose engine args ---
$engineArgs = @()
if ($Source)      { $engineArgs += @('--source', $Source) }
if ($ChainsCsv)   { $engineArgs += @('--chains', $ChainsCsv) }
if ($MinTVL)      { $engineArgs += @('--min-tvl', $MinTVL) }
if ($MaxAPY)      { $engineArgs += @('--max-apy', $MaxAPY) }
if ($Top)         { $engineArgs += @('--top', $Top) }
if ($StableMode)  { $engineArgs += @('--stable-mode', $StableMode) }

# Quote args that contain spaces/commas
$engineArgsLine = ($engineArgs | ForEach-Object {
  if ($_ -match '[, ]') { '"{0}"' -f $_ } else { $_ }
}) -join ' '

# --- run engine and tee raw to the scan log ---
$engineOut = Invoke-YieldEngine -ArgsLine $engineArgsLine
# Save raw lines to log (as seen)
$engineOut | Set-Content -LiteralPath $scanLog -Encoding UTF8

# --- parse & filter ---
$rows = @($engineOut | Parse-EngineTable)
Write-Verbose "[parse] parsed rows: $($rows.Count)"

$chainList = ($ChainsCsv -split ',') | ForEach-Object { $_.Trim() } | Where-Object { $_ }
$rows = @($rows | Where-Object { $_.Chain -in $chainList })
Write-Verbose "[filter] rows after chains: $($rows.Count)"

if ($rows.Count -eq 0) {
  Show-ParseFailure -Raw $engineOut
  Write-Warning "[watch] No engine rows after parsing/filters this cycle."
  return
}

# --- Excel ingestion (optional) ---
if ($WriteToExcel) {
  $ingest = Join-Path $PSScriptRoot 'yf_ingest.py'
  if (Test-Path -LiteralPath $ingest) {
    $wb = Join-Path $PSScriptRoot 'YieldFlow_Tracker.xlsx'
    Write-Verbose "[excel] ingesting $scanLog -> $wb"
    & python $ingest --input $scanLog --workbook $wb 2>&1 | ForEach-Object { Write-Host $_ }
  } else {
    Write-Warning "[excel] yf_ingest.py not found; skipping Excel write."
  }
}

# --- Discord post (optional) ---
if ($PostToDiscord) {
  $postScript = Join-Path $PSScriptRoot 'scripts\postprocess-and-discord.ps1'
  if (Test-Path -LiteralPath $postScript) {
    Write-Verbose "[discord] running: $postScript"
    & powershell -NoProfile -ExecutionPolicy Bypass -File $postScript -Top 10 2>&1 | ForEach-Object { Write-Host $_ }
  } else {
    Write-Warning "[discord] scripts\postprocess-and-discord.ps1 not found; skipping Discord."
  }
}

Write-Verbose "[watch] Done."
