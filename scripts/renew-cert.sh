#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/acme-common.sh"

print_help() {
  cat <<'EOF'
Usage: ./scripts/renew-cert.sh [--help]

Renew certificates with ACME DNS-01 using acme.sh and AliDNS.

Required values in .env:
  DOMAIN
  ALI_KEY
  ALI_SECRET

After renewal, syncs the new certificate to NPM and reloads nginx.
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
  require_values DOMAIN ALI_KEY ALI_SECRET

  mkdir -p "${ACME_HOME_HOST}" "${CERT_ROOT_HOST}/live/${DOMAIN}"

  run_acme --cron
  run_acme \
    --install-cert \
    -d "*.${DOMAIN}" \
    --ecc \
    --fullchain-file "/output/live/${DOMAIN}/fullchain.pem" \
    --key-file "/output/live/${DOMAIN}/privkey.pem"

  echo "Certificate renewed and installed."

  # Sync to NPM custom_ssl directory and reload nginx
  "${ROOT_DIR}/scripts/sync-cert-to-npm.sh"

  echo "Reloading NPM nginx to load new certificate..."
  docker compose -f "${ROOT_DIR}/compose.yaml" exec npm nginx -s reload
}

main "$@"
