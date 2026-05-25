#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

cd "${ROOT_DIR}"

# 默认需要确认，CI 或自动化测试时传入 --yes
# --keep-tailscale: 保留 Tailscale 容器和状态，避免重新申请 auth key
AUTO_CONFIRM=false
KEEP_TAILSCALE=false
for arg in "$@"; do
  case "$arg" in
    --yes|-y) AUTO_CONFIRM=true ;;
    --keep-tailscale) KEEP_TAILSCALE=true ;;
    --help|-h)
      cat <<'EOF'
Usage: ./scripts/uninstall.sh [OPTIONS]

一键清理 nginx-deploy 部署环境。

Options:
  --yes, -y          跳过交互确认，直接执行清理
  --keep-tailscale   保留 Tailscale 容器和认证状态，避免重新申请 auth key
  --help, -h         显示此帮助信息

Examples:
  ./scripts/uninstall.sh              # 交互式清理
  ./scripts/uninstall.sh --yes        # 自动确认，完整清理
  ./scripts/uninstall.sh --yes --keep-tailscale  # 保留 Tailscale 的自动清理
EOF
      exit 0
      ;;
  esac
done

# -----------------------------------------------------------------------------
# 确认提示
# -----------------------------------------------------------------------------
if [[ "$AUTO_CONFIRM" != true ]]; then
  echo "⚠️  此操作将删除容器、数据卷和定时任务，且不可恢复。"
  echo "   以下数据将被永久删除："
  if [[ "$KEEP_TAILSCALE" == true ]]; then
    echo "     - Docker 容器: npm, derper (保留 tailscale)"
    echo "     - 数据目录: npm/data, npm/letsencrypt, certbot/, logs/"
    echo "     - Tailscale 状态和容器将被保留"
  else
    echo "     - Docker 容器: tailscale, npm, derper"
    echo "     - 数据目录: npm/data, npm/letsencrypt, tailscale/state, certbot/"
    echo "     - 日志目录: logs/"
  fi
  echo "     - cron 自动续签任务"
  echo ""
  read -rp "确定要继续吗？输入 'yes' 确认: " confirm
  if [[ "$confirm" != "yes" ]]; then
    echo "❌ 已取消"
    exit 1
  fi
fi

# -----------------------------------------------------------------------------
# 1. 停止并删除容器
# -----------------------------------------------------------------------------
if [[ "$KEEP_TAILSCALE" == true ]]; then
  echo "🛑 停止并删除 npm、derper 容器（保留 tailscale）..."
  docker compose -f ./npm/compose.yaml -f ./derper/compose.yaml down 2>/dev/null || true
  # 如果上面的 down 失败（derper 可能在 profile 里），尝试停止具体容器
  docker stop npm derper 2>/dev/null || true
  docker rm npm derper 2>/dev/null || true
else
  echo "🛑 停止并删除所有容器..."
  docker compose --profile derper down --remove-orphans 2>/dev/null || docker compose down --remove-orphans 2>/dev/null || true
fi

# -----------------------------------------------------------------------------
# 2. 删除数据目录
# -----------------------------------------------------------------------------
echo "🗑️  删除数据目录..."
if [[ "$KEEP_TAILSCALE" == true ]]; then
  rm -rf \
    "${ROOT_DIR}/npm/data" \
    "${ROOT_DIR}/npm/letsencrypt" \
    "${ROOT_DIR}/certbot" \
    "${ROOT_DIR}/logs"
else
  rm -rf \
    "${ROOT_DIR}/npm/data" \
    "${ROOT_DIR}/npm/letsencrypt" \
    "${ROOT_DIR}/tailscale/state" \
    "${ROOT_DIR}/certbot" \
    "${ROOT_DIR}/logs"
fi

# -----------------------------------------------------------------------------
# 3. 删除 cron 任务
# -----------------------------------------------------------------------------
echo "🗑️  删除 cron 自动续签任务..."
CRON_MARKER="${ROOT_DIR}/scripts/renew-cert.sh"
if crontab -l 2>/dev/null | grep -qF "$CRON_MARKER"; then
  crontab -l 2>/dev/null | grep -vF "$CRON_MARKER" | crontab - 2>/dev/null || true
  echo "✅ 已删除 cron 任务"
else
  echo "ℹ️  未找到 cron 任务"
fi

# -----------------------------------------------------------------------------
# 4. 清理 dangling 镜像（可选）
# -----------------------------------------------------------------------------
if [[ "$AUTO_CONFIRM" != true ]]; then
  echo ""
  read -rp "是否删除未使用的 Docker 镜像？(y/N): " prune_images
  if [[ "$prune_images" == "y" || "$prune_images" == "Y" ]]; then
    docker image prune -f || true
  fi
else
  docker image prune -f || true
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 清理完成"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📁 以下文件保留未动："
echo "     - .env"
echo "     - scripts/"
echo "     - config/"
if [[ "$KEEP_TAILSCALE" == true ]]; then
  echo "     - tailscale/ (容器和状态已保留)"
fi
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
