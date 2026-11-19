<#
把本项目推送到你自己的 GitHub 仓库（Windows PowerShell 版）。

前提：本地仓库已由 git init + 首次 commit 建好（本脚本可直接用于新建的仓库）。
用法（在项目根目录执行）：

    powershell -ExecutionPolicy Bypass -File scripts\push_to_github.ps1 `
        -RepoUrl https://github.com/<你的账号>/medical-kg-qa.git `
        -GitHubName "<你的账号>" -GitHubEmail "<注册邮箱>"

加 -GitHubName / -GitHubEmail 时，会把首次提交的作者改成你自己（git commit --amend --reset-author）。
只想看会执行哪些命令、不真正上传：加 -DryRun。
如果本地提交被改写过（amend 过作者），远程会拒绝普通 push，此时加 -Force
（实际用的是 --force-with-lease：远程被别人动过就仍然拒绝，比 --force 安全）。

脚本会自动找 git：优先 PATH 里的 git，其次用 GitHub Copilot 桌面版自带的 git
（%LOCALAPPDATA%\github-copilot-git-*\cmd\git.exe），都不存在时提示先安装。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$RepoUrl,

    [string]$GitHubName,
    [string]$GitHubEmail,
    [string]$Git,

    [switch]$Force,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

function Resolve-Git {
    param([string]$Explicit)
    if ($Explicit) {
        if (Test-Path $Explicit) { return $Explicit }
        throw "指定的 git 不存在：$Explicit"
    }
    $cmd = Get-Command git -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = Get-ChildItem "$env:LOCALAPPDATA\github-copilot-git-*\cmd\git.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName -Descending
    if ($candidates) { return $candidates[0].FullName }
    throw "没找到 git。先执行：winget install --id Git.Git -e --source winget，装完重开终端再运行本脚本。"
}

function Invoke-Git {
    param([string[]]$Arguments, [switch]$AllowFail)
    Write-Host ("  git " + ($Arguments -join " ")) -ForegroundColor DarkGray
    if ($DryRun) { return }
    & $script:git -C $script:root @Arguments
    if ($LASTEXITCODE -ne 0 -and -not $AllowFail) {
        throw "git $($Arguments[0]) 失败（退出码 $LASTEXITCODE）"
    }
}

if ($RepoUrl -notmatch '^https://github\.com/[\w.-]+/[\w.-]+?(\.git)?/?$' -and
    $RepoUrl -notmatch '^git@github\.com:[\w.-]+/[\w.-]+?(\.git)?$') {
    throw "仓库地址看起来不对：$RepoUrl`n应为 https://github.com/<账号>/<仓库名>.git"
}
if ($RepoUrl -notmatch '\.git$') { $RepoUrl = $RepoUrl.TrimEnd('/') + '.git' }

$script:git = Resolve-Git -Explicit $Git
$script:root = $root

Write-Host "仓库目录：$root" -ForegroundColor Cyan
Write-Host "使用的 git：$($script:git)" -ForegroundColor DarkGray
& $script:git -C $root rev-parse --git-dir | Out-Null
if ($LASTEXITCODE -ne 0) { throw "这里还不是 git 仓库，请先在项目根目录执行 git init。" }

# 1) 可选：修正作者身份（首次提交目前是占位身份）
if ($GitHubName -or $GitHubEmail) {
    if (-not ($GitHubName -and $GitHubEmail)) {
        throw "如果要改作者，-GitHubName 和 -GitHubEmail 请一起提供。"
    }
    Write-Host "`n[1/4] 设置提交身份并修正首次提交的作者" -ForegroundColor Cyan
    Invoke-Git -Arguments @("config", "--local", "user.name", $GitHubName)
    Invoke-Git -Arguments @("config", "--local", "user.email", $GitHubEmail)
    Invoke-Git -Arguments @("commit", "--amend", "--reset-author", "--no-edit")
}
else {
    Write-Host "`n[1/4] 跳过作者修正（未提供 -GitHubName / -GitHubEmail）" -ForegroundColor Yellow
}

# 2) 配远程仓库
Write-Host "`n[2/4] 配置远程仓库 origin" -ForegroundColor Cyan
$existing = & $script:git -C $root remote 2>$null
if ($existing -contains "origin") {
    Invoke-Git -Arguments @("remote", "set-url", "origin", $RepoUrl)
}
else {
    Invoke-Git -Arguments @("remote", "add", "origin", $RepoUrl)
}

# 3) 推之前再确认一次没有密钥/缓存
Write-Host "`n[3/4] 安全检查：确认没有 .env、__pycache__、日志" -ForegroundColor Cyan
$tracked = & $script:git -C $root ls-files
$risky = $tracked | Where-Object { $_ -match '(^|/)\.env$|__pycache__|\.pyc$' }
if ($risky) {
    $risky | ForEach-Object { Write-Host "  可疑文件：$_" -ForegroundColor Red }
    throw "发现不该提交的文件，先把它加进 .gitignore 并 git rm --cached 再重试。"
}
Write-Host "  通过：$($tracked.Count) 个文件，无密钥/缓存" -ForegroundColor Green

# 4) 推送
Write-Host "`n[4/4] 推送到 GitHub" -ForegroundColor Cyan
if (-not $DryRun) {
    Write-Host "  （首次会弹出登录窗口，选 Sign in with your browser，浏览器里点 Authorize）" -ForegroundColor Yellow
}
if ($Force) {
    Invoke-Git -Arguments @("push", "--force-with-lease", "-u", "origin", "main")
}
else {
    Invoke-Git -Arguments @("push", "-u", "origin", "main")
}

$web = $RepoUrl -replace '\.git$', ''
if ($DryRun) {
    Write-Host "`nDryRun 完成，以上命令未真正执行。" -ForegroundColor Yellow
}
else {
    Write-Host "`n完成。仓库地址：$web" -ForegroundColor Green
    Write-Host "刷新这个页面，应能看到 docs/ 下的报告与截图目录。" -ForegroundColor Green
}