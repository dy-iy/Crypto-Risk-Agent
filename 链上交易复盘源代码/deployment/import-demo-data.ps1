param(
    [string]$ComposeDirectory = "."
)

$ErrorActionPreference = "Stop"

$dataDirectory = Join-Path $PSScriptRoot "demo-data"
$postgresDump = Join-Path $dataDirectory "attackpilot-postgres.dump"
$redisArchive = Join-Path $dataDirectory "attackpilot-redis-data.tar.gz"

if (-not (Test-Path -LiteralPath $postgresDump)) {
    throw "Missing PostgreSQL data file: $postgresDump"
}
if (-not (Test-Path -LiteralPath $redisArchive)) {
    throw "Missing Redis data file: $redisArchive"
}

Push-Location $ComposeDirectory
try {
    Write-Host "Starting PostgreSQL and Redis containers..."
    docker compose up -d postgres redis

    Write-Host "Waiting for PostgreSQL..."
    $postgresReady = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        docker exec tracepilot_postgres pg_isready -U tracepilot_user -d tracepilot *> $null
        if ($LASTEXITCODE -eq 0) {
            $postgresReady = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $postgresReady) {
        throw "PostgreSQL did not become ready in time."
    }

    docker compose stop backend

    Write-Host "Restoring PostgreSQL tasks and reports..."
    docker cp $postgresDump tracepilot_postgres:/tmp/attackpilot-postgres.dump
    docker exec tracepilot_postgres pg_restore `
        -U tracepilot_user `
        -d tracepilot `
        --clean `
        --if-exists `
        --no-owner `
        --no-privileges `
        --exit-on-error `
        /tmp/attackpilot-postgres.dump

    Write-Host "Restoring Redis logs..."
    $redisVolume = docker inspect tracepilot_redis --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Name}}{{end}}{{end}}'
    if (-not $redisVolume) {
        throw "Could not find the /data volume mounted by tracepilot_redis."
    }

    docker compose stop redis
    $dockerDataDirectory = $dataDirectory.Replace("\", "/")
    docker run --rm `
        -v "$($redisVolume):/data" `
        -v "$($dockerDataDirectory):/backup:ro" `
        redis:7-alpine `
        sh -c "rm -rf /data/* && tar xzf /backup/attackpilot-redis-data.tar.gz -C /data"

    Write-Host "Restarting services..."
    docker compose up -d redis backend

    Write-Host "Demo data import completed."
}
finally {
    Pop-Location
}
