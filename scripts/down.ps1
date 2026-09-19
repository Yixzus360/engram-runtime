$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

docker info *> $null
if ($LASTEXITCODE -eq 0) {
    docker compose --project-directory $repoRoot down
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed to stop State Core." }
    return
}

$wslRoot = (wsl.exe -d Ubuntu -- wslpath -a $repoRoot).Trim()
wsl.exe -d Ubuntu -u root --cd $wslRoot docker compose down
if ($LASTEXITCODE -ne 0) { throw "WSL Docker Compose failed to stop State Core." }
