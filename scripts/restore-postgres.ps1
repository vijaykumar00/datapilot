<#
.SYNOPSIS
  Restore a DataPilot backup created by backup-postgres.ps1 / backup-postgres.sh.

.DESCRIPTION
  Verifies the checksum and archive, then (unless -VerifyOnly) restores the
  database.  -ObjectsDir restores the dataset object store from an
  objects-<stamp> folder of the same backup (S3 via `aws s3 sync`, or a copy
  into $LOCAL_STORAGE_DIR\objects).  Restore the database and objects from the
  SAME backup; stop the API and workers first, then run `alembic upgrade head`.

.EXAMPLE
  .\scripts\restore-postgres.ps1 -BackupFile .\backups\datapilot-20261003-101500.dump -VerifyOnly
  .\scripts\restore-postgres.ps1 -BackupFile .\backups\datapilot-20261003-101500.dump -ObjectsDir .\backups\objects-20261003-101500 -Yes
#>
param(
  [Parameter(Mandatory = $true)]
  [string]$BackupFile,
  [string]$DatabaseUrl = $env:DATABASE_URL,
  [string]$ObjectsDir,
  [switch]$VerifyOnly,
  [switch]$Yes,
  [string]$StorageProvider = $(if ($env:STORAGE_PROVIDER) { $env:STORAGE_PROVIDER } else { "local" }),
  [string]$Bucket = $env:S3_BUCKET,
  [string]$EndpointUrl = $env:S3_ENDPOINT_URL,
  [string]$LocalStorageDir = $env:LOCAL_STORAGE_DIR
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $BackupFile)) { throw "Backup file not found: $BackupFile" }
if (-not (Get-Command pg_restore -ErrorAction SilentlyContinue)) {
  throw "pg_restore was not found on PATH. Install PostgreSQL client tools before running restores."
}

$checksumFile = "$BackupFile.sha256"
if (Test-Path -LiteralPath $checksumFile) {
  $expected = (Get-Content -Path $checksumFile -TotalCount 1).Split(" ")[0].Trim()
  $actual = (Get-FileHash -Algorithm SHA256 -Path $BackupFile).Hash
  if ($expected -and $actual -ne $expected) { throw "Checksum mismatch for $BackupFile." }
}
pg_restore --list "$BackupFile" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Backup verification failed with exit code $LASTEXITCODE." }
if ($ObjectsDir -and -not (Test-Path -LiteralPath $ObjectsDir)) { throw "Objects folder not found: $ObjectsDir" }

if ($VerifyOnly) {
  Write-Output "Backup verified: $BackupFile"
  return
}
if (-not $Yes) { throw "Refusing to restore without -Yes (existing database objects are dropped and replaced)." }
if (-not $DatabaseUrl) {
  throw "DATABASE_URL is required. Pass -DatabaseUrl or set the DATABASE_URL environment variable."
}
$PgUrl = $DatabaseUrl -replace '^postgresql\+[a-z0-9_]+://', 'postgresql://'

pg_restore --clean --if-exists --no-owner --no-acl --exit-on-error --single-transaction --dbname "$PgUrl" "$BackupFile"
if ($LASTEXITCODE -ne 0) { throw "Restore failed with exit code $LASTEXITCODE." }
Write-Output "Database restored from: $BackupFile"

if ($ObjectsDir) {
  $provider = $StorageProvider.ToLower()
  if ($provider -in @("s3", "r2", "minio")) {
    if (-not $Bucket) { throw "S3_BUCKET (or -Bucket) is required to restore objects for STORAGE_PROVIDER=$provider." }
    if (-not (Get-Command aws -ErrorAction SilentlyContinue)) { throw "The AWS CLI ('aws') was not found on PATH." }
    $awsArgs = @()
    if ($EndpointUrl) { $awsArgs += @("--endpoint-url", $EndpointUrl) }
    $awsArgs += @("s3", "sync", $ObjectsDir, "s3://$Bucket", "--only-show-errors")
    & aws @awsArgs
    if ($LASTEXITCODE -ne 0) { throw "aws s3 sync failed with exit code $LASTEXITCODE." }
  }
  elseif ($provider -eq "local") {
    $target = if ($LocalStorageDir) { Join-Path $LocalStorageDir "objects" } else { Join-Path (Join-Path $PSScriptRoot "..\backend\uploads") "objects" }
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    Copy-Item -Path (Join-Path $ObjectsDir "*") -Destination $target -Recurse -Force
  }
  else {
    throw "Unsupported STORAGE_PROVIDER '$provider' for object restore."
  }
  Write-Output "Objects restored from: $ObjectsDir"
}
else {
  Write-Warning "Only the database was restored. Restore dataset objects from the same backup (-ObjectsDir) unless the bucket is intact."
}
Write-Output "Next: run 'alembic upgrade head', then start the API and workers."
