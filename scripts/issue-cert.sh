#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/acme-common.sh"

print_help() {
  cat <<'EOF'
Usage: ./scripts/issue-cert.sh [--help]

Issue a wildcard certificate with ACME DNS-01 using acme.sh and AliDNS.

Required values in .env:
  DOMAIN
  LETSENCRYPT_EMAIL
  ALI_KEY
  ALI_SECRET

Notes:
  - Uses dns-01 via the AliDNS API
  - Uses acme.sh with the Let's Encrypt CA
  - Installs fullchain.pem and privkey.pem into certbot/conf/live/<domain>/
  - Only issues *.teraai.cn (does NOT cover bare domain teraai.cn)
EOF
}

main() {
  case "${1:-}" in
    --help|-h)
      print_help
      exit 0
      ;;
    "")
      ;;
    *)
      echo "Unknown argument: ${1}" >&2
      print_help >&2
      exit 1
      ;;
  esac

  require_env_file
  load_env
  require_values DOMAIN LETSENCRYPT_EMAIL ALI_KEY ALI_SECRET

  mkdir -p "${ACME_HOME_HOST}" "${CERT_ROOT_HOST}/live/${DOMAIN}"

  run_acme --set-default-ca --server letsencrypt

  # 签发证书（如果已存在且未过期则跳过，acme.sh 返回码 2）
  # 临时关闭 set -e，避免 acme.sh 返回码 2 时直接退出
  set +e
  run_acme \
    --issue \
    --dns dns_ali \
    --server letsencrypt \
    --accountemail "${LETSENCRYPT_EMAIL}" \
    -d "*.${DOMAIN}" \
    --keylength ec-256
  rc=$?
  set -e
  if [ "$rc" -ne 0 ]; then
    if [ "$rc" -eq 2 ]; then
      echo "Certificate already exists and is valid, skipping issue."
    else
      echo "ERROR: acme.sh issue failed with code $rc" >&2
      exit $rc
    fi
  fi

  run_acme \
    --install-cert \
    -d "*.${DOMAIN}" \
    --ecc \
    --fullchain-file "/output/live/${DOMAIN}/fullchain.pem" \
    --key-file "/output/live/${DOMAIN}/privkey.pem"

  echo "Certificate installed to: ${CERT_ROOT_HOST}/live/${DOMAIN}/"
  openssl x509 -in "${CERT_ROOT_HOST}/live/${DOMAIN}/fullchain.pem" -noout -subject -dates
}

main "$@"
