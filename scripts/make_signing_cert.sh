#!/usr/bin/env bash
# 生成/更新片坞的**自签名代码签名证书**（只在需要换证书时跑一次）。
#
# 产物：
#   $OUT/moviedock-codesign.pem  （证书，公开）
#   $OUT/moviedock-codesign.key  （私钥，勿外泄）
#   $OUT/moviedock-codesign.pfx  （带私钥的 PKCS#12，供 CI 签名用）
#   $OUT/pfx-password.txt        （pfx 口令）
#   $OUT/thumbprint.txt          （SHA1 指纹，无冒号大写，供 CI 校验）
#   仓库内 packaging/selfsigned/moviedock-codesign.cer（公开证书，随包分发，供用户导入信任）
#
# 生成后需要把 pfx + 口令 + 指纹写进 GitHub Secrets：
#   gh secret set WIN_CSC_PFX_B64 --body "$(base64 -w0 moviedock-codesign.pfx)"
#   gh secret set WIN_CSC_PFX_PASSWORD --body "$(cat pfx-password.txt)"
#   gh secret set WIN_CSC_THUMBPRINT --body "$(cat thumbprint.txt)"
#
# 注意：换证书后，用户需要重新导入新的 .cer 才会继续认作可信发布者。
set -euo pipefail

OUT="${1:-$HOME/.moviedock-signing}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CN="${CN:-MovieDock Self-Signed}"
YEARS="${YEARS:-10}"

mkdir -p "$OUT" "$REPO_ROOT/packaging/selfsigned"
chmod 700 "$OUT"

if [[ ! -f "$OUT/pfx-password.txt" ]]; then
  openssl rand -base64 24 | tr -d '/+=' | head -c 24 > "$OUT/pfx-password.txt"
  chmod 600 "$OUT/pfx-password.txt"
fi
PW="$(cat "$OUT/pfx-password.txt")"

openssl req -x509 -newkey rsa:4096 -sha256 -days $((YEARS * 365)) -nodes \
  -keyout "$OUT/moviedock-codesign.key" -out "$OUT/moviedock-codesign.pem" \
  -subj "/C=CN/O=MovieDock/CN=$CN" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,digitalSignature,keyCertSign,cRLSign" \
  -addext "extendedKeyUsage=critical,codeSigning" \
  -addext "subjectKeyIdentifier=hash" 2>/dev/null

openssl pkcs12 -export -out "$OUT/moviedock-codesign.pfx" \
  -inkey "$OUT/moviedock-codesign.key" -in "$OUT/moviedock-codesign.pem" \
  -passout "pass:$PW" -name "MovieDock Code Signing"

openssl x509 -in "$OUT/moviedock-codesign.pem" -outform DER \
  -out "$REPO_ROOT/packaging/selfsigned/moviedock-codesign.cer"

openssl x509 -in "$OUT/moviedock-codesign.pem" -noout -fingerprint -sha1 \
  | cut -d= -f2 | tr -d ':' | tr 'a-f' 'A-F' > "$OUT/thumbprint.txt"
chmod 600 "$OUT/moviedock-codesign.key" "$OUT/moviedock-codesign.pfx" "$OUT/thumbprint.txt"

echo "证书目录：$OUT"
openssl x509 -in "$OUT/moviedock-codesign.pem" -noout -subject -dates -fingerprint -sha1
echo "公开证书已更新：packaging/selfsigned/moviedock-codesign.cer"
echo "下一步：把 pfx 口令与指纹写入 GitHub Secrets（见本脚本头部注释）"
