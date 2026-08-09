param(
  [Parameter(Mandatory = $true)]
  [string]$BackupFile,
  [string]$DatabaseUrl = $env:DATABASE_URL,
  [switch]$VerifyOnly
)

$ErrorActionPreference = "Stop"

if (-not $DatabaseUrl) {
  throw "DATABASE_URL is required. Pass -DatabaseUrl or set the DATABASE_URL environment variable."
}

if (-not (Test-Path -LiteralPath $BackupFile)) {
  throw "Backup file not found: $BackupFile"
}

if (-not (Get-Command pg_restore -ErrorAction SilentlyContinue)) {
  throw "pg_restore was not found on PATH. Install PostgreSQL client tools before running restores."
}

$checksumFile = "$BackupFile.sha256"
if (Test-Path -LiteralPath $checksumFile) {
  $expected = (Get-Content -Path $checksumFile -TotalCount 1).Split(" ")[0].Trim()
  $actual = (Get-FileHash -Algorithm SHA256 -Path $BackupFile).Hash
  if ($expected -and $actual -ne $expected) {
    throw "Checksum mismatch for $BackupFile."
  }
}

pg_restore --list "$BackupFile" | Out-Null
if ($LASTEXITCODE -ne 0) {
  throw "Backup verification failed with exit code $LASTEXITCODE."
}

if ($VerifyOnly) {
  Write-Output "Backup verified: $BackupFile"
  return
}

pg_restore --clean --if-exists --no-owner --no-acl --dbname "$DatabaseUrl" "$BackupFile"
if ($LASTEXITCODE -ne 0) {
  throw "Restore failed with exit code $LASTEXITCODE."
}

Write-Output "Restore completed from: $BackupFile"
