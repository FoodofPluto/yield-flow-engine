# scripts/parse-engine.ps1
# Hardened parser compatible with Windows PowerShell 5.1.
# - Handles raw engine tables and debug-dumped lines
# - Tolerates bullets ("- ") and "[...][raw]" prefixes
# - Parses either layout:
#     A) Name | APY% | Source | TVL (USD) | Chain
#     B) APY% | TVL (USD) | Chain | Name
# - Emits objects with: Name, APY (double), TVL (double), Chain, Source

# Avoid super-strict mode differences across shells
Set-StrictMode -Version 2.0

function Parse-Number {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)]
    [string]$Text
  )
  $clean = ($Text -replace '[\$,]', '').Trim()
  if ($clean -eq '') { return $null }
  try {
    return [double]::Parse($clean, [System.Globalization.CultureInfo]::InvariantCulture)
  } catch {
    return $null
  }
}

function Parse-Percent {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)]
    [string]$Text
  )
  $clean = ($Text -replace '%', '' -replace ',', '').Trim()
  if ($clean -eq '') { return $null }
  try {
    return [double]::Parse($clean, [System.Globalization.CultureInfo]::InvariantCulture)
  } catch {
    return $null
  }
}

function Normalize-Line {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)]
    [string]$Line
  )

  $l = $Line

  # Strip optional bullet used in debug dumps: "  - ..."
  $l = $l -replace '^\s*-\s+', ''

  # Strip optional timestamp/raw prefixes: "[2025-10-21T20:52:21] [raw] "
  $l = $l -replace '^\[\d{4}-\d{2}-\d{2}T[^\]]+\]\s*\[raw\]\s*', ''

  return $l.TrimEnd()
}

function Is-HeaderOrRuler {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory)]
    [string]$Line
  )
  $t = $Line.Trim()

  if ($t -match '^\s*Name\s+APY%') { return $true }
  if ($t -match '^-{10,}$') { return $true }
  if ($t -eq '') { return $true }
  if ($t -match '^\[skip') { return $true }
  return $false
}

function Parse-EngineTable {
  <#
    .SYNOPSIS
      Parse Yield Flow engine table lines into objects.

    .DESCRIPTION
      Accepts engine output lines (either raw or debug-dumped) via pipeline or array
      and emits PSCustomObjects with: Name, APY, TVL, Chain, Source (optional).

    .OUTPUTS
      [pscustomobject] with properties: Name, APY ([double]), TVL ([double]), Chain, Source
  #>
  [CmdletBinding()]
  param(
    [Parameter(ValueFromPipeline = $true)]
    [string] $InputObject
  )

  begin {
    $buf = New-Object System.Collections.Generic.List[string]
  }
  process {
    if ($null -ne $InputObject) { [void]$buf.Add($InputObject) }
  }
  end {
    $rows = New-Object System.Collections.Generic.List[object]

    foreach ($raw in $buf) {
      $line = Normalize-Line -Line $raw
      if (Is-HeaderOrRuler -Line $line) { continue }

      # Split on 2+ spaces; table columns are padded
      $parts = @($line -split '\s{2,}' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
      if ($parts.Count -lt 2) { continue }

      $name = $null; $apyText = $null; $tvlText = $null; $chain = $null; $source = $null

      # Helpers compatible with PS 5.1 (no script blocks as delegates)
      $isNumberLike = $false
      if ($parts[0] -match '^[\d,\.]+%?$') { $isNumberLike = $true }

      # Detect layouts
      if ($parts.Count -ge 5 -and ($parts[1] -match '^[\d,\.]+%?$')) {
        # Layout A (engine printout): Name | APY% | Source | TVL | Chain
        $name     = $parts[0]
        $apyText  = $parts[1]
        $source   = $parts[2]
        $tvlText  = $parts[3]
        $chain    = $parts[4]
      }
      elseif ($parts.Count -ge 4 -and ($parts[0] -match '^[\d,\.]+%?$') -and ($parts[1] -match '^[\$\d,\.]+$')) {
        # Layout B (discord view): APY% | TVL | Chain | Name (name may contain spaces)
        $apyText  = $parts[0]
        $tvlText  = $parts[1]
        $chain    = $parts[2]
        if ($parts.Count -gt 4) {
          $name = ($parts[3..($parts.Count-1)] -join ' ')
        } else {
          $name = $parts[3]
        }
      }
      else {
        # Conservative fallback: name first, apy near start, chain at end
        if ($parts.Count -ge 4 -and ($parts[1] -match '^[\d,\.]+%?$')) {
          $name     = $parts[0]
          $apyText  = $parts[1]
          $tvlText  = $parts[$parts.Count-2]
          $chain    = $parts[$parts.Count-1]
          if ($parts.Count -ge 6) { $source = $parts[2] }
        } else {
          continue
        }
      }

      $apy = if ($apyText) { Parse-Percent $apyText } else { $null }
      $tvl = if ($tvlText) { Parse-Number  $tvlText } else { $null }

      if (-not $name) { continue }

      $obj = [pscustomobject]@{
        Name   = $name
        APY    = $apy
        TVL    = $tvl
        Chain  = $chain
        Source = $source
      }
      [void]$rows.Add($obj)
    }

    # Emit parsed rows
    $rows
  }
}

# No Export-ModuleMember here to avoid module-scope requirement.
