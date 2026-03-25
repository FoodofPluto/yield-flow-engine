Set-Location "C:\Users\andro\Projects\yield-flow-engine"

# Required
$env:TELEGRAM_BOT_TOKEN="YOUR_BOT_TOKEN"
$env:TELEGRAM_CHAT_ID="-1003736270024"
$env:TELEGRAM_ENABLE_POWERSHELL_FALLBACK="true"
# Optional only if your Python SSL stack is failing:
# $env:TELEGRAM_DISABLE_SSL_VERIFY="true"

# Signal filters
$env:FURUFLOW_SIGNAL_SOURCE="defillama"
$env:FURUFLOW_SIGNAL_MIN_TVL="1000000"
$env:FURUFLOW_SIGNAL_MIN_APY="8"
$env:FURUFLOW_SIGNAL_MAX_APY="200"
$env:FURUFLOW_SIGNAL_TOP_N="5"
$env:FURUFLOW_SIGNAL_MAX_POSTS="3"
$env:FURUFLOW_SIGNAL_CHAINS="base,arbitrum,optimism,polygon,ethereum"
$env:FURUFLOW_SIGNAL_STABLECOIN_ONLY="false"
$env:FURUFLOW_SIGNAL_ALLOW_REPOSTS="false"
$env:FURUFLOW_SIGNAL_DEDUPE_HOURS="24"
$env:FURUFLOW_SIGNAL_DRY_RUN="false"

python .\post_real_signals.py
