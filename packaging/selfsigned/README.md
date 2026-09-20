# 自签名代码签名证书（公开部分）

本目录只放**公开证书**：`moviedock-codesign.cer`（随 Release 与 zip 分发，供用户导入信任）。
私钥（`.key`）与 PKCS#12（`.pfx`）以及口令**不入库**，只保存在本地受保护目录 + GitHub Secrets。

- 签发者 / 主体：`CN=MovieDock Self-Signed (WANGjia8613)`，有效期 10 年
- SHA1 指纹：`92A20205A84C867586BD8E1671D7B2B9A31D2BCC`
- 用途扩展：`Code Signing`（critical）、`CA:TRUE`（便于作为受信任根导入）

## 用户怎么用（去掉“未知发布者”提示）

右键 `trust-moviedock-cert.ps1` → 「使用 PowerShell 运行」（会请求管理员权限），
它会把证书导入 `LocalMachine\Root` 与 `LocalMachine\TrustedPublisher`。
验证：`Get-AuthenticodeSignature .\MovieDock.exe` → `Status: Valid`。

## 维护者：换证书

```bash
scripts/make_signing_cert.sh                 # 生成新证书并更新本目录的 .cer
gh secret set WIN_CSC_PFX_B64     --body "$(base64 -w0 ~/.moviedock-signing/moviedock-codesign.pfx)"
gh secret set WIN_CSC_PFX_PASSWORD --body "$(cat ~/.moviedock-signing/pfx-password.txt)"
gh secret set WIN_CSC_THUMBPRINT   --body "$(cat ~/.moviedock-signing/thumbprint.txt)"
```
换证书后需要重新发版，并让用户重新导入新的 `.cer`。

## 说明（预期管理）

自签名证书能做到：Windows 认可签名有效、不再提示“未知发布者”。
它**不能**消除 SmartScreen 的“下载信誉”提示 —— 那需要商业代码签名证书（OV/EV）或
微软的 Azure Trusted Signing（个人可申请，约 $9.99/月，CI 有官方集成）。
