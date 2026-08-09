param(
  [string]$DatabaseUrl = $env:DATABASE_URL,
  [string]$BackupDir = ".\backups",
  [int]$RetentionDays = 14
)

$ErrorActionPreference = "Stop"

if (-not $DatabaseUrl) {
  throw "DATABASE_URL is required. Pass -DatabaseUrl or set the DATABASE_URL environment variable."
}

if (-not (Get-Command pg_dump -ErrorAction SilentlyContinue)) {
  throw "pg_dump was not found on PATH. Install PostgreSQL client tools before running backups."
}

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupFile = Join-Path $BackupDir "datapilot-$timestamp.dump"
$checksumFile = "$backupFile.sha256"

if (-not $env:PGCONNECT_TIMEOUT) {
  $env:PGCONNECT_TIMEOUT = "10"
}
pg_dump --format=custom --no-owner --no-acl --file "$backupFile" "$DatabaseUrl"
if ($LASTEXITCODE -ne 0) {
  throw "pg_dump failed with exit code $LASTEXITCODE."
}

$hash = Get-FileHash -Algorithm SHA256 -Path $backupFile
"$($hash.Hash)  $(Split-Path -Leaf $backupFile)" | Set-Content -Encoding ascii -Path $checksumFile

$cutoff = (Get-Date).AddDays(-1 * $RetentionDays)
Get-ChildItem -Path $BackupDir -Filter "datapilot-*.dump*" |
  Where-Object { $_.LastWriteTime -lt $cutoff } |
  Remove-Item -Force

Write-Output "Backup created: $backupFile"
Write-Output "Checksum: $checksumFile"
