# scripts/parse-engine.ps1 (regex edition)
# Ultra-robust parser for Windows PowerShell 5.1
# Matches two known layouts using regex; ignores headers/rulers and debug bullets/prefixes.

Set-StrictMode -Version 2.0

function _CleanLine {
  param([Parameter(Mandatory)][string]$Line)
  $l = $Line

  # Remove leading bullet from debug dumps: "  - ..."
  $l = $l -replace '^\s*-\s+', ''

  # Remove "[...][raw]" prefix if present
  $l = $l -replace '^\[\d{4}-\d{2}-\d{2}T[^\]]+\]\s*\[raw\]\s*', ''

  return $l.TrimEnd()
}

function _IsSkippable {
  param([Parameter(Mandatory)][string]$Line)
  $t = $Line.Trim()

  if ($t -eq '') { return $true }
  if ($t -match '^\s*Name\s+APY%') { return $true }
  if ($t -match '^-{10,}$') { return $true }
  if ($t -match '^\[skip') { return $true }
  return $false
}

function _ToDouble {
  param([string]$Text, [switch]$Percent)
  if (-not $Text) { return $null }
  $x = $Text
  if ($Percent) { $x = $x -replace '%','' }
  $x = $x -replace '[\$,]',''
  $x = $x.Trim()
  if ($x -eq '') { return $null }
  try { return [double]::Parse($x, [System.Globalization.CultureInfo]::InvariantCulture) } catch { return $null }
}

function Parse-EngineTable {
  <#
    .SYNOPSIS
      Regex-based parser for engine/discord tables.
    .OUTPUTS
      PSCustomObject(Name, APY [double], TVL [double], Chain, Source)
  #>
  [CmdletBinding()]
  param(
    [Parameter(ValueFromPipeline=$true)]
    [string]$InputObject
  )

  begin {
    $rows = New-Object System.Collections.Generic.List[object]

    # Layout A (engine): Name  APY%  Source  TVL  Chain
    $rxA = '^(?<name>.+?)\s{2,}(?<apy>[\d,\.]+)%?\s+(?<source>\S+)\s+(?<tvl>[\$\d,\,\.]+)\s+(?<chain>\S+)$'

    # Layout B (discord): APY%  TVL  Chain  Name
    $rxB = '^(?<apy>[\d,\.]+)%?\s{2,}(?<tvl>[\$\d,\,\.]+)\s{2,}(?<chain>\S+)\s{2,}(?<name>.+)$'
  }

  process {
    if ($null -eq $InputObject) { return }
    $line = _CleanLine $InputObject
    if (_IsSkippable $line) { return }

    $m = [regex]::Match($line, $rxA)
    if (-not $m.Success) { $m = [regex]::Match($line, $rxB) }
    if (-not $m.Success) { return }

    $name   = $m.Groups['name'].Value.Trim()
    $apy    = _ToDouble $m.Groups['apy'].Value -Percent
    $tvl    = _ToDouble $m.Groups['tvl'].Value
    $chain  = ($m.Groups['chain'].Value.Trim())
    $source = if ($m.Groups['source'] -and $m.Groups['source'].Success) { $m.Groups['source'].Value.Trim() } else { $null }

    if ($name) {
      $obj = [pscustomobject]@{
        Name   = $name
        APY    = $apy
        TVL    = $tvl
        Chain  = $chain
        Source = $source
      }
      [void]$rows.Add($obj)
    }
  }

  end {
    $rows
  }
}
