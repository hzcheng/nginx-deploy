#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

cd "${ROOT_DIR}"

# ------------------------------------------------------------------------------
# 辅助函数：从 .env 安全读取变量（不导出到全局环境）
# ------------------------------------------------------------------------------
read_env_var() {
  local var_name="$1"
  local file="${2:-${ENV_FILE}}"
  awk -F= -v key="$var_name" '
    BEGIN { found=0 }
    $1 ~ "^[ \t]*" key "[ \t]*$" {
      val = substr($0, index($0, "=") + 1)
      sub(/^[ \t]+/, "", val)
      sub(/[ \t]+$/, "", val)
      gsub(/^["\047]/, "", val)
      gsub(/["\047]$/, "", val)
      print val
      found=1
      exit
    }
    END { if (!found) exit 1 }
  ' "$file"
}

# ------------------------------------------------------------------------------
# 检查前置条件
# ------------------------------------------------------------------------------

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "❌ .env not found. Copy .env.example to .env and fill in your values."
  exit 1
fi

# 检查 Python 3
if ! command -v python3 &>/dev/null; then
  echo "❌ Python 3 not found. Please install Python 3 first."
  exit 1
fi

# 检查 Docker
if ! command -v docker &>/dev/null; then
  echo "❌ Docker not found. Please install Docker first:"
  echo "   curl -fsSL https://get.docker.com | sh"
  exit 1
fi

if ! docker compose version &>/dev/null; then
  echo "❌ Docker Compose plugin not found."
  exit 1
fi

# 安全加载 .env 变量（不导出到环境）
DOMAIN=$(read_env_var "DOMAIN")
LETSENCRYPT_EMAIL=$(read_env_var "LETSENCRYPT_EMAIL")
ALI_KEY=$(read_env_var "ALI_KEY")
ALI_SECRET=$(read_env_var "ALI_SECRET")
TS_AUTHKEY=$(read_env_var "TS_AUTHKEY")
TAILSCALE_HOSTNAME=$(read_env_var "TAILSCALE_HOSTNAME" "cloud-server")
NPM_IMAGE_TAG=$(read_env_var "NPM_IMAGE_TAG" "latest")
ENABLE_DERPER=$(read_env_var "ENABLE_DERPER" "false")
DERP_STUN_PORT=$(read_env_var "DERP_STUN_PORT" "3478")

# 检查 .env 必填项
for name in DOMAIN LETSENCRYPT_EMAIL ALI_KEY ALI_SECRET TS_AUTHKEY; do
  if [[ -z "${!name:-}" ]]; then
    echo "❌ Missing required value in .env: ${name}"
    exit 1
  fi
done

# 确保数据目录存在
mkdir -p npm/data npm/letsencrypt tailscale/state certbot/{acme-home,conf}

# ------------------------------------------------------------------------------
# 1. 启动 Tailscale
# ------------------------------------------------------------------------------
echo "🚀 启动 Tailscale..."
docker compose up -d tailscale

# 等待 Tailscale 认证（最多 60 秒）
echo "⏳ 等待 Tailscale 认证..."
for i in {1..30}; do
  if docker exec tailscale tailscale status &>/dev/null; then
    echo "✅ Tailscale 已在线"
    break
  fi
  sleep 2
done

if ! docker exec tailscale tailscale status &>/dev/null; then
  echo "❌ Tailscale 认证失败。请检查 TS_AUTHKEY 是否正确。"
  echo "   查看日志: docker compose logs -f tailscale"
  exit 1
fi

# ------------------------------------------------------------------------------
# 2. 签发 SSL 证书
# ------------------------------------------------------------------------------
echo "🔐 签发 SSL 证书..."
./scripts/issue-cert.sh

# ------------------------------------------------------------------------------
# 3. 预填充 NPM 数据库
# ------------------------------------------------------------------------------
echo "⚙️  预填充 NPM 数据库..."
python3 scripts/init-db.py

# ------------------------------------------------------------------------------
# 4. 启动 NPM
# ------------------------------------------------------------------------------
echo "🚀 启动 NPM..."
docker compose up -d npm

# 等待 NPM 就绪（最多 60 秒）
echo "⏳ 等待 NPM 启动..."
for i in {1..30}; do
  if curl -sf http://127.0.0.1:81/api/ &>/dev/null; then
    echo "✅ NPM 已就绪"
    break
  fi
  sleep 2
done

if ! curl -sf http://127.0.0.1:81/api/ &>/dev/null; then
  echo "❌ NPM 启动失败。请检查日志: docker compose logs -f npm"
  exit 1
fi

# ------------------------------------------------------------------------------
# 5. 按需启动 Derper
# ------------------------------------------------------------------------------
if [[ "${ENABLE_DERPER:-false}" == "true" ]]; then
  echo "🌐 启动 Derper..."
  docker compose --profile derper up -d --build
fi

# ------------------------------------------------------------------------------
# 6. 设置 cron 自动续签
# ------------------------------------------------------------------------------
mkdir -p "${ROOT_DIR}/logs"
CRON_JOB="0 3 * * 1 cd ${ROOT_DIR} && ./scripts/renew-cert.sh >> ${ROOT_DIR}/logs/acme-renew.log 2>&1"
if ! (crontab -l 2>/dev/null | grep -qF "${ROOT_DIR}/scripts/renew-cert.sh"); then
  echo "📝 设置 cron 自动续签..."
  (crontab -l 2>/dev/null || true; echo "${CRON_JOB}") | crontab -
fi

# ------------------------------------------------------------------------------
# 完成
# ------------------------------------------------------------------------------
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 部署完成！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🌐 管理界面: https://nginx.${DOMAIN}"
echo "📧 默认账号: admin@example.com"
echo "⚠️  首次登录后请立即修改默认密码"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
