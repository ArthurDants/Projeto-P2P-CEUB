$scriptPath = (& python -c "import sysconfig,os;print(sysconfig.get_path('scripts'))")
if ($LASTEXITCODE -ne 0) { Write-Output 'Python error determining scripts path'; exit 1 }
if (-not $scriptPath) { Write-Output 'Could not determine scripts path'; exit 1 }
$userPath = [Environment]::GetEnvironmentVariable('PATH','User')
if ($userPath -notlike "*$scriptPath*") {
    [Environment]::SetEnvironmentVariable('PATH', "$scriptPath;$userPath", 'User')
    Write-Output "Added $scriptPath to User PATH"
} else {
    Write-Output "User PATH already contains scripts path"
}
$env:PATH = "$scriptPath;$env:PATH"
Write-Output "Session PATH updated: $scriptPath added"
Write-Output "Restart existing shells to pick up User PATH changes."