#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
ACME_HOME_HOST="${ROOT_DIR}/certbot/acme-home"
CERT_ROOT_HOST="${ROOT_DIR}/certbot/conf"
ACME_IMAGE="${ACME_IMAGE:-neilpang/acme.sh:latest}"

print_help() {
  cat <<'EOF'
Usage: ./scripts/renew-cert.sh [--help]

Renew certificates with ACME DNS-01 using acme.sh and AliDNS.

Required values in .env:
  DOMAIN
  ALI_KEY
  ALI_SECRET

After renewal, syncs the new certificate to NPM and restarts the container.
EOF
}

require_env_file() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    echo ".env not found." >&2
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

  for name in DOMAIN ALI_KEY ALI_SECRET; do
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
  run_acme --cron
  run_acme \
    --install-cert \
    -d "*.${DOMAIN}" \
    --ecc \
    --fullchain-file "/output/live/${DOMAIN}/fullchain.pem" \
    --key-file "/output/live/${DOMAIN}/privkey.pem"

  echo "Certificate renewed and installed."

  # Sync to NPM custom_ssl directory and restart
  "${ROOT_DIR}/scripts/sync-cert-to-npm.sh"

  echo "Restarting NPM to load new certificate..."
  docker compose -f "${ROOT_DIR}/compose.yaml" restart npm
}

main "$@"
