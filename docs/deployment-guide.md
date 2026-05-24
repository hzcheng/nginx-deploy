# Tailscale + Nginx Proxy Manager 云服务器部署指南

> **NPM** 是 **Nginx Proxy Manager** 的缩写，一个基于 Web 界面的 Nginx 图形化管理工具。本文档中用 "NPM" 代指它，不要和 Node.js 的包管理器混淆。

## 目录

- [1. 架构概述](#1-架构概述)
- [2. 前置准备](#2-前置准备)
- [3. 项目结构](#3-项目结构)
- [4. 配置文件说明](#4-配置文件说明)
  - [4.1 `.env` 环境变量](#41-env-环境变量)
  - [4.2 `compose.yaml`（主入口）](#42-composeyaml主入口)
  - [4.3 `tailscale/compose.yaml`](#43-tailscalecomposeyaml)
  - [4.4 `npm/compose.yaml`](#44-npmcomposeyaml)
  - [4.5 `derper/compose.yaml`](#45-derpercomposeyaml)
  - [4.6 `derper/Dockerfile`](#46-derperdockerfile)
  - [4.7 `config/services.yml`](#47-configservicesyml)
  - [4.8 `.gitignore`](#48-gitignore)
- [5. 部署步骤](#5-部署步骤)
- [6. Nginx Proxy Manager 配置指南](#6-nginx-proxy-manager-配置指南)
- [7. Derper 配置（可选）](#7-derper-配置可选)
- [8. 家里主机配置](#8-家里主机配置)
- [9. 日常维护](#9-日常维护)
- [10. 故障排查](#10-故障排查)
- [11. 安全建议](#11-安全建议)

---

## 1. 架构概述

### 1.1 整体架构图

```
                                    互联网用户
                                         │
                                         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           云服务器 (公网 IP)                                 │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  acme.sh（证书管理，临时容器）                                       │   │
│  │  • DNS-01 验证（AliDNS API）                                        │   │
│  │  • 签发通配符证书 *.teraai.cn（不覆盖裸域名）                       │   │
│  │  • 证书 → ./certbot/conf/live/teraai.cn/（通过 --install-cert 指定）│   │
│  └──────────────────────┬──────────────────────────────────────────────┘   │
│                         │ 卷挂载: ./certbot/conf:/certs:ro                │
│                         ▼                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Tailscale 容器（网络核心层）                                        │   │
│  │  • 端口映射: 80 → NPM HTTP                                          │   │
│  │  • 端口映射: 443 → NPM HTTPS                                        │   │
│  │  • 端口映射: 127.0.0.1:81 → NPM 管理界面（不暴露公网）              │   │
│  │  • 端口映射: 41641/udp → WireGuard                                  │   │
│  │  • 端口映射: 3478/udp → Derper STUN（可选）                         │   │
│  │  • 创建 /dev/net/tun，加入 tailnet (100.x.y.z)                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              │ network_mode: service:tailscale              │
│                              ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Nginx Proxy Manager                                               │   │
│  │  • TLS 终结（acme.sh 通配符证书）                                   │   │
│  │  • 证书挂载: /certs/live/teraai.cn/（Custom Certificate）          │   │
│  │  • 反向代理到家里服务（通过 tailnet IP）                            │   │
│  │  • 反代 Derper WebSocket（可选）                                    │   │
│  │  • Web UI 管理界面（端口 81，仅 127.0.0.1 可访问）                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              │ network_mode: service:tailscale              │
│                              ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Derper（可选，docker compose --profile derper）                     │   │
│  │  • 监听 HTTP :8080（无证书，TLS 由 NPM 统一处理）                   │   │
│  │  • STUN UDP 3478（直接暴露）                                        │   │
│  │  • --verify-clients（仅允许 tailnet 成员连接）                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                         │
                              Tailscale VPN (WireGuard)
                                         │
┌─────────────────────────────────────────────────────────────────────────────┐
│                              家里主机                                        │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Tailscale (systemd 或 Docker)                                      │   │
│  │  • tailnet IP: 100.a.b.c                                           │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                              │                                              │
│                              ▼                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Nginx / Home Assistant / NAS / 其他服务                            │   │
│  │  • 监听 127.0.0.1 或局域网 IP                                       │   │
│  │  • 不直接暴露在公网                                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 流量路径说明

| 场景 | 路径 |
|------|------|
| 用户访问云服务器首页 | `用户 → HTTPS 443 → NPM → 静态页/默认站点` |
| 用户访问家里服务 | `用户 → HTTPS 443 → NPM → tailnet (100.x.x.x) → 家里服务` |
| Tailscale P2P 直连 | `云服务器 ↔ UDP 41641 ↔ 家里` (WireGuard) |
| Tailscale DERP 中继 | `云服务器 ↔ Derper ↔ 家里` (TCP/WebSocket over HTTPS) |
| 管理员配置 NPM | `管理员 → https://nginx.teraai.cn → NPM Web UI`（HTTPS） |
| 证书自动续签 | `acme.sh --cron` → 同步到 NPM → `docker compose restart npm` |
| 裸域名访问 | `teraai.cn` 不在证书覆盖范围，建议用 `www.teraai.cn` |

### 1.3 关键技术决策

| 决策 | 选择 | 原因 |
|------|------|------|
| Tailscale 部署方式 | Docker 容器 | 纯容器化，无 systemd 依赖 |
| NPM 部署方式 | Docker 容器 + `network_mode: service:tailscale` | 共享 tailnet，可直接访问 100.x.x.x |
| NPM 管理界面访问 | `https://nginx.teraai.cn`（公网 HTTPS） | 首次启动前预填充数据库，无需手动 |
| NPM 版本策略 | 锁定到具体版本（如 `2.11.3`） | 避免 `latest` 漂移，保证预填充数据库兼容 |
| SSL 证书管理 | acme.sh + AliDNS DNS-01 | 一个通配符证书覆盖所有子域名，自动续签 |
| 证书导入方式 | 预填充 SQLite + mount 证书文件 | 不依赖 NPM 内部 API，100% 可靠 |
| Derper TLS | 由 NPM 统一终结 | 证书集中管理，Derper 跑纯 HTTP |
| Derper STUN | UDP 3478 直接暴露 | Nginx 不支持 UDP 代理，必须直连 |
| 家里服务 TLS | 不需要独立公网证书 | 云服务器 NPM 已提供 HTTPS，云→家走 Tailscale 加密隧道 |

---

## 2. 前置准备

### 2.1 云服务器要求

- [ ] 公网 IP（IPv4 或 IPv6）
- [ ] Ubuntu 22.04+ / Debian 12+ / 其他支持 Docker 的 Linux
- [ ] 至少 1 vCPU / 1GB RAM（Derper 会额外占用一些内存）
- [ ] 防火墙放行端口：`80`、`443`、`41641/udp`、`3478/udp`（Derper 可选）
- [ ] **81 端口不需要放行公网**，管理界面通过 `https://nginx.teraai.cn` 访问

### 2.2 域名要求

- [ ] 域名：`teraai.cn`
- [ ] DNS A 记录指向云服务器公网 IP：
  - `www.teraai.cn` → 云服务器 IP（你的导航网站）
  - `nginx.teraai.cn` → 云服务器 IP（NPM 管理界面）
  - `derper.teraai.cn` → 云服务器 IP（Derper 入口，可选）
- [ ] 如果家里服务想用子域名，也需要相应 DNS 记录：
  - `ha.teraai.cn` → 云服务器 IP（NPM 反代到家里 Home Assistant）

### 2.3 AliDNS API 密钥（用于自动签发 SSL 证书）

> 本项目使用 **acme.sh + AliDNS API** 通过 DNS-01 验证自动签发通配符证书 `*.teraai.cn`。

- [ ] 登录 [阿里云控制台](https://ram.console.aliyun.com/users) → 创建 RAM 用户
- [ ] 为该用户添加权限策略：`AliyunDNSFullAccess`
- [ ] 创建 AccessKey，记录：

### 2.4 Tailscale 账号

- [ ] 注册 [Tailscale](https://login.tailscale.com/) 账号
- [ ] 生成 Auth Key：
  1. 访问 https://login.tailscale.com/admin/settings/keys
  2. 点击 **Generate auth key...**
  3. 配置：
     - **Reusable**: ✅ Yes（云服务器重启后可复用）
     - **Ephemeral**: ❌ No（状态持久化，避免重启后 IP 变化）
     - **Pre-approved**: ✅ Yes（跳过设备审批）
  4. 复制生成的 key（格式：`tskey-auth-xxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxx`）

### 2.5 安装 Docker

如果云服务器尚未安装 Docker：

```bash
# 一键安装 Docker
curl -fsSL https://get.docker.com | sh

# 将当前用户加入 docker 组（需重新登录生效）
sudo usermod -aG docker $USER

# 验证
docker --version
docker compose version
```

---

## 3. 项目结构

```
nginx-deploy/
├── compose.yaml                # 主入口：include 所有子服务
├── .env                        # 环境变量（敏感信息，不提交 Git）
├── .env.example                # 环境变量模板
├── .gitignore
├── docs/
│   ├── deployment-guide.md     # 本文档
│   └── ssl-cert-plan.md        # SSL 方案设计文档
├── scripts/                    # 一键部署与证书管理脚本
│   ├── deploy.sh               # 一键部署主入口
│   ├── init-db.py              # 预生成 NPM SQLite 数据库
│   ├── issue-cert.sh           # 首次签发 SSL 证书
│   ├── renew-cert.sh           # 自动续签证书
│   └── sync-cert-to-npm.sh     # 同步证书到 NPM 并 restart
├── config/
│   └── services.yml            # 预定义的基础服务（可选）
├── certbot/                    # acme.sh 证书管理
│   ├── acme-home/              # acme.sh 账号与状态
│   └── conf/                   # 签发后的证书文件
├── tailscale/                  # Tailscale 网络核心
│   ├── compose.yaml            # Tailscale 服务定义
│   └── state/                  # tailscaled.state（自动创建）
├── npm/                        # Nginx Proxy Manager
│   ├── compose.yaml            # NPM 服务定义
│   ├── data/                   # 数据库 + 配置（自动创建）
│   └── letsencrypt/            # NPM 内部证书目录
└── derper/                     # Derper DERP 中继（可选）
    ├── compose.yaml            # Derper 服务定义
    └── Dockerfile              # Derper 镜像构建文件
```

---

## 4. 配置文件说明

### 4.1 `.env` 环境变量

```bash
# ============================================
# 基础配置
# ============================================

# 云服务器在 Tailscale 中的主机名
TAILSCALE_HOSTNAME=cloud-server

# Tailscale Auth Key（从 https://login.tailscale.com/admin/settings/keys 获取）
TS_AUTHKEY=tskey-auth-xxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxx

# 是否接受 Tailscale DNS
TS_ACCEPT_DNS=true

# ============================================
# NPM 版本锁定
# ============================================

# 锁定 NPM 版本，保证预填充数据库兼容
# 升级前需重新测试 init-db.py
NPM_IMAGE_TAG=2.11.3

# ============================================
# SSL 证书配置（acme.sh + AliDNS）
# ============================================

# 主域名（通配符证书仅覆盖 *.teraai.cn，不覆盖裸域名 teraai.cn）
DOMAIN=teraai.cn

# Let's Encrypt 注册邮箱
LETSENCRYPT_EMAIL=admin@teraai.cn

# 阿里云 DNS API 密钥（用于 DNS-01 验证）
# 从 https://ram.console.aliyun.com/users 获取
ALI_KEY=LTAIxxxxxxxxxxxxxxxx
ALI_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ============================================
# Derper 配置（可选）
# ============================================

# Derper 域名
DERP_DOMAIN=derp.teraai.cn

# Derper HTTP 内部端口（不需要暴露到宿主机，NPM 反代）
DERP_HTTP_PORT=8080

# Derper STUN UDP 端口（必须暴露到宿主机）
DERP_STUN_PORT=3478
```

### 4.2 `compose.yaml`（主入口）

主文件只负责 `include` 各子服务，一目了然：

```yaml
include:
  - ./tailscale/compose.yaml
  - ./npm/compose.yaml
  - ./derper/compose.yaml
```

> 💡 `include` 合并后所有服务在同一个命名空间，跨文件的 `network_mode: service:tailscale` 引用完全正常。

### 4.3 `tailscale/compose.yaml`

Tailscale 作为网络核心层，所有公网端口在此映射：

```yaml
services:
  tailscale:
    image: tailscale/tailscale:latest
    container_name: tailscale
    hostname: ${TAILSCALE_HOSTNAME:-cloud-server}
    restart: unless-stopped
    cap_add:
      - NET_ADMIN
      - NET_RAW
      - SYS_MODULE
    devices:
      - /dev/net/tun:/dev/net/tun
    sysctls:
      - net.ipv4.ip_forward=1
      - net.ipv6.conf.all.forwarding=1
    volumes:
      - ./tailscale/state:/var/lib/tailscale
    environment:
      - TS_AUTHKEY=${TS_AUTHKEY:-}
      - TS_STATE_DIR=/var/lib/tailscale
      - TS_USERSPACE=false
      - TS_ACCEPT_DNS=${TS_ACCEPT_DNS:-true}
    ports:
      - "80:80"
      - "443:443"
      - "127.0.0.1:81:81"
      - "41641:41641/udp"
      - "${DERP_STUN_PORT:-3478}:${DERP_STUN_PORT:-3478}/udp"
```

### 4.4 `npm/compose.yaml`

NPM 共享 Tailscale 的网络命名空间，可直接访问 tailnet IP：

```yaml
services:
  npm:
    image: jc21/nginx-proxy-manager:${NPM_IMAGE_TAG:-latest}
    container_name: npm
    restart: unless-stopped
    network_mode: service:tailscale
    volumes:
      - ./npm/data:/data
      - ./npm/letsencrypt:/etc/letsencrypt
      - ./certbot/conf:/certs:ro
    depends_on:
      - tailscale
    environment:
      - DB_SQLITE_FILE=/data/database.sqlite
```

> ⚠️ **务必使用 `${NPM_IMAGE_TAG}` 锁定版本**，不要用 `latest`。预填充数据库脚本依赖特定表结构。

### 4.5 `derper/compose.yaml`

Derper 是可选服务，带有 `profiles: [derper]`，默认不启动。需要时会自动 multi-stage build：

```yaml
services:
  derper:
    build:
      context: .
    container_name: derper
    restart: unless-stopped
    network_mode: service:tailscale
    profiles:
      - derper
    environment:
      - DERP_HOSTNAME=${DERP_DOMAIN:-}
      - DERP_HTTP_PORT=${DERP_HTTP_PORT:-8080}
    command: >
      /bin/sh -c '
        if [ -z "$${DERP_HOSTNAME}" ]; then
          echo "ERROR: DERP_DOMAIN is not set in .env" &&
          exit 1;
        fi &&
        echo "Starting derper on HTTP port $${DERP_HTTP_PORT}..." &&
        derper
        --hostname=$${DERP_HOSTNAME}
        --certmode=manual
        --certdir=/tmp/certs
        --stun=true
        --stun-port=${DERP_STUN_PORT:-3478}
        --a=:$${DERP_HTTP_PORT}
        --verify-clients
      '
    depends_on:
      - tailscale
```

### 4.6 `derper/Dockerfile`

```dockerfile
# 构建阶段
FROM golang:1.26-alpine AS builder
WORKDIR /app

# 设置 Go 代理（国内环境可加速）
RUN go env -w GOPROXY=https://goproxy.cn,direct 2>/dev/null || true

# 安装 derper
RUN go install tailscale.com/cmd/derper@latest

# 运行阶段
FROM alpine:3.20
RUN apk add --no-cache ca-certificates
COPY --from=builder /go/bin/derper /usr/local/bin/derper
ENTRYPOINT ["derper"]
```

### 4.7 `config/services.yml`（可选，预定义基础服务）

首次部署时，`deploy.sh` 会读取此文件，由 `init-db.py` 预生成数据库时一并创建预定义的 Proxy Host。

```yaml
services:
  - name: nginx_ui
    domain: nginx.teraai.cn
    target: http://127.0.0.1:81

  - name: home_assistant
    domain: ha.teraai.cn
    target: http://100.101.7.100:8123
    websocket: true
```

> 如果你不需要预定义，可以留空或删除此文件。后续所有服务都通过 NPM Web UI 手动添加。

### 4.8 `.gitignore`

```
.env
tailscale/state/*
npm/data/*
npm/letsencrypt/*
certbot/acme-home/*
certbot/conf/*
!*/.gitkeep
```

---

## 5. 部署步骤（一键部署）

### 5.1 克隆项目并进入目录

```bash
cd /opt  # 或你喜欢的目录
git clone <仓库地址> nginx-deploy
cd nginx-deploy
```

### 5.2 创建环境变量文件

```bash
cp .env.example .env
nano .env  # 或 vim，按需编辑
```

编辑 `.env`，填入你的实际值：

```bash
TAILSCALE_HOSTNAME=my-cloud-server
TS_AUTHKEY=tskey-auth-xxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxx
TS_ACCEPT_DNS=true

DOMAIN=teraai.cn
LETSENCRYPT_EMAIL=admin@teraai.cn
ALI_KEY=LTAIxxxxxxxxxxxxxxxx
ALI_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

DERP_DOMAIN=derper.teraai.cn
DERP_HTTP_PORT=8080
DERP_STUN_PORT=3478
```

### 5.3 一键部署

```bash
./scripts/deploy.sh
```

`deploy.sh` 会自动完成以下步骤：

1. 启动 `tailscale` 容器，等待自动认证
2. 使用 `acme.sh` 签发通配符证书 `*.teraai.cn`（不覆盖裸域名）
3. **预填充 NPM 数据库**：
   - 运行 `scripts/init-db.py`，生成预配置的 `database.sqlite`
   - 数据库包含默认用户、通配符证书记录、基础 Proxy Host
   - 证书文件复制到 `./npm/data/custom_ssl/npm-1/`
4. 启动 `npm` 容器，NPM 启动后直接读取预配置，无需任何手动操作
5. **如果 `ENABLE_DERPER=true`**：自动 build 并启动 Derper
6. 设置 cron 自动续签

部署完成后，你会看到输出信息：

```
✅ 部署完成！
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌐 管理界面: https://nginx.teraai.cn
📧 默认账号: admin@example.com
🔑 默认密码: changeme
⚠️  请立即登录并修改密码
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 5.4 验证部署

```bash
# 查看所有服务状态
docker compose ps

# 查看各服务日志
docker compose logs -f tailscale
docker compose logs -f npm
```

### 5.5 访问 NPM 管理界面

部署完成后，NPM 管理界面通过 **HTTPS** 访问：

```
https://nginx.teraai.cn
```

**⚠️ 重要安全提醒：**
- **81 端口不暴露在公网**，不要在你的云服务器防火墙中放行 81 端口
- 管理界面只能通过 `https://nginx.teraai.cn` 访问（走 443 端口，由 NPM 自身反代）
- 首次登录后**务必立即修改默认密码**

---

## 6. Nginx Proxy Manager 配置指南

### 6.1 SSL 证书说明

本项目**不依赖 NPM 内置的 Let's Encrypt 功能**。证书由独立的 `acme.sh` 管理：

- **签发方式**：acme.sh + AliDNS API + DNS-01 验证
- **证书类型**：ECDSA P-256 通配符证书（`*.teraai.cn`）
- **覆盖范围**：覆盖所有子域名（`nginx.teraai.cn`、`derper.teraai.cn`、`ha.teraai.cn` 等）
- **不覆盖**：裸域名 `teraai.cn`。如需访问裸域名，建议 DNS 添加 `www` 子域名或使用 `www.teraai.cn`
- **自动续签**：`renew-cert.sh` 每周运行一次，`acme.sh --cron` 自动检测并续签

#### 证书文件位置

宿主机上：
```
certbot/conf/live/teraai.cn/
├── fullchain.pem   # 证书 + 中间证书
└── privkey.pem     # 私钥
```

NPM 容器内（通过卷挂载）：
```
/certs/live/teraai.cn/
```

#### 首次部署时证书如何进入 NPM？

**不依赖 NPM 内部 API**。`deploy.sh` 脚本通过以下方式自动完成：

1. `issue-cert.sh` 签发证书到 `./certbot/conf/live/teraai.cn/`
2. `init-db.py` 预生成 NPM 的 `database.sqlite`，包含：
   - 默认用户 `admin@example.com`
   - 通配符证书记录（指向 `./custom_ssl/npm-1/`）
   - 基础 Proxy Host（`nginx.teraai.cn`、`www.teraai.cn`）
3. 证书文件复制到 `./npm/data/custom_ssl/npm-1/`
4. NPM 容器启动后自动识别，无需任何手动操作

#### 自动续签

`renew-cert.sh` 每周运行一次：
1. `acme.sh --cron` 检测并续签证书
2. 新证书复制到 `./npm/data/custom_ssl/npm-1/`
3. `docker compose restart npm` 重启加载新证书

> ⚠️ **NPM 版本已锁定**，升级版本前需重新测试 `init-db.py` 的兼容性。

### 6.2 添加云服务器默认站点

`www.teraai.cn` 作为你的导航页/首页，首次部署时已由脚本自动创建。如果你需要修改：

1. 登录 `https://nginx.teraai.cn`
2. 点击 **Hosts** → **Proxy Hosts**
3. 找到 `www.teraai.cn` 条目，点击编辑
4. 根据你的实际情况修改 Forward 目标：
   - **静态网页**：Forward 到云服务器上的某个本地服务
   - **反代到家里**：Forward 到家里 Tailscale IP:端口
   - **其他云服务商**：Forward 到对应地址
5. **SSL** 标签页：选择 `*.teraai.cn` 通配符证书（Custom）
6. 点击 **Save**

### 6.3 添加家里服务的反向代理

假设家里有一台 Home Assistant 运行在 Tailscale IP `100.a.b.c:8123`：

1. 登录 `https://nginx.teraai.cn`
2. 点击 **Hosts** → **Proxy Hosts** → **Add Proxy Host**
3. 填写：
   - **Domain Names**: `ha.teraai.cn`
   - **Scheme**: `http`
   - **Forward Hostname / IP**: `100.a.b.c`
   - **Forward Port**: `8123`
4. **SSL** 标签页：
   - **SSL Certificate**: 选择 `*.teraai.cn` 通配符证书（Custom）
   - **Force SSL**: ✅
   - **HTTP/2 Support**: ✅
5. **Advanced** 标签页（可选，某些服务需要）：

如果家里服务需要 WebSocket 支持（如 Home Assistant），在 Advanced 标签页添加：

```nginx
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
proxy_read_timeout 86400;
```

6. 点击 **Save**

现在访问 `https://ha.teraai.cn`，流量路径是：

```
你 → https://ha.teraai.cn → 云服务器 NPM (TLS 终结)
  → tailnet (100.a.b.c:8123) → 家里 Home Assistant
```

### 6.4 NPM 管理界面域名

`nginx.teraai.cn` 反代到 NPM 自身的管理界面（端口 81），**首次部署时已由脚本自动创建**。

如果你需要手动查看或修改配置：

1. 登录 `https://nginx.teraai.cn`
2. **Hosts** → **Proxy Hosts**
3. 找到 `nginx.teraai.cn` 条目：
   - **Forward Hostname / IP**: `127.0.0.1`
   - **Forward Port**: `81`
4. **SSL** 标签页：
   - **SSL Certificate**: `*.teraai.cn` 通配符证书（Custom）
   - **Force SSL**: ✅
   - **HTTP/2 Support**: ✅

> 🔒 管理界面始终通过 `https://nginx.teraai.cn` 访问，81 端口不暴露在公网。

### 6.5 添加更多家里服务

按照同样的方式添加其他服务。所有子域名**共用同一个通配符证书**：

| 服务 | 域名 | 目标 IP:端口 | 特殊配置 |
|------|------|-------------|---------|
| Home Assistant | `ha.teraai.cn` | `100.a.b.c:8123` | WebSocket |
| NAS 管理页 | `nas.teraai.cn` | `100.a.b.c:5000` | - |
| 个人博客 | `blog.teraai.cn` | `100.a.b.c:8080` | - |
| 开发环境 | `dev.teraai.cn` | `100.a.b.c:3000` | WebSocket |

> 💡 **推荐用子域名**（`ha.teraai.cn`）而不是路径（`teraai.cn/ha`），因为路径反代可能会遇到 cookie path、资源引用等问题。
> 💡 **SSL 证书不需要单独申请**，所有 `*.teraai.cn` 子域名都使用同一个通配符证书。

### 6.6 配置你的导航页（www.teraai.cn）

`www.teraai.cn` 是你自己的网站导航，**首次部署时已由脚本自动创建基础反代**。

如果你需要修改：

1. 登录 `https://nginx.teraai.cn`
2. **Hosts** → **Proxy Hosts**
3. 找到 `www.teraai.cn` 条目并编辑
4. 根据你的实际情况修改 Forward 目标：
   - **静态网页**：Forward 到云服务器上的某个本地服务/目录
   - **反代到家里**：Forward 到家里 Tailscale IP:端口
   - **其他云服务商**：Forward 到对应地址
5. **SSL** 标签页：选择 `*.teraai.cn` 通配符证书（Custom）

> 这个站点完全由你掌控，按你的需求配置即可。

---

## 7. Derper 配置（可选）

### 7.1 启动 Derper

```bash
# 带 derper profile 启动
docker compose --profile derper up -d --build

# 查看日志
docker compose logs -f derper
```

### 7.2 在 NPM 中添加 Derper 反代

1. 登录 NPM 管理界面
2. **Hosts** → **Proxy Hosts** → **Add Proxy Host**
3. 填写：
   - **Domain Names**: `derper.teraai.cn`
   - **Scheme**: `http`
   - **Forward Hostname / IP**: `127.0.0.1`
   - **Forward Port**: `8080`（`DERP_HTTP_PORT` 的值）
4. **SSL** 标签页：
   - **SSL Certificate**: 选择 `*.teraai.cn` 通配符证书（Custom）
   - **Force SSL**: ✅
5. **Advanced** 标签页添加（WebSocket 支持）：

```nginx
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
proxy_read_timeout 86400;
proxy_buffering off;
```

6. 点击 **Save**

### 7.3 在 Tailscale ACL 中注册自定义 DERP

访问 https://login.tailscale.com/admin/acls/file，在 JSON 中添加：

```json
{
  "derpMap": {
    "OmitDefaultRegions": false,
    "Regions": {
      "900": {
        "RegionID": 900,
        "RegionCode": "myderp",
        "RegionName": "My Cloud DERP",
        "Nodes": [
          {
            "Name": "1",
            "RegionID": 900,
            "HostName": "derper.teraai.cn",
            "DERPPort": 443,
            "InsecureForTests": false
          }
        ]
      }
    }
  }
}
```

保存后，Tailscale 会自动将 `900` 号区域作为可用 DERP 节点。你的设备在无法 P2P 直连时，会通过这个节点中继。

### 7.4 验证 Derper 是否工作

```bash
# 在云服务器上查看 derper 日志
docker compose logs -f derper

# 在家里主机上查看当前使用的 DERP
tailscale netcheck
```

如果看到 `DERP: 900`（或你设置的 RegionID），说明自定义 DERP 已生效。

### 7.5 关闭 Derper

```bash
# 停止并删除 Derper 容器
docker compose --profile derper down

# 或者修改 .env 中 ENABLE_DERPER=false，然后重新运行 deploy.sh
```

---

## 8. 家里主机配置

### 8.1 安装 Tailscale

```bash
# Linux
curl -fsSL https://tailscale.com/install.sh | sh

# macOS / Windows / iOS / Android
# 下载客户端: https://tailscale.com/download
```

### 8.2 登录并加入 tailnet

```bash
sudo tailscale up
```

访问输出的 URL 完成认证。

### 8.3 查看 Tailscale IP

```bash
tailscale ip -4
# 输出: 100.a.b.c
```

把这个 IP 填入 NPM 的反向代理配置中。

### 8.4（可选）宣告家里局域网路由

如果你希望云服务器也能访问家里局域网的其他设备（如打印机、路由器）：

```bash
# 假设家里局域网是 192.168.1.0/24
sudo tailscale up --advertise-routes=192.168.1.0/24 --accept-dns=false
```

然后在 Tailscale 后台开启路由：**Machines** → 点击家里主机 → **Edit route settings** → 开启对应路由。

### 8.5 家里服务部署

家里的 Nginx / Home Assistant / NAS 等按你自己的习惯部署即可。关键是：

- 服务监听在 `127.0.0.1` 或局域网 IP 上（不要暴露在公网）
- Tailscale 已安装并在线
- 记住各服务的端口号，填入 NPM 反代配置

> 🔒 **家里不需要独立 HTTPS 证书**。云服务器 NPM 已经提供 HTTPS，云→家走 Tailscale WireGuard 加密，双层安全。

---

## 9. 日常维护

### 9.1 查看服务状态

```bash
# 所有服务（一目了然）
docker compose ps

# 各服务日志
docker compose logs -f tailscale
docker compose logs -f npm

# Derper 日志（如果已启动）
docker compose logs -f derper
```

### 9.2 重启服务

```bash
# 重启核心服务
docker compose restart

# 重启单个服务
docker compose restart npm

# 重启 Derper（如果已启动）
docker compose --profile derper restart derper
```

### 9.3 更新镜像

```bash
# 拉取最新镜像（核心服务）
docker compose pull

# 重建并启动 Derper（自动 build）
docker compose --profile derper up -d --build

# 全部重建（核心 + Derper，先拉取最新镜像）
docker compose pull && docker compose --profile derper up -d --build
```

### 9.4 备份

定期备份以下目录：

```bash
# 一键备份全部（含 .env）
tar czf nginx-deploy-backup-$(date +%Y%m%d).tar.gz \
  .env \
  npm/data \
  certbot/conf \
  certbot/acme-home \
  tailscale/state
```

### 9.5 恢复

```bash
# 解压备份到项目根目录
tar xzf nginx-deploy-backup-20260524.tar.gz

# 确保 .env 已恢复后，重启所有服务
docker compose up -d
```

---

## 10. 故障排查

### 10.1 Tailscale 无法认证

**现象**：`docker logs tailscale` 显示认证失败或反复重试。

**排查**：

```bash
# 检查 Auth Key 是否正确
grep TS_AUTHKEY .env

# 手动触发认证
docker exec -it tailscale tailscale up --authkey=tskey-auth-xxx

# 查看详细状态
docker exec tailscale tailscale status
docker exec tailscale tailscale netcheck
```

### 10.2 SSL 证书问题

**现象**：访问 `https://xxx.teraai.cn` 时浏览器提示证书错误，或证书已过期。

**排查步骤**：

1. **确认证书是否有效**：
   ```bash
   openssl x509 -in certbot/conf/live/teraai.cn/fullchain.pem -noout -dates
   ```

2. **手动执行续签**：
   ```bash
   ./scripts/renew-cert.sh
   ```

3. **检查 acme.sh 日志**：
   ```bash
   docker run --rm -v ./certbot/acme-home:/acme.sh neilpang/acme.sh:latest --list
   ```

4. **确认 NPM 中的证书是否已同步**：
   ```bash
   # 查看 NPM custom_ssl 目录
   ls -la npm/data/custom_ssl/
   ```

5. **检查 AliDNS API 密钥**：
   ```bash
   grep ALI .env
   ```

### 10.3 无法访问家里服务

**现象**：`https://ha.teraai.cn` 返回 502 Bad Gateway。

**排查步骤**：

1. **确认家里 Tailscale 在线**：
   ```bash
   # 在云服务器上执行
   docker exec tailscale tailscale status
   # 确认家里主机出现在列表中
   ```
2. **确认家里 IP 可达**：
   ```bash
   # 在云服务器上执行
   docker exec tailscale tailscale ping 100.a.b.c
   docker exec tailscale wget -qO- http://100.a.b.c:8123
   ```
3. **确认家里服务监听正确**：
   ```bash
   # 在家里主机上执行
   sudo ss -tlnp | grep 8123
   # 确认监听在 0.0.0.0:8123 或 tailscale IP:8123，不是 127.0.0.1:8123
   ```
4. **检查 NPM 配置**：Forward Hostname / IP 是否正确？Scheme 是 http 还是 https？

### 10.4 Derper 无法连接

**现象**：`tailscale netcheck` 没有显示自定义 DERP。

**排查**：

```bash
# 检查 derper 是否运行
docker compose ps

# 检查 derper 日志
docker compose logs derper

# 测试 derper 的 HTTPS 可达性（从外部）
curl -I https://derper.teraai.cn

# 检查 Tailscale ACL 是否正确保存
# 访问 https://login.tailscale.com/admin/acls/file 确认
```

### 10.5 NPM 管理界面无法访问

**现象**：`https://nginx.teraai.cn` 无法打开。

**排查**：

1. **确认域名解析正确**：
   ```bash
   dig nginx.teraai.cn
   # 确认指向云服务器公网 IP
   ```

2. **确认 443 端口可达**：
   ```bash
   curl -I https://nginx.teraai.cn
   # 如果证书错误但返回 HTTP 200，说明服务正常
   ```

3. **检查 NPM 是否运行**：`docker compose ps`

4. **检查 NPM 日志**：`docker compose logs npm`

5. **确认 `nginx.teraai.cn` 的 Proxy Host 配置存在**：
   ```bash
   # 在宿主机上查看 NPM 数据库中的配置
   # 或者直接访问 http://127.0.0.1:81 检查
   ```

---

## 11. 安全建议

### 11.1 NPM 管理界面

- `nginx.teraai.cn` 暴露在公网（走 443 HTTPS），NPM 有登录密码保护
- **81 端口不暴露公网**，管理界面只能通过 HTTPS 域名访问
- ✅ 首次登录后立即修改默认密码
- ✅ 考虑启用 NPM 的 Two-Factor Authentication
- ✅ 在 Tailscale ACL 中可以进一步限制设备访问权限

### 11.5 文件权限

```bash
# .env 包含 AliDNS API 密钥，必须限制访问权限
chmod 600 .env

# NPM 数据目录可能需要调整属主（NPM 容器内 UID 可能不同）
mkdir -p npm/data npm/letsencrypt
docker compose up -d npm
# 如遇到权限问题，查看容器日志后调整：
# sudo chown -R 911:911 npm/data
```

### 11.6 防火墙配置

如果云服务器使用 UFW：
```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 41641/udp
# 81 端口不要放行！
# sudo ufw deny 81/tcp
```

### 11.7 Tailscale Auth Key 过期

Tailscale Auth Key 默认 90 天过期。到期后：
1. 在 https://login.tailscale.com/admin/settings/keys 重新生成
2. 更新 `.env` 中的 `TS_AUTHKEY`
3. 删除 `./tailscale/state/` 下的旧状态文件
4. 重启容器：`docker compose restart tailscale`

### 11.2 Tailscale

- ✅ Auth Key 设置为 **Reusable + Not Ephemeral**，避免重启后 IP 变化
- ✅ 在 Tailscale 后台开启 **Device Authorization**（如果团队成员多）
- ✅ 定期检查 **Machines** 列表，移除不认识的设备
- ✅ 使用 ACL 限制设备之间的访问权限

### 11.3 Derper

- ✅ 始终开启 `--verify-clients`，防止外部滥用
- ✅ 如果不需要，保持 Derper 关闭（`docker compose --profile derper down`）

### 11.4 家里服务

- ✅ 家里服务不要暴露在公网（不要映射路由器端口）
- ✅ 敏感服务（如 NAS 管理页）在 NPM 中配置 **Access List** 限制 IP

---

*文档版本: 2.0*
*最后更新: 2026-05-24*
