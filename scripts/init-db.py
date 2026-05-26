#!/usr/bin/env python3
"""预生成 NPM 的 SQLite 数据库和 custom_ssl 证书目录。

运行时机：首次部署时，在启动 NPM 容器之前执行。
效果：NPM 启动后自动拥有预配置的用户、证书和 Proxy Host。
"""

import os
import sys
import json
import re
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# ------------------------------------------------------------------------------
# 配置路径
# ------------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"
CERT_DIR = ROOT_DIR / "certbot" / "conf" / "live"
DATA_DIR = ROOT_DIR / "npm" / "data"
CUSTOM_SSL_DIR = DATA_DIR / "custom_ssl"
DB_FILE = DATA_DIR / "database.sqlite"
SERVICES_FILE = ROOT_DIR / "config" / "services.yml"

# 证书目录名（对应 certificate.nice_name）
CERT_NICE_NAME = "npm-1"

# bcrypt hash of "changeme" (generated once, valid for any bcrypt verifier)
# python3 -c "import bcrypt; print(bcrypt.hashpw(b'changeme', bcrypt.gensalt(rounds=10)).decode())"
DEFAULT_PASSWORD_HASH = (
    "$2b$10$fdZ8vbpfzh8Z0u7veIYMSOY56kHgEicMwLxmca3O3zfHlL/RF/IDu"
)


def load_env():
    """读取 .env 文件到环境变量。"""
    if not ENV_FILE.exists():
        print(f"ERROR: {ENV_FILE} not found.", file=sys.stderr)
        sys.exit(1)

    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)


def get_env(key, default=None):
    return os.environ.get(key, default)


def parse_cert_expiry(cert_path: Path) -> str:
    """从 PEM 证书中提取过期时间，返回 'YYYY-MM-DD HH:MM:SS'。"""
    result = subprocess.run(
        ["openssl", "x509", "-in", str(cert_path), "-noout", "-enddate"],
        capture_output=True,
        text=True,
        check=True,
    )
    # notAfter=Aug 22 10:00:00 2026 GMT
    match = re.search(r"notAfter=(.+)", result.stdout)
    if not match:
        raise RuntimeError("Failed to parse certificate expiry")
    dt = datetime.strptime(match.group(1).strip(), "%b %d %H:%M:%S %Y %Z")
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def split_fullchain_text(content: str):
    """将 fullchain.pem 文本拆分为 cert.pem 和 chain.pem。"""
    certs = re.findall(
        r"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
        content,
        re.DOTALL,
    )
    if len(certs) < 1:
        raise RuntimeError("No certificates found in fullchain.pem")

    cert_pem = certs[0]
    chain_pem = "\n".join(certs[1:]) if len(certs) > 1 else cert_pem
    return cert_pem, chain_pem


def split_fullchain(fullchain_path: Path):
    """将 fullchain.pem 文件拆分为 cert.pem 和 chain.pem。"""
    with open(fullchain_path, "r", encoding="utf-8") as f:
        content = f.read()
    return split_fullchain_text(content)


def load_services():
    """读取 config/services.yml，返回预定义服务列表。"""
    if not SERVICES_FILE.exists():
        return []

    try:
        import yaml
    except ImportError:
        print("WARNING: PyYAML not installed, skipping services.yml", file=sys.stderr)
        return []

    with open(SERVICES_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return data.get("services") or []


def load_streams():
    """读取 config/services.yml，返回预定义流代理列表。"""
    if not SERVICES_FILE.exists():
        return []

    try:
        import yaml
    except ImportError:
        return []

    with open(SERVICES_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return data.get("streams") or []


def create_tables(conn: sqlite3.Connection):
    """创建 NPM 所需的 SQLite 表（v2.11.3 全部 migration 完成后的最终 schema）。

    migrate.js 显式调用 db.migrate.latest({tableName: 'migrations', ...})，
    因此 migration 记录表必须命名为 migrations。
    """
    c = conn.cursor()

    # --- 核心功能表 ---

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS user (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            is_disabled INTEGER NOT NULL DEFAULT 0,
            email TEXT NOT NULL,
            name TEXT NOT NULL,
            nickname TEXT NOT NULL,
            avatar TEXT NOT NULL DEFAULT '',
            roles TEXT NOT NULL DEFAULT '[]'
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS auth (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL DEFAULT 'password',
            secret TEXT NOT NULL,
            meta TEXT NOT NULL DEFAULT '{}',
            is_deleted INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS user_permission (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER NOT NULL UNIQUE,
            visibility TEXT NOT NULL DEFAULT 'all',
            proxy_hosts TEXT NOT NULL DEFAULT 'manage',
            redirection_hosts TEXT NOT NULL DEFAULT 'manage',
            dead_hosts TEXT NOT NULL DEFAULT 'manage',
            streams TEXT NOT NULL DEFAULT 'manage',
            access_lists TEXT NOT NULL DEFAULT 'manage',
            certificates TEXT NOT NULL DEFAULT 'manage'
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS certificate (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            owner_user_id INTEGER NOT NULL DEFAULT 1,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            provider TEXT NOT NULL,
            nice_name TEXT NOT NULL DEFAULT '',
            domain_names TEXT NOT NULL,
            expires_on DATETIME NOT NULL,
            meta TEXT NOT NULL DEFAULT '{}'
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS proxy_host (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            owner_user_id INTEGER NOT NULL DEFAULT 1,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            domain_names TEXT NOT NULL,
            forward_host TEXT NOT NULL DEFAULT '',
            forward_port INTEGER NOT NULL DEFAULT 80,
            access_list_id INTEGER NOT NULL DEFAULT 0,
            certificate_id INTEGER NOT NULL DEFAULT 0,
            ssl_forced INTEGER NOT NULL DEFAULT 0,
            caching_enabled INTEGER NOT NULL DEFAULT 0,
            block_exploits INTEGER NOT NULL DEFAULT 0,
            advanced_config TEXT NOT NULL DEFAULT '',
            meta TEXT NOT NULL DEFAULT '{}',
            allow_websocket_upgrade INTEGER NOT NULL DEFAULT 0,
            http2_support INTEGER NOT NULL DEFAULT 0,
            forward_scheme TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            hsts_enabled INTEGER NOT NULL DEFAULT 0,
            hsts_subdomains INTEGER NOT NULL DEFAULT 0,
            locations TEXT DEFAULT '[]'
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS setting (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            value TEXT NOT NULL,
            meta TEXT NOT NULL DEFAULT '{}'
        )
        """
    )

    # --- NPM 完整功能所需的辅助表 ---

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS redirection_host (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            owner_user_id INTEGER NOT NULL DEFAULT 1,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            domain_names TEXT NOT NULL,
            forward_domain_name TEXT NOT NULL,
            preserve_path INTEGER NOT NULL DEFAULT 0,
            certificate_id INTEGER NOT NULL DEFAULT 0,
            ssl_forced INTEGER NOT NULL DEFAULT 0,
            block_exploits INTEGER NOT NULL DEFAULT 0,
            advanced_config TEXT NOT NULL DEFAULT '',
            meta TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1,
            hsts_enabled INTEGER NOT NULL DEFAULT 0,
            hsts_subdomains INTEGER NOT NULL DEFAULT 0,
            forward_scheme TEXT NOT NULL DEFAULT '$scheme',
            forward_http_code INTEGER NOT NULL DEFAULT 302
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS dead_host (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            owner_user_id INTEGER NOT NULL DEFAULT 1,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            domain_names TEXT NOT NULL,
            certificate_id INTEGER NOT NULL DEFAULT 0,
            ssl_forced INTEGER NOT NULL DEFAULT 0,
            advanced_config TEXT NOT NULL DEFAULT '',
            meta TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1,
            hsts_enabled INTEGER NOT NULL DEFAULT 0,
            hsts_subdomains INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS stream (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            owner_user_id INTEGER NOT NULL DEFAULT 1,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            incoming_port INTEGER NOT NULL,
            forwarding_host TEXT NOT NULL,
            forwarding_port INTEGER NOT NULL,
            tcp_forwarding INTEGER NOT NULL DEFAULT 0,
            udp_forwarding INTEGER NOT NULL DEFAULT 0,
            meta TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS access_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            owner_user_id INTEGER NOT NULL DEFAULT 1,
            is_deleted INTEGER NOT NULL DEFAULT 0,
            name TEXT NOT NULL,
            meta TEXT NOT NULL DEFAULT '{}',
            satisfy_any INTEGER NOT NULL DEFAULT 0,
            pass_auth INTEGER NOT NULL DEFAULT 1
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS access_list_auth (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            access_list_id INTEGER NOT NULL,
            username TEXT NOT NULL,
            password TEXT NOT NULL,
            meta TEXT NOT NULL DEFAULT '{}'
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS access_list_client (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            access_list_id INTEGER NOT NULL,
            address TEXT NOT NULL,
            directive TEXT NOT NULL,
            meta TEXT NOT NULL DEFAULT '{}'
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            modified_on DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            user_id INTEGER NOT NULL,
            object_type TEXT NOT NULL DEFAULT '',
            object_id INTEGER NOT NULL DEFAULT 0,
            action TEXT NOT NULL,
            meta TEXT NOT NULL DEFAULT '{}'
        )
        """
    )

    # --- knex migration 记录表 ---
    # migrate.js 显式调用 db.migrate.latest({tableName: 'migrations', ...})，
    # 覆盖了 knex 默认表名，因此必须使用 migrations / migrations_lock

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS migrations_lock (
            "index" INTEGER PRIMARY KEY AUTOINCREMENT,
            is_locked INTEGER DEFAULT 0
        )
        """
    )

    c.execute(
        """
        CREATE TABLE IF NOT EXISTS migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            batch INTEGER NOT NULL,
            migration_time DATETIME NOT NULL
        )
        """
    )

    conn.commit()


def insert_user(conn: sqlite3.Connection):
    """插入默认管理员用户。"""
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    c.execute(
        """
        INSERT INTO user (created_on, modified_on, email, name, nickname, roles)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (now, now, "admin@example.com", "Administrator", "Admin", json.dumps(["admin"])),
    )
    user_id = c.lastrowid

    c.execute(
        """
        INSERT INTO auth (created_on, modified_on, user_id, type, secret, meta)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (now, now, user_id, "password", DEFAULT_PASSWORD_HASH, json.dumps({})),
    )

    c.execute(
        """
        INSERT INTO user_permission
        (created_on, modified_on, user_id, visibility, proxy_hosts,
         redirection_hosts, dead_hosts, streams, access_lists, certificates)
        VALUES (?, ?, ?, 'all', 'manage', 'manage', 'manage', 'manage', 'manage', 'manage')
        """,
        (now, now, user_id),
    )

    conn.commit()
    return user_id


def insert_certificate(conn: sqlite3.Connection, domain: str, cert_dir: Path):
    """插入通配符证书记录，返回 certificate_id。"""
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fullchain_path = cert_dir / "fullchain.pem"
    expires_on = parse_cert_expiry(fullchain_path)

    c.execute(
        """
        INSERT INTO certificate
        (created_on, modified_on, owner_user_id, provider, nice_name, domain_names, expires_on, meta)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now,
            now,
            1,
            "other",
            CERT_NICE_NAME,
            json.dumps([f"*.{domain}"]),
            expires_on,
            json.dumps({"letsencrypt_email": get_env("LETSENCRYPT_EMAIL", "admin@example.com")}),
        ),
    )

    conn.commit()
    return c.lastrowid


def insert_proxy_host(
    conn: sqlite3.Connection,
    domain_names: list,
    forward_scheme: str,
    forward_host: str,
    forward_port: int,
    certificate_id: int,
    websocket: bool = False,
    advanced_config: str = "",
):
    """插入 Proxy Host 记录。"""
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    c.execute(
        """
        INSERT INTO proxy_host
        (created_on, modified_on, domain_names, forward_host, forward_port,
         certificate_id, ssl_forced, http2_support, block_exploits,
         advanced_config, meta, allow_websocket_upgrade, forward_scheme)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            now,
            now,
            json.dumps(domain_names),
            forward_host,
            forward_port,
            certificate_id,
            1,  # ssl_forced
            1,  # http2_support
            1,  # block_exploits
            advanced_config,
            json.dumps({"letsencrypt_agree": False, "dns_challenge": False}),
            1 if websocket else 0,
            forward_scheme,
        ),
    )

    conn.commit()
    return c.lastrowid

def insert_stream(
    conn: sqlite3.Connection,
    incoming_port: int,
    forwarding_host: str,
    forwarding_port: int,
    protocol: str = "tcp",
):
    """插入 Stream 记录（TCP/UDP 流代理）。"""
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    tcp_forwarding = 1 if protocol == "tcp" else 0
    udp_forwarding = 1 if protocol == "udp" else 0

    c.execute(
        """
        INSERT INTO stream
        (created_on, modified_on, owner_user_id, incoming_port,
         forwarding_host, forwarding_port, tcp_forwarding, udp_forwarding,
         meta, enabled)
        VALUES (?, ?, 1, ?, ?, ?, ?, ?, '{}', 1)
        """,
        (now, now, incoming_port, forwarding_host, forwarding_port,
         tcp_forwarding, udp_forwarding),
    )

    conn.commit()
    return c.lastrowid


def setup_custom_ssl(cert_dir: Path, domain: str):
    """创建 custom_ssl 目录结构并复制证书文件。"""
    target_dir = CUSTOM_SSL_DIR / CERT_NICE_NAME
    target_dir.mkdir(parents=True, exist_ok=True)

    fullchain_path = cert_dir / "fullchain.pem"
    privkey_path = cert_dir / "privkey.pem"

    if not fullchain_path.exists():
        print(f"ERROR: Certificate not found: {fullchain_path}", file=sys.stderr)
        sys.exit(1)

    fullchain_text = fullchain_path.read_text(encoding="utf-8")
    cert_pem, chain_pem = split_fullchain_text(fullchain_text)

    # 写入证书文件
    (target_dir / "fullchain.pem").write_text(fullchain_text, encoding="utf-8")
    (target_dir / "privkey.pem").write_text(privkey_path.read_text(encoding="utf-8"), encoding="utf-8")
    (target_dir / "cert.pem").write_text(cert_pem, encoding="utf-8")
    (target_dir / "chain.pem").write_text(chain_pem, encoding="utf-8")

    # 生成 metadata.json
    expires_on = parse_cert_expiry(fullchain_path)
    metadata = {
        "domain_names": [f"*.{domain}"],
        "expires_on": f"{expires_on.replace(' ', 'T')}.000Z",
    }
    (target_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    print(f"Certificate installed to: {target_dir}")


MIGRATION_NAMES = [
    "20180618015850_initial.js",
    "20180929054513_websockets.js",
    "20181019052346_forward_host.js",
    "20181113041458_http2_support.js",
    "20181213013211_forward_scheme.js",
    "20190104035154_disabled.js",
    "20190215115310_customlocations.js",
    "20190218060101_hsts.js",
    "20190227065017_settings.js",
    "20200410143839_access_list_client.js",
    "20200410143840_access_list_client_fix.js",
    "20201014143841_pass_auth.js",
    "20210210154702_redirection_scheme.js",
    "20210210154703_redirection_status_code.js",
    "20210423103500_stream_domain.js",
    "20211108145214_regenerate_default_host.js",
]


def _insert_knex_migrations(conn: sqlite3.Connection):
    """插入 migration 记录到 migrations 表，让 NPM 认为数据库已是最新版本。

    migrate.js 显式调用 db.migrate.latest({tableName: 'migrations', ...})，
    因此表名必须是 migrations。
    """
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 初始化 lock 表
    c.execute("DELETE FROM migrations_lock")
    c.execute("INSERT INTO migrations_lock (is_locked) VALUES (0)")

    # 插入所有 migration 记录
    for name in MIGRATION_NAMES:
        c.execute(
            """
            INSERT INTO migrations (name, batch, migration_time)
            VALUES (?, ?, ?)
            """,
            (name, 1, now),
        )

    conn.commit()
    print(f"Inserted {len(MIGRATION_NAMES)} knex migration records.")


NGINX_PROXY_HOST_DIR = DATA_DIR / "nginx" / "proxy_host"
NGINX_STREAM_DIR = DATA_DIR / "nginx" / "stream"



def _nginx_conf_header(domain_names):
    return f"# ------------------------------------------------------------\n# {', '.join(domain_names)}\n# ------------------------------------------------------------\n"


def _nginx_conf_body(host_id, domain_names, forward_scheme, forward_host,
                     forward_port, certificate_id, ssl_forced, http2_support,
                     block_exploits, hsts_enabled, allow_websocket_upgrade,
                     advanced_config):
    """Generate a single NPM-style proxy_host nginx config."""
    lines = [_nginx_conf_header(domain_names)]
    lines.append("")
    lines.append("server {")
    lines.append(f'  set $forward_scheme {forward_scheme};')
    lines.append(f'  set $server         "{forward_host}";')
    lines.append(f'  set $port           {forward_port};')
    lines.append("")
    # Listen directives
    lines.append("  listen 80;")
    lines.append("  listen [::]:80;")
    if certificate_id and certificate_id > 0:
        http2 = " http2" if http2_support else ""
        lines.append(f"  listen 443 ssl{http2};")
        lines.append(f"  listen [::]:443 ssl{http2};")
    lines.append(f'  server_name {" ".join(domain_names)};')
    lines.append("")
    # SSL cert
    if certificate_id and certificate_id > 0:
        lines.append("  # Custom SSL")
        lines.append(f"  ssl_certificate /data/custom_ssl/npm-{certificate_id}/fullchain.pem;")
        lines.append(f"  ssl_certificate_key /data/custom_ssl/npm-{certificate_id}/privkey.pem;")
        lines.append("")
    # Block exploits
    if block_exploits:
        lines.append("  # Block Exploits")
        lines.append("  include conf.d/include/block-exploits.conf;")
        lines.append("")
    # HSTS
    if certificate_id and certificate_id > 0 and ssl_forced and hsts_enabled:
        lines.append("  # HSTS")
        lines.append("  add_header Strict-Transport-Security $hsts_header always;")
        lines.append("")
    # Force SSL
    if certificate_id and certificate_id > 0 and ssl_forced:
        lines.append("  # Force SSL")
        lines.append("  include conf.d/include/force-ssl.conf;")
        lines.append("")
    # Websocket
    if allow_websocket_upgrade:
        lines.append("proxy_set_header Upgrade $http_upgrade;")
        lines.append("proxy_set_header Connection $http_connection;")
        lines.append("proxy_http_version 1.1;")
        lines.append("")
    # Logs
    lines.append(f"  access_log /data/logs/proxy-host-{host_id}_access.log proxy;")
    lines.append(f"  error_log /data/logs/proxy-host-{host_id}_error.log warn;")
    lines.append("")
    # Advanced config
    if advanced_config:
        lines.append(advanced_config)
        lines.append("")
    # Location block
    lines.append("  location / {")
    lines.append("")
    if certificate_id and certificate_id > 0 and ssl_forced and hsts_enabled:
        lines.append("    # HSTS")
        lines.append("    add_header Strict-Transport-Security $hsts_header always;")
        lines.append("")
    if allow_websocket_upgrade:
        lines.append("    proxy_set_header Upgrade $http_upgrade;")
        lines.append("    proxy_set_header Connection $http_connection;")
        lines.append("    proxy_http_version 1.1;")
        lines.append("")
    lines.append("    # Proxy!")
    lines.append("    include conf.d/include/proxy.conf;")
    lines.append("  }")
    lines.append("")
    lines.append("  # Custom")
    lines.append("  include /data/nginx/custom/server_proxy[.]conf;")
    lines.append("}")
    return "\n".join(lines) + "\n"


def generate_nginx_configs(conn: sqlite3.Connection):
    """从数据库生成 /data/nginx/proxy_host/*.conf 文件。

    NPM 仅在通过 API 创建/更新 Proxy Host 时生成 nginx 配置，
    不会在启动时从数据库重建。因此首次部署时必须手动生成这些文件。
    """
    NGINX_PROXY_HOST_DIR.mkdir(parents=True, exist_ok=True)

    c = conn.cursor()
    c.execute("""
        SELECT id, domain_names, forward_scheme, forward_host, forward_port,
               certificate_id, ssl_forced, http2_support, block_exploits,
               hsts_enabled, allow_websocket_upgrade, advanced_config
        FROM proxy_host
        WHERE is_deleted = 0 AND enabled = 1
    """)

    count = 0
    for row in c.fetchall():
        (host_id, domain_names_json, forward_scheme, forward_host,
         forward_port, certificate_id, ssl_forced, http2_support,
         block_exploits, hsts_enabled, allow_websocket_upgrade,
         advanced_config) = row

        domain_names = json.loads(domain_names_json)

        conf_content = _nginx_conf_body(
            host_id=host_id,
            domain_names=domain_names,
            forward_scheme=forward_scheme or "http",
            forward_host=forward_host,
            forward_port=forward_port,
            certificate_id=certificate_id,
            ssl_forced=ssl_forced,
            http2_support=http2_support,
            block_exploits=block_exploits,
            hsts_enabled=hsts_enabled,
            allow_websocket_upgrade=allow_websocket_upgrade,
            advanced_config=advanced_config or "",
        )

        conf_path = NGINX_PROXY_HOST_DIR / f"{host_id}.conf"
        conf_path.write_text(conf_content, encoding="utf-8")
        print(f"Generated nginx config: {conf_path}")
        count += 1

    print(f"Generated {count} nginx proxy host config(s).")
    return count


def generate_stream_nginx_configs(conn: sqlite3.Connection):
    """从数据库生成 /data/nginx/stream/*.conf 文件。

    NPM 仅在通过 API 创建/更新 Stream 时生成 nginx 配置，
    不会在启动时从数据库重建。因此首次部署时必须手动生成这些文件。
    """
    NGINX_STREAM_DIR.mkdir(parents=True, exist_ok=True)

    c = conn.cursor()
    c.execute("""
        SELECT id, incoming_port, forwarding_host, forwarding_port,
               tcp_forwarding, udp_forwarding
        FROM stream
        WHERE is_deleted = 0 AND enabled = 1
    """)

    count = 0
    for row in c.fetchall():
        stream_id, incoming_port, forwarding_host, forwarding_port, \
            tcp_forwarding, udp_forwarding = row

        protocol = "tcp" if tcp_forwarding else "udp"
        conf_content = (
            f"# ------------------------------------------------------------\n"
            f"# Stream: {protocol} {incoming_port} -> {forwarding_host}:{forwarding_port}\n"
            f"# ------------------------------------------------------------\n\n"
            f"server {{\n"
            f"    listen {incoming_port};\n"
            f"    proxy_pass {forwarding_host}:{forwarding_port};\n"
            f"    proxy_connect_timeout 1h;\n"
            f"    proxy_timeout 1h;\n"
            f"}}\n"
        )

        conf_path = NGINX_STREAM_DIR / f"{stream_id}.conf"
        conf_path.write_text(conf_content, encoding="utf-8")
        print(f"Generated stream config: {conf_path}")
        count += 1

    print(f"Generated {count} stream nginx config(s).")
    return count


def _fix_permissions():
    """调整 npm/data 目录的属主为 NPM 容器的 UID (911)。"""
    try:
        for path in [DATA_DIR, CUSTOM_SSL_DIR, DB_FILE]:
            if path.exists():
                os.chown(str(path), 911, 911)
        # 递归设置 data、custom_ssl 和 letsencrypt 子目录
        for base_dir in [DATA_DIR, CUSTOM_SSL_DIR]:
            if base_dir.exists():
                for root, dirs, files in os.walk(str(base_dir)):
                    for d in dirs:
                        os.chown(os.path.join(root, d), 911, 911)
                    for f in files:
                        os.chown(os.path.join(root, f), 911, 911)
        # 设置 letsencrypt 目录权限
        letsencrypt_dir = ROOT_DIR / "npm" / "letsencrypt"
        if letsencrypt_dir.exists():
            os.chown(str(letsencrypt_dir), 911, 911)
        print("Fixed permissions for UID 911.")
    except PermissionError:
        print("WARNING: Could not fix permissions. NPM may not be able to write to database.")


def main():
    load_env()

    domain = get_env("DOMAIN", "teraai.cn")
    cert_domain_dir = CERT_DIR / domain

    if not cert_domain_dir.exists():
        print(f"ERROR: Certificate directory not found: {cert_domain_dir}", file=sys.stderr)
        print("Please run ./scripts/issue-cert.sh first.", file=sys.stderr)
        sys.exit(1)

    # 确保数据目录存在
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CUSTOM_SSL_DIR.mkdir(parents=True, exist_ok=True)

    if DB_FILE.exists():
        print(f"Database already exists: {DB_FILE}, skipping initialization.")
        conn = sqlite3.connect(str(DB_FILE))
        try:
            # 重新生成 nginx 配置文件（容器重建后可能需要）
            generate_nginx_configs(conn)
            generate_stream_nginx_configs(conn)
        finally:
            conn.close()
        _fix_permissions()
        return

    conn = sqlite3.connect(str(DB_FILE))

    try:
        create_tables(conn)
        insert_user(conn)
        cert_id = insert_certificate(conn, domain, cert_domain_dir)

        # 默认反代：www.teraai.cn → 导航页
        # 导航页的目标可以在 services.yml 中配置，默认反代到 127.0.0.1:80
        insert_proxy_host(
            conn,
            domain_names=[f"www.{domain}"],
            forward_scheme="http",
            forward_host="127.0.0.1",
            forward_port=80,
            certificate_id=cert_id,
        )

        # 从 services.yml 加载预定义服务（包含 nginx_ui 等）
        services = load_services()
        for svc in services:
            domain_names = [svc["domain"]]
            target = svc.get("target", "http://127.0.0.1:80")
            websocket = svc.get("websocket", False)

            # 解析 target URL
            parsed = urlparse(target)
            scheme = parsed.scheme or "http"
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or (80 if scheme == "http" else 443)

            advanced = ""
            if websocket:
                advanced = (
                    "proxy_set_header Upgrade $http_upgrade;\n"
                    "proxy_set_header Connection \"upgrade\";\n"
                    "proxy_read_timeout 86400;"
                )

            insert_proxy_host(
                conn,
                domain_names=domain_names,
                forward_scheme=scheme,
                forward_host=host,
                forward_port=port,
                certificate_id=cert_id,
                websocket=websocket,
                advanced_config=advanced,
            )

        # 设置 custom_ssl
        setup_custom_ssl(cert_domain_dir, domain)

        # 插入 knex migration 记录
        _insert_knex_migrations(conn)

        # 从 services.yml 加载流代理（TCP/UDP）
        streams = load_streams()
        for s in streams:
            insert_stream(
                conn,
                incoming_port=s["incoming_port"],
                forwarding_host=s["target_host"],
                forwarding_port=s["target_port"],
                protocol=s.get("protocol", "tcp"),
            )

        # 生成 stream nginx 配置文件
        generate_stream_nginx_configs(conn)

        # 生成 nginx proxy host 配置文件
        # NPM 只在通过 API 操作时才生成配置，启动时不会从数据库重建
        generate_nginx_configs(conn)

        print(f"Database initialized: {DB_FILE}")
        print(f"Custom SSL installed: {CUSTOM_SSL_DIR / CERT_NICE_NAME}")
        print("NPM will read this database on startup.")

    finally:
        conn.close()
        _fix_permissions()


if __name__ == "__main__":
    main()
