$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

docker info *> $null
if ($LASTEXITCODE -eq 0) {
    docker compose --project-directory $repoRoot down
    exit $LASTEXITCODE
}

$wslRoot = (wsl.exe -d Ubuntu -- wslpath -a $repoRoot).Trim()
wsl.exe -d Ubuntu -u root --cd $wslRoot docker compose down
exit $LASTEXITCODE
