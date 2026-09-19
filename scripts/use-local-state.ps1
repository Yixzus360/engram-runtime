$ErrorActionPreference = "Stop"

$localPort = 5439
$directHost = "localhost"
$reachable = Test-NetConnection -ComputerName $directHost -Port $localPort -InformationLevel Quiet

if (-not $reachable) {
    $directHost = (wsl.exe -d Ubuntu -- hostname -I).Trim().Split(' ')[0]
}

if (-not $directHost) {
    throw "State Core host could not be resolved. Run scripts/up.ps1 first."
}

$connection = "postgresql://engram:engram@$directHost`:$localPort/engram"
$env:ENGRAM_DATABASE_URL = $connection
$env:ENGRAM_TEST_DATABASE_URL = $connection
Write-Host "State Core environment selected at $directHost`:$localPort."

