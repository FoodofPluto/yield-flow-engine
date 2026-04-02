Set-Location "C:\Users\andro\Projects\yield-flow-engine"

Write-Host ""
Write-Host "==============================="
Write-Host "FURUFLOW STRONG SIGNALS"
Write-Host "==============================="

$env:TELEGRAM_CHAT_ID = "-1003736270024"
$env:TELEGRAM_ENABLE_POWERSHELL_FALLBACK = "true"

# Signal filters
$env:FURUFLOW_SIGNAL_SOURCE = "defillama"
$env:FURUFLOW_SIGNAL_MIN_TVL = "750000"
$env:FURUFLOW_SIGNAL_MIN_APY = "8"
$env:FURUFLOW_SIGNAL_MAX_APY = "200"
$env:FURUFLOW_SIGNAL_MIN_STRENGTH = "65"
$env:FURUFLOW_SIGNAL_MAX_STRENGTH = "100"
$env:FURUFLOW_SIGNAL_TOP_N = "8"
$env:FURUFLOW_SIGNAL_SCAN_DEPTH = "400"
$env:FURUFLOW_SIGNAL_MAX_POSTS = "4"
$env:FURUFLOW_SIGNAL_CHAINS = "base,arbitrum,optimism,polygon,ethereum"
$env:FURUFLOW_SIGNAL_STABLECOIN_ONLY = "false"
$env:FURUFLOW_SIGNAL_ALLOW_REPOSTS = "false"
$env:FURUFLOW_SIGNAL_DEDUPE_HOURS = "6"
$env:FURUFLOW_SIGNAL_DRY_RUN = "false"
$env:FURUFLOW_SIGNAL_DEBUG = "true"
$env:FURUFLOW_POST_FREE_SIGNALS = "true"
$env:FURUFLOW_POST_PRO_SIGNALS = "true"
$env:FURUFLOW_POSTED_SIGNALS_FILE = "posted_signals_strong.json"

python .\post_real_signals.py
