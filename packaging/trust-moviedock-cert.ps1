# 把片坞的自签名代码签名证书装进本机信任库（去掉“未知发布者”提示）
#
# 用法（二选一）：
#   1) 右键本文件 → “使用 PowerShell 运行”（会请求管理员权限）
#   2) 管理员 PowerShell 里执行：
#        powershell -ExecutionPolicy Bypass -File .\trust-moviedock-cert.ps1
#
# 做什么：把 moviedock-codesign.cer 导入
#   - 受信任的根证书颁发机构（LocalMachine\Root）
#   - 受信任的发布者（LocalMachine\TrustedPublisher）
# 之后 MovieDock.exe 的签名会被 Windows 认作有效，不再提示“未知发布者”。
# 卸载：certmgr.msc 里删除该证书，或运行本脚本加 -Remove 参数。

param(
  [string]$CertPath = (Join-Path $PSScriptRoot 'moviedock-codesign.cer'),
  [switch]$Remove,
  [switch]$CurrentUser
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $CertPath)) {
  Write-Host "找不到证书文件：$CertPath" -ForegroundColor Red
  exit 1
}

$cer = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 (Resolve-Path $CertPath)
Write-Host "证书主体：$($cer.Subject)"
Write-Host "SHA1 指纹：$($cer.Thumbprint)"
Write-Host "有效期至：$($cer.NotAfter)"

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin -and -not $CurrentUser) {
  Write-Host ""
  Write-Host "需要管理员权限才能导入“本机”证书库。正在尝试提权启动自身…" -ForegroundColor Yellow
  Start-Process powershell -Verb RunAs -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-CertPath', "`"$CertPath`""
  )
  exit 0
}

$stores = if ($CurrentUser) {
  @('Cert:\CurrentUser\Root', 'Cert:\CurrentUser\TrustedPublisher')
} else {
  @('Cert:\LocalMachine\Root', 'Cert:\LocalMachine\TrustedPublisher')
}

foreach ($store in $stores) {
  if ($Remove) {
    Get-ChildItem $store | Where-Object { $_.Thumbprint -eq $cer.Thumbprint } | Remove-Item -Force
    Write-Host "已从 $store 移除" -ForegroundColor Yellow
  } else {
    Import-Certificate -FilePath (Resolve-Path $CertPath) -CertStoreLocation $store | Out-Null
    Write-Host "已导入 $store" -ForegroundColor Green
  }
}

if (-not $Remove) {
  Write-Host ""
  Write-Host "完成。验证方式：在解压目录执行" -ForegroundColor Cyan
  Write-Host "  Get-AuthenticodeSignature .\MovieDock.exe | Format-List Status,SignerCertificate"
  Write-Host "Status 显示 Valid 即表示签名被本机认可。"
}
