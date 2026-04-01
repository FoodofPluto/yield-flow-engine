Set-Location "C:\Users\andro\Projects\yield-flow-engine"

Write-Host ""
Write-Host "==============================="
Write-Host "FURUFLOW DEGEN SIGNALS"
Write-Host "==============================="

# Telegram
$env:TELEGRAM_BOT_TOKEN = $env:TELEGRAM_BOT_TOKEN
$env:TELEGRAM_CHAT_ID = "-1003736270024"
$env:TELEGRAM_ENABLE_POWERSHELL_FALLBACK = "true"

# Signal source
$env:FURUFLOW_SIGNAL_SOURCE = "defillama"

# Degen bucket tuning
$env:FURUFLOW_SIGNAL_MIN_TVL = "500000"
$env:FURUFLOW_SIGNAL_MIN_APY = "40"
$env:FURUFLOW_SIGNAL_MAX_APY = "200"
$env:FURUFLOW_SIGNAL_MIN_RISK = "5"
$env:FURUFLOW_SIGNAL_MAX_RISK = "6"
$env:FURUFLOW_SIGNAL_MIN_STRENGTH = "64"
$env:FURUFLOW_SIGNAL_MAX_STRENGTH = "100"
$env:FURUFLOW_SIGNAL_TOP_N = "5"
$env:FURUFLOW_SIGNAL_SCAN_DEPTH = "250"
$env:FURUFLOW_SIGNAL_STABLECOIN_ONLY = "false"
$env:FURUFLOW_SIGNAL_CHAINS = "ethereum,base,arbitrum,optimism,polygon"

# Posting behavior
$env:FURUFLOW_POST_FREE_SIGNALS = "true"
$env:FURUFLOW_POST_PRO_SIGNALS = "true"
$env:FURUFLOW_SIGNAL_ALLOW_REPOSTS = "false"
$env:FURUFLOW_SIGNAL_DEDUPE_HOURS = "24"
$env:FURUFLOW_SIGNAL_MAX_POSTS = "3"
$env:FURUFLOW_SIGNAL_DRY_RUN = "false"
$env:FURUFLOW_SIGNAL_DEBUG = "true"

# Separate dedupe file for this bucket
$env:FURUFLOW_POSTED_SIGNALS_FILE = "posted_signals_degen.json"

python .\post_real_signals.py