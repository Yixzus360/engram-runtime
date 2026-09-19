$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$dockerDesktop = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
$needsWslKeepAlive = -not $dockerDesktop

& "$PSScriptRoot\up.ps1"
. "$PSScriptRoot\use-local-state.ps1"

$wslKeepAlive = $null
if ($needsWslKeepAlive) {
    $wslKeepAlive = Start-Process -FilePath "wsl.exe" `
        -ArgumentList @("-d", "Ubuntu", "--exec", "sleep", "infinity") `
        -WindowStyle Hidden -PassThru
}

try {
    uv run uvicorn engram_runtime.web:app --host 127.0.0.1 --port 8765
}
finally {
    if ($wslKeepAlive -and -not $wslKeepAlive.HasExited) {
        Stop-Process -Id $wslKeepAlive.Id
    }
}
