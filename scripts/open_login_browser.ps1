param(
    [ValidateSet("xianyu", "taobao")]
    [string]$Platform = "xianyu",

    [string]$Account = "xianyu_a",

    [ValidateSet("msedge", "chrome")]
    [string]$Channel = "msedge",

    [string]$UserDataDir = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $UserDataDir) {
    $UserDataDir = Join-Path $projectRoot "data\browser_profiles\$Account"
}

New-Item -ItemType Directory -Force -Path $UserDataDir | Out-Null

$url = switch ($Platform) {
    "xianyu" { "https://www.goofish.com/" }
    "taobao" { "https://www.taobao.com/" }
}

$exe = switch ($Channel) {
    "msedge" { "msedge.exe" }
    "chrome" { "chrome.exe" }
}

Write-Host "Opening normal browser for manual login..."
Write-Host "Platform: $Platform"
Write-Host "Account: $Account"
Write-Host "Profile: $UserDataDir"
Write-Host ""
Write-Host "After login succeeds, close this browser window before running the automation."

Start-Process $exe -ArgumentList @(
    "--user-data-dir=$UserDataDir",
    "--no-first-run",
    $url
)
