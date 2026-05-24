#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
ACME_HOME_HOST="${ROOT_DIR}/certbot/acme-home"
CERT_ROOT_HOST="${ROOT_DIR}/certbot/conf"
ACME_IMAGE="${ACME_IMAGE:-neilpang/acme.sh:latest}"

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

require_env_file() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    echo ".env not found. Copy .env.example to .env first." >&2
    exit 1
  fi
}

load_env() {
  set -a
  source "${ENV_FILE}"
  set +a
}

require_values() {
  local missing=()

  for name in DOMAIN LETSENCRYPT_EMAIL ALI_KEY ALI_SECRET; do
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
  require_values

  mkdir -p "${ACME_HOME_HOST}" "${CERT_ROOT_HOST}/live/${DOMAIN}"

  run_acme --set-default-ca --server letsencrypt

  # 签发证书（如果已存在且未过期则跳过，acme.sh 返回码 2）
  if ! run_acme \
    --issue \
    --dns dns_ali \
    --server letsencrypt \
    --accountemail "${LETSENCRYPT_EMAIL}" \
    -d "*.${DOMAIN}" \
    --keylength ec-256; then
    rc=$?
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
