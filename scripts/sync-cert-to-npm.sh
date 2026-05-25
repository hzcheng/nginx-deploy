#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/acme-common.sh"

CERT_DIR="${ROOT_DIR}/certbot/conf/live"
NPM_SSL_DIR="${ROOT_DIR}/npm/data/custom_ssl"

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
      # 用 python3 精确匹配域名，避免 grep 误匹配
      if python3 -c "
import json, sys
with open('$dir/metadata.json') as f:
    data = json.load(f)
for name in data.get('domain_names', []):
    if '${DOMAIN}' in name:
        sys.exit(0)
sys.exit(1)
" 2>/dev/null; then
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
