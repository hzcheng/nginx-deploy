#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

cd "${ROOT_DIR}"

# ------------------------------------------------------------------------------
# 检查前置条件
# ------------------------------------------------------------------------------

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "❌ .env not found. Copy .env.example to .env and fill in your values."
  exit 1
fi

# 加载 .env
set -a
source "${ENV_FILE}"
set +a

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
CRON_JOB="0 3 * * 1 cd ${ROOT_DIR} && ./scripts/renew-cert.sh >> /var/log/acme-renew.log 2>&1"
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
echo "🔑 默认密码: changeme"
echo "⚠️  请立即登录并修改密码"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
