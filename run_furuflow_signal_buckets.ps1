Set-Location "C:\Users\andro\Projects\yield-flow-engine"

Write-Host ""
Write-Host "==============================="
Write-Host "FURUFLOW MODERATE SIGNALS"
Write-Host "==============================="
& .\run_furuflow_moderate_signals.ps1

Write-Host ""
Write-Host "==============================="
Write-Host "FURUFLOW DEGEN SIGNALS"
Write-Host "==============================="
& .\run_furuflow_degen_signals.ps1
