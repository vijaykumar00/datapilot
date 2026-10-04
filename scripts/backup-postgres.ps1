<#
.SYNOPSIS
  Back up DataPilot: the PostgreSQL database and (with -WithObjects) the dataset object store.

.DESCRIPTION
  Postgres holds users, billing, the dataset registry and jobs; the datasets
  themselves (original uploads and every Parquet version) live in object
  storage.  A restorable backup needs both, taken at (about) the same time.

  -WithObjects copies the object store next to the database dump:
    * STORAGE_PROVIDER=s3|r2|minio  ->  `aws s3 sync s3://$S3_BUCKET` (AWS CLI required)
    * STORAGE_PROVIDER=local        ->  copy of $LOCAL_STORAGE_DIR\objects
  Without it, the script still succeeds but prints a warning and records in the
  manifest that dataset contents were NOT included (rely on bucket versioning /
  replication in that case).

  Every run writes datapilot-<stamp>.manifest.json describing what was captured.

.EXAMPLE
  .\scripts\backup-postgres.ps1 -BackupDir .\backups -WithObjects
#>
param(
  [string]$DatabaseUrl = $env:DATABASE_URL,
  [string]$BackupDir = ".\backups",
  [int]$RetentionDays = 14,
  [switch]$WithObjects,
  [string]$StorageProvider = $(if ($env:STORAGE_PROVIDER) { $env:STORAGE_PROVIDER } else { "local" }),
  [string]$Bucket = $env:S3_BUCKET,
  [string]$EndpointUrl = $env:S3_ENDPOINT_URL,
  [string]$LocalStorageDir = $env:LOCAL_STORAGE_DIR
)

$ErrorActionPreference = "Stop"

if (-not $DatabaseUrl) {
  throw "DATABASE_URL is required. Pass -DatabaseUrl or set the DATABASE_URL environment variable."
}
if (-not (Get-Command pg_dump -ErrorAction SilentlyContinue)) {
  throw "pg_dump was not found on PATH. Install PostgreSQL client tools before running backups."
}
# SQLAlchemy URLs carry a driver suffix that libpq does not understand.
$PgUrl = $DatabaseUrl -replace '^postgresql\+[a-z0-9_]+://', 'postgresql://'

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
$timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd-HHmmss")
$backupFile = Join-Path $BackupDir "datapilot-$timestamp.dump"
$checksumFile = "$backupFile.sha256"
$manifestFile = Join-Path $BackupDir "datapilot-$timestamp.manifest.json"

if (-not $env:PGCONNECT_TIMEOUT) { $env:PGCONNECT_TIMEOUT = "10" }
pg_dump --format=custom --no-owner --no-acl --file "$backupFile" "$PgUrl"
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed with exit code $LASTEXITCODE." }

# Verify the archive is readable before declaring success.
pg_restore --list "$backupFile" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Backup verification (pg_restore --list) failed with exit code $LASTEXITCODE." }

$hash = Get-FileHash -Algorithm SHA256 -Path $backupFile
"$($hash.Hash.ToLower())  $(Split-Path -Leaf $backupFile)" | Set-Content -Encoding ascii -Path $checksumFile

$provider = $StorageProvider.ToLower()
$objects = [ordered]@{ included = $false; provider = $provider; location = $null; path = $null; files = 0 }

if ($WithObjects) {
  $objectsDir = Join-Path $BackupDir "objects-$timestamp"
  if ($provider -in @("s3", "r2", "minio")) {
    if (-not $Bucket) { throw "S3_BUCKET (or -Bucket) is required with -WithObjects for STORAGE_PROVIDER=$provider." }
    if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
      throw "The AWS CLI ('aws') was not found on PATH; it is required to back up the object store."
    }
    $awsArgs = @()
    if ($EndpointUrl) { $awsArgs += @("--endpoint-url", $EndpointUrl) }
    $awsArgs += @("s3", "sync", "s3://$Bucket", $objectsDir, "--only-show-errors")
    & aws @awsArgs
    if ($LASTEXITCODE -ne 0) { throw "aws s3 sync failed with exit code $LASTEXITCODE." }
    $objects.location = "s3://$Bucket"
  }
  elseif ($provider -eq "local") {
    $source = if ($LocalStorageDir) { Join-Path $LocalStorageDir "objects" } else { Join-Path (Join-Path $PSScriptRoot "..\backend\uploads") "objects" }
    if (-not (Test-Path -LiteralPath $source)) { throw "Local object store not found: $source" }
    New-Item -ItemType Directory -Force -Path $objectsDir | Out-Null
    Copy-Item -Path (Join-Path $source "*") -Destination $objectsDir -Recurse -Force
    $objects.location = (Resolve-Path $source).Path
  }
  else {
    throw "Unsupported STORAGE_PROVIDER '$provider' for -WithObjects."
  }
  if (-not (Test-Path -LiteralPath $objectsDir)) { New-Item -ItemType Directory -Force -Path $objectsDir | Out-Null }
  $objects.included = $true
  $objects.path = (Resolve-Path $objectsDir).Path
  $objects.files = @(Get-ChildItem -LiteralPath $objectsDir -Recurse -File).Count
}
else {
  Write-Warning ("Dataset contents in object storage ($provider) were NOT backed up. " +
    "Re-run with -WithObjects, or make sure bucket versioning/replication is enabled.")
}

[ordered]@{
  created_utc = $timestamp
  database    = [ordered]@{ included = $true; file = (Split-Path -Leaf $backupFile); sha256 = $hash.Hash.ToLower() }
  objects     = $objects
} | ConvertTo-Json -Depth 4 | Set-Content -Encoding utf8 -Path $manifestFile

$cutoff = (Get-Date).AddDays(-1 * $RetentionDays)
Get-ChildItem -Path $BackupDir -Filter "datapilot-*" -File |
  Where-Object { $_.LastWriteTime -lt $cutoff } |
  Remove-Item -Force
Get-ChildItem -Path $BackupDir -Filter "objects-*" -Directory |
  Where-Object { $_.LastWriteTime -lt $cutoff } |
  Remove-Item -Recurse -Force

Write-Output "Backup created: $backupFile"
Write-Output "Checksum: $checksumFile"
Write-Output "Manifest: $manifestFile"
if ($objects.included) { Write-Output "Objects: $($objects.files) file(s) in $($objects.path)" }
