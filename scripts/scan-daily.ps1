# Scan Daily — PowerShell 5.1 compatible
# - Provides Run-Cmd (with timeout), Write-Log, and FAST/FULL run modes
# - Produces a timestamped scan log under .\runs
# - Postprocesses to Discord via scripts\postprocess-and-discord.ps1 when available

# --- Safe logger --------------------------------------------------------------
function Write-Log {
    param([Parameter(Mandatory=$true)][string]$Message)
    $ts = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
    Write-Output "[$ts] $Message"
}

# --- PS 5.1-safe process runner with timeout ---------------------------------
function Run-Cmd {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory=$true)][string]$File,
    [string]$Args = '',
    [int]$TimeoutSec = 60
  )

  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName               = $File
  $psi.Arguments              = $Args
  $psi.UseShellExecute        = $false
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError  = $true
  $psi.CreateNoWindow         = $true

  $p = New-Object System.Diagnostics.Process
  $p.StartInfo = $psi

  $null = $p.Start()
  Write-Log "RUN: $File $Args"
  Write-Log "PID: $($p.Id)"

  # Wait with timeout
  if (-not $p.WaitForExit($TimeoutSec * 1000)) {
    Write-Log "TIMEOUT: Exceeded $TimeoutSec seconds. Killing PID $($p.Id)..."
    try { $p.Kill() } catch {}
    $stdout = ""
    $stderr = ""
    try { $stdout = $p.StandardOutput.ReadToEnd() } catch {}
    try { $stderr = $p.StandardError.ReadToEnd() } catch {}
    return [PSCustomObject]@{
      StdOut   = $stdout
      StdErr   = $stderr
      ExitCode = 124
      TimedOut = $true
    }
  }

  # Completed within timeout
  $stdout = ""
  $stderr = ""
  try { $stdout = $p.StandardOutput.ReadToEnd() } catch {}
  try { $stderr = $p.StandardError.ReadToEnd() } catch {}
  return [PSCustomObject]@{
    StdOut   = $stdout
    StdErr   = $stderr
    ExitCode = $p.ExitCode
    TimedOut = $false
  }
}

try {
    Write-Log "START scan"
    Write-Log "PS $($PSVersionTable.PSVersion.ToString())"

    # Ensure runs folder exists
    New-Item -ItemType Directory -Path "runs" -Force | Out-Null

    # --- Locate Poetry (PS 5.1 compatible) ---
    $cmd = Get-Command poetry -ErrorAction SilentlyContinue
    if ($null -eq $cmd) { throw "Poetry not found on PATH." }
    $poetry = $cmd.Source

    # Poetry version (30s timeout)
    $ver = Run-Cmd -File $poetry -Args '--version' -TimeoutSec 30
    if ($ver.StdOut) { Write-Log "Poetry: $($ver.StdOut.Trim())" }

    # Probe python path in the venv (30s timeout)
    $probe = Run-Cmd -File $poetry -Args 'run python -c "import sys; print(sys.executable)"' -TimeoutSec 30
    Write-Log "Python: $($probe.StdOut.Trim())"

    # --- Run mode switch -----------------------------------------------------
    # FAST = quick daily summary (finishes reliably)
    # FULL = broader sweep (can take longer)
    $mode = $env:YF_MODE
    if (-not $mode) { $mode = "FAST" }  # default

    $runStamp = (Get-Date -Format "yyyy-MM-dd-HHmm")
    $scanLog  = "runs\$($runStamp)-scan.log"

    if ($mode -ieq "FAST") {
        Write-Log "Mode: FAST"
        $chains = @("base","arbitrum")  # quick networks
        foreach ($ch in $chains) {
            $engineArgsArray = @(
                'run','engine',
                '--source','defillama',
                '--category','dex',
                '--chains', $ch,
                '--min-tvl','20000',
                '--max-apy','400',
                '--top','50',
                '--debug'
            )
            $engineArgs = ($engineArgsArray -join ' ')
            Write-Log "EngineArgs[$ch]: $engineArgs"

            $scan = Run-Cmd -File $poetry -Args $engineArgs -TimeoutSec 150
            Add-Content -Path $scanLog -Value $scan.StdOut
            if ($scan.ExitCode -ne 0) {
                Write-Log "Engine exit $($scan.ExitCode) on chain $ch"
                if ($scan.StdErr) { Write-Log "StdErr ($ch):`n$($scan.StdErr)" }
            }
        }
    }
    else {
        Write-Log "Mode: FULL"
        $engineArgsArray = @(
            'run','engine',
            '--source','defillama',
            '--top','100',
            '--max-apy','400',
            '--min-tvl','0',
            '--chains','ethereum,arbitrum,base,optimism,polygon',
            '--debug'
        )
        $engineArgs = ($engineArgsArray -join ' ')
        Write-Log "EngineArgs: $engineArgs"

        # Give the full scan more time (8 minutes)
        $scan = Run-Cmd -File $poetry -Args $engineArgs -TimeoutSec 480
        Add-Content -Path $scanLog -Value $scan.StdOut
        Write-Log "Engine ExitCode: $($scan.ExitCode)"
        if ($scan.ExitCode -ne 0 -and $scan.StdErr) {
            Write-Log "Engine StdErr:`n$($scan.StdErr)"
        }
    }

    # --- Postprocess to Discord (keep your existing pipeline/tooling) --------
    if (Test-Path '.\scripts\postprocess-and-discord.ps1') {
        .\scripts\postprocess-and-discord.ps1 -Top 10
    } else {
        # Fallback: call Python module postprocessor if present
        $ppArgs = 'run python -m engine.postprocess --top 10 --min-tvl 20000 --max-apy 12000 --save-json runs\latest-scan.json'
        $pp = Run-Cmd -File $poetry -Args $ppArgs -TimeoutSec 60
        if ($pp.ExitCode -ne 0 -and $pp.StdErr) {
            Write-Log "Postprocess error:`n$($pp.StdErr)"
        }
    }

    Write-Log "DONE"
}
catch {
    Write-Log "FATAL: $($_.Exception.Message)"
    exit 1
}
