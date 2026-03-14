param(
  [string]$Webhook = $env:DISCORD_WEBHOOK,
  [string]$TextFile,
  [string]$Message
)

if (-not $Webhook) { throw "No Discord webhook provided. Set -Webhook or DISCORD_WEBHOOK." }

# --- Load text ---
[string]$txt = ""
if ($Message) {
  $txt = [string]$Message
} elseif ($TextFile) {
  if (-not (Test-Path $TextFile)) { throw "Text file not found: $TextFile" }
  $txt = Get-Content -Raw -Encoding UTF8 $TextFile
} else {
  throw "Provide -TextFile <path> or -Message <text>."
}

# --- Normalize punctuation & whitespace (do sequential assigns; no line continuations) ---
$txt = $txt -replace "[\u2010-\u2015]", "-"        # various dashes -> hyphen
$txt = $txt -replace "[\u2018\u2019\u2032]", "'"    # left/right single quote, prime -> '
$txt = $txt -replace "[\u201C\u201D\u2033]", '"'    # left/right double quote, double prime -> "
$txt = $txt -replace "[\u2026]", "..."              # ellipsis -> ...
$txt = $txt -replace "[\u00A0\u2000-\u200B]", " "   # NBSP + zero-widths -> space
$txt = $txt -replace "`r`n?", "`n"                  # normalize newlines to LF

# --- Discord helpers ---
function Send-DiscordChunk {
  param([string]$Content)
  $payload = @{ content = $Content }
  $json = $payload | ConvertTo-Json -Depth 5 -Compress
  try {
    Invoke-RestMethod -Uri $Webhook -Method Post -ContentType "application/json; charset=utf-8" -Body $json | Out-Null
  } catch {
    throw "Failed to post to Discord: $($_.Exception.Message)"
  }
}

# Discord hard limit: 2000 chars per message (content)
$MAX = 2000

# Wrap long/multiline content in code fences to keep tables aligned
$needsFence = ($txt.Contains("`n") -or $txt.Contains("│") -or $txt.Contains("|") -or $txt.Contains("—"))
if (-not $needsFence -and $txt.Length -le $MAX) {
  Send-DiscordChunk $txt
} else {
  # We’ll send in chunks with fenced blocks per chunk
  $nl = [Environment]::NewLine
  # Room for ```text\n + \n``` = ~10 chars
  $roomForFences = 10
  $remaining = $txt

  while ($remaining.Length -gt 0) {
    $take = [Math]::Min($remaining.Length, $MAX - $roomForFences)
    if ($take -lt 1) { $take = [Math]::Min($remaining.Length, $MAX) }

    $slice = $remaining.Substring(0, $take)

    # Try not to cut in the middle of a line if there’s more to send
    if ($take -lt $remaining.Length) {
      $lastNL = $slice.LastIndexOf("`n")
      if ($lastNL -gt 0) { $slice = $slice.Substring(0, $lastNL) }
    }

    if ([string]::IsNullOrEmpty($slice)) {
      $slice = $remaining.Substring(0, [Math]::Min($remaining.Length, $take))
    }

    $chunk = '```' + 'text' + "`n" + $slice + "`n" + '```'
    Send-DiscordChunk $chunk

    $remaining = $remaining.Substring($slice.Length).TrimStart()
    Start-Sleep -Milliseconds 250
  }
}

if ($TextFile) {
  Write-Output "Posted to Discord from file: $TextFile"
} else {
  Write-Output "Posted to Discord from -Message text"
}
