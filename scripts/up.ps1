$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

docker info *> $null
if ($LASTEXITCODE -eq 0) {
    docker compose --project-directory $repoRoot up -d --wait
    exit $LASTEXITCODE
}

$wslRoot = (wsl.exe -d Ubuntu -- wslpath -a $repoRoot).Trim()
if (-not $wslRoot) {
    throw "No usable Docker engine was found."
}
wsl.exe -d Ubuntu -u root --cd $wslRoot docker compose up -d --wait
exit $LASTEXITCODE
