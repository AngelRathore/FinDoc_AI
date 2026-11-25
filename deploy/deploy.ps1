# Runs on YOUR Windows PC. Copies the project to the AWS server and starts it.
# Use the same command for the first deploy and for every update.
#
#   .\deploy\deploy.ps1 -Server 1.2.3.4 -Key "$HOME\Downloads\findoc-key.pem"
param(
    [Parameter(Mandatory = $true)][string]$Server,
    [Parameter(Mandatory = $true)][string]$Key,
    [string]$User = "ubuntu"
)
$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $Key)) { throw "Key file not found: $Key" }
$Key = (Resolve-Path -LiteralPath $Key).Path
$root = Split-Path -Parent $PSScriptRoot
$target = "$User@$Server"
$ssh = @("-i", $Key, "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15")

function Assert-LastExit([string]$what) {
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)." }
}

# SSH refuses a key that other Windows accounts can read.
icacls $Key /inheritance:r /grant:r "$($env:USERNAME):(R)" | Out-Null
Assert-LastExit "Locking down the key file"

Write-Host "==> Packing the project" -ForegroundColor Cyan
$list = [IO.Path]::GetTempFileName()
$archive = Join-Path ([IO.Path]::GetTempPath()) "findoc-deploy.tgz"
try {
    # Tracked files plus new ones, minus anything .gitignore excludes (such as .env).
    $files = git -C $root -c core.quotepath=off ls-files --cached --others --exclude-standard
    Assert-LastExit "Listing project files"
    $files = $files | Where-Object { Test-Path -LiteralPath (Join-Path $root $_) -PathType Leaf }
    [IO.File]::WriteAllLines($list, [string[]]$files, (New-Object Text.UTF8Encoding($false)))
    & "$env:SystemRoot\System32\tar.exe" -czf $archive -C $root -T $list
    Assert-LastExit "Packing"

    Write-Host "==> Copying it to $Server" -ForegroundColor Cyan
    scp @ssh $archive "${target}:findoc-deploy.tgz"
    Assert-LastExit "Copying to the server"

    Write-Host "==> Setting it up on the server" -ForegroundColor Cyan
    # Settings live in ~/findoc.env, outside this folder, so replacing it is safe.
    $remote = "rm -rf ~/findoc && mkdir ~/findoc && tar -xzf ~/findoc-deploy.tgz -C ~/findoc && rm ~/findoc-deploy.tgz && bash ~/findoc/deploy/setup.sh"
    ssh @ssh -t $target $remote
    Assert-LastExit "Setup on the server"
}
finally {
    Remove-Item -LiteralPath $list, $archive -Force -ErrorAction SilentlyContinue
}
