# scripts/Get-ScanRows.ps1
function Get-ScanRows {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [string]$Path
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "File not found: $Path"
    }

    $lines = Get-Content -LiteralPath $Path -Encoding UTF8

    # Skip empty lines, timestamps like [2025-10-12T16:06:11], and separator rows
    $payload = $lines | Where-Object {
        $_.Trim() -ne "" -and
        ($_ -notmatch '^\s*\[\d{4}-\d{2}-\d{2}T') -and
        ($_ -notmatch '^\s*-{5,}\s*$')
    }

    # Find the first header-ish row; after that, parse table-like rows
    $headerIdx = ($payload | Select-String -Pattern 'APY%|Name|TVL' -SimpleMatch | Select-Object -First 1).LineNumber
    if (-not $headerIdx) { $headerIdx = 1 }

    $data = $payload[$headerIdx..($payload.Count-1)]

    foreach ($line in $data) {
        # split on 2+ spaces to handle padded columns
        $parts = ($line -split '\s{2,}').ForEach({ $_.Trim() }) | Where-Object { $_ -ne '' }
        if ($parts.Count -lt 4) { continue }

        # Heuristic: if first token contains a %, assume APY-first layout (Discord view)
        $apyFirst = $parts[0] -match '%$'

        if ($apyFirst) {
            $obj = [PSCustomObject]@{
                Name  = $parts[3]
                APY   = $parts[0]
                TVL   = $parts[1]
                Chain = $parts[2]
                Raw   = $line
            }
        } else {
            # Name-first layout (engine print)
            $obj = [PSCustomObject]@{
                Name  = $parts[0]
                APY   = $parts[1]
                TVL   = $parts[3]  # many prints have TVL after Source
                Chain = $parts[4]  # adjust if needed
                Raw   = $line
            }
        }

        # Only emit rows that look like real data (APY has % and TVL has digits)
        if ($obj.APY -match '%$' -and $obj.TVL -match '\d') { $obj }
    }
}
