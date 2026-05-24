#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
CERT_DIR="${ROOT_DIR}/certbot/conf/live"
NPM_SSL_DIR="${ROOT_DIR}/npm/data/custom_ssl"

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

main() {
  require_env_file
  load_env

  DOMAIN="${DOMAIN:-teraai.cn}"
  SRC_DIR="${CERT_DIR}/${DOMAIN}"

  if [[ ! -f "${SRC_DIR}/fullchain.pem" ]]; then
    echo "Certificate not found: ${SRC_DIR}/fullchain.pem" >&2
    exit 1
  fi

  if [[ ! -d "${NPM_SSL_DIR}" ]]; then
    echo "NPM custom_ssl directory not found. Has NPM been started at least once?" >&2
    exit 1
  fi

  FOUND=0
  for dir in "${NPM_SSL_DIR}"/*/; do
    if [[ -f "$dir/metadata.json" ]]; then
      if grep -q "${DOMAIN}" "$dir/metadata.json" 2>/dev/null; then
        cp "${SRC_DIR}/fullchain.pem" "$dir/fullchain.pem"
        cp "${SRC_DIR}/privkey.pem" "$dir/privkey.pem"
        echo "Synced to $dir"
        FOUND=1
      fi
    fi
  done

  if [[ "$FOUND" -eq 0 ]]; then
    echo "No NPM custom certificate found for ${DOMAIN}." >&2
    echo "Please ensure init-db.py has created the certificate record first." >&2
    exit 1
  fi

  echo "Certificate synced successfully."
}

main "$@"
