#!/usr/bin/env bash
# acme-common.sh — 被 issue-cert.sh / renew-cert.sh / sync-cert-to-npm.sh 共享的辅助函数

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
ACME_HOME_HOST="${ROOT_DIR}/certbot/acme-home"
CERT_ROOT_HOST="${ROOT_DIR}/certbot/conf"
ACME_IMAGE="${ACME_IMAGE:-neilpang/acme.sh:3.1.0}"

require_env_file() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    echo ".env not found. Copy .env.example to .env first." >&2
    exit 1
  fi
}

load_env() {
  # 只读取需要的变量，避免将整个 .env 导出到进程环境
  DOMAIN=$(read_env_var "DOMAIN")
  LETSENCRYPT_EMAIL=$(read_env_var "LETSENCRYPT_EMAIL")
  ALI_KEY=$(read_env_var "ALI_KEY")
  ALI_SECRET=$(read_env_var "ALI_SECRET")
}

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

require_values() {
  local missing=()

  for name in "$@"; do
    if [[ -z "${!name:-}" ]]; then
      missing+=("${name}")
    fi
  done

  if (( ${#missing[@]} > 0 )); then
    printf 'Missing required values in .env: %s\n' "${missing[*]}" >&2
    exit 1
  fi
}

run_acme() {
  docker run --rm \
    -e Ali_Key="${ALI_KEY}" \
    -e Ali_Secret="${ALI_SECRET}" \
    -v "${ACME_HOME_HOST}:/acme.sh" \
    -v "${CERT_ROOT_HOST}:/output" \
    "${ACME_IMAGE}" \
    "$@"
}
