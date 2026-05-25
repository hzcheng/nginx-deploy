# nginx-deploy

Tailscale + Nginx Proxy Manager + acme.sh 一键部署方案。

一个证书（`*.teraai.cn`）覆盖所有子域名，免费自动续签，零手动配置。

---

## 项目简介

本项目用于在**云服务器**上快速部署一套完整的反向代理 + VPN 网关：

- **Tailscale**：加密隧道，云服务器 ↔ 家里内网直连
- **Nginx Proxy Manager**：Web UI 管理反向代理、SSL 证书
- **acme.sh**：自动签发 Let's Encrypt 通配符证书
- **Derper**（可选）：Tailscale 自定义 DERP 中继

```
用户 → HTTPS 443 → 云服务器 NPM → Tailscale 隧道 → 家里服务
```

**核心设计**：
- 只签一个通配符证书 `*.teraai.cn`，所有子域名共用
- 首次部署**完全自动化**，无需手动登录 NPM UI 上传证书
- 服务模块化（tailscale/npm/derper 各自独立）
- 81 端口不暴露公网，管理界面通过 `https://nginx.teraai.cn` 访问

---

## 目录结构

```
nginx-deploy/
├── compose.yaml              # 主入口（include 子服务）
├── .env                      # 环境变量（敏感信息）
├── .env.example              # 环境变量模板
├── README.md                 # 本文件
├── docs/
│   ├── deployment-guide.md   # 详细技术文档
│   └── ssl-cert-plan.md      # SSL 方案设计
├── scripts/
│   ├── deploy.sh             # 一键部署
│   ├── init-db.py            # 预生成 NPM 数据库
│   ├── issue-cert.sh         # 首次签发证书
│   ├── renew-cert.sh         # 自动续签
│   ├── sync-cert-to-npm.sh   # 证书同步
│   ├── uninstall.sh          # 一键卸载/清理
│   └── lib/
│       └── acme-common.sh    # 证书脚本共享库
├── config/
│   └── services.yml          # 预定义服务（可选）
├── certbot/                  # acme.sh 证书目录
├── tailscale/                # Tailscale 状态
├── npm/                      # NPM 数据
└── derper/                   # Derper 构建上下文
```

---

## 前置条件

### 1. 云服务器

- **系统**：Ubuntu 22.04+ / Debian 12+
- **配置**：至少 1 vCPU / 1GB RAM
- **公网 IP**：IPv4 或 IPv6
- **端口**：防火墙放行 `80`、`443`、`41641/udp`
- **81 端口不需要放行公网**

### 2. 域名

- 拥有一个域名（如 `teraai.cn`）
- DNS A 记录指向云服务器公网 IP：
  - `www.teraai.cn` → 云服务器 IP
  - `nginx.teraai.cn` → 云服务器 IP
  - `*.teraai.cn` → 云服务器 IP（泛解析，可选）

### 3. 阿里云 DNS API 密钥

> 用于 acme.sh 通过 DNS-01 验证自动签发证书

1. 登录 [阿里云 RAM 控制台](https://ram.console.aliyun.com/users)
2. 创建 RAM 用户，添加权限策略 `AliyunDNSFullAccess`
3. 创建 AccessKey，记录 **AccessKey ID** 和 **AccessKey Secret**

### 4. Tailscale 账号

1. 注册 [Tailscale](https://login.tailscale.com/) 账号
2. 进入 [Settings → Keys](https://login.tailscale.com/admin/settings/keys)
3. 点击 **Generate auth key...**
   - **Reusable**: ✅ Yes
   - **Ephemeral**: ❌ No
   - **Pre-approved**: ✅ Yes
4. 复制生成的 key（格式：`tskey-auth-xxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxx`）

### 5. 安装 Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# 重新登录后验证
docker --version
docker compose version
```

### 6. 安装 Python 3

> init-db.py 需要 Python 3（通常 Ubuntu/Debian 已预装）

```bash
python3 --version
```

---

## 快速开始

### 1. 克隆项目

```bash
cd /opt  # 或你喜欢的目录
git clone <仓库地址> nginx-deploy
cd nginx-deploy
```

### 2. 配置环境变量

```bash
cp .env.example .env
nano .env  # 或 vim
```

填写以下内容（**所有带 `xxx` 的必须替换**）：

```bash
# Tailscale
TAILSCALE_HOSTNAME=cloud-server
TS_AUTHKEY=tskey-auth-xxxxxxxxxxxx-xxxxxxxxxxxxxxxxxxxxxxxx

# SSL 证书
DOMAIN=teraai.cn
LETSENCRYPT_EMAIL=admin@teraai.cn
ALI_KEY=LTAIxxxxxxxxxxxxxxxx
ALI_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# NPM 版本（不建议修改，升级前需重新测试 init-db.py）
NPM_IMAGE_TAG=2.11.3

# Derper（可选）
ENABLE_DERPER=false
DERP_DOMAIN=derper.teraai.cn
DERP_HTTP_PORT=8080
DERP_STUN_PORT=3478
```

> ⚠️ **`.env` 文件包含敏感密钥，务必设置权限：**
> ```bash
> chmod 600 .env
> ```

### 3. 一键部署

```bash
./scripts/deploy.sh
```

`deploy.sh` 会自动完成以下步骤：

1. 启动 Tailscale 容器，等待自动认证
2. 用 acme.sh + AliDNS 签发 `*.teraai.cn` 通配符证书
3. 运行 `init-db.py` 预生成 NPM 数据库（含默认用户、证书、Proxy Host）
4. 启动 NPM 容器（直接读取预配置，无需手动操作）
5. 按需启动 Derper（如果 `ENABLE_DERPER=true`）
6. 设置 cron 每周一 3 点自动续签

部署完成后，你会看到：

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ 部署完成！
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌐 管理界面: https://nginx.teraai.cn
📧 默认账号: admin@example.com
⚠️  首次登录后请立即修改默认密码
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 4. 验证部署

```bash
# 查看所有服务状态
docker compose ps

# 查看各服务日志
docker compose logs -f tailscale
docker compose logs -f npm
```

访问 `https://nginx.teraai.cn`，用默认账号登录，**立即修改密码**。

---

## 添加代理服务

部署完成后，你可以通过 NPM Web UI 随时添加新的反向代理。

### 示例：添加家里 Home Assistant

假设家里 Home Assistant 运行在 Tailscale IP `100.101.7.100:8123`：

1. 登录 `https://nginx.teraai.cn`
2. 点击 **Hosts → Proxy Hosts → Add Proxy Host**
3. 填写：
   - **Domain Names**: `ha.teraai.cn`
   - **Scheme**: `http`
   - **Forward Hostname / IP**: `100.101.7.100`
   - **Forward Port**: `8123`
4. **SSL** 标签页：
   - **SSL Certificate**: 选择 `*.teraai.cn` 通配符证书
   - **Force SSL**: ✅
   - **HTTP/2 Support**: ✅
5. 点击 **Save**

> 所有子域名共用同一个通配符证书，不需要单独申请。

---

## 预定义服务（可选）

如果你希望在首次部署时就自动创建某些 Proxy Host，编辑 `config/services.yml`：

```yaml
services:
  - name: home_assistant
    domain: ha.teraai.cn
    target: http://100.101.7.100:8123
    websocket: true
```

然后重新运行 `./scripts/deploy.sh`，`init-db.py` 会自动创建这些反代。

---

## 启用 Derper（可选）

Derper 是 Tailscale 的自定义 DERP 中继，用于在 P2P 无法直连时中继流量。

### 步骤 1：启用并启动容器

```bash
# 修改 .env
sed -i 's/ENABLE_DERPER=false/ENABLE_DERPER=true/' .env

# 重新部署（自动 build 并启动 derper 容器）
./scripts/deploy.sh
```

### 步骤 2：在 NPM 中添加 Derper 反代

1. 登录 `https://nginx.teraai.cn`
2. **Hosts → Proxy Hosts → Add Proxy Host**
3. 填写：
   - **Domain Names**: `derper.teraai.cn`
   - **Scheme**: `http`
   - **Forward Hostname / IP**: `127.0.0.1`
   - **Forward Port**: `8080`
4. **SSL** 标签页：
   - **SSL Certificate**: 选择 `*.teraai.cn` 通配符证书
   - **Force SSL**: ✅
5. **Advanced** 标签页添加（WebSocket 支持）：
   ```nginx
   proxy_set_header Upgrade $http_upgrade;
   proxy_set_header Connection "upgrade";
   proxy_read_timeout 86400;
   proxy_buffering off;
   ```
6. 点击 **Save**

### 步骤 3：在 Tailscale ACL 中注册自定义 DERP

1. 访问 https://login.tailscale.com/admin/acls/file
2. 在 JSON 中添加 `derpMap`（如果已有其他配置，合并进去即可）：
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
3. 点击 **Save**

### 步骤 4：验证是否成功

**在云服务器上**：
```bash
# 确认 derper 容器在运行
docker compose --profile derper ps

# 查看日志无报错
docker compose logs -f derper
```

**在家里主机上**：
```bash
# 查看当前使用的 DERP
tailscale netcheck
```

如果输出中出现 `DERP: 900`（或你设置的 RegionID），说明自定义 DERP 已生效。

**成功标准 checklist**：
- [ ] `docker compose --profile derper ps` 显示 derper 状态为 `running`
- [ ] `curl -I https://derper.teraai.cn` 返回 HTTP 200
- [ ] `tailscale netcheck`（家里主机）显示 `DERP: 900`
- [ ] `tailscale status`（家里主机）显示云服务器为 direct 或 via DERP 900

---

## 日常维护

### 查看服务状态

```bash
docker compose ps
docker compose logs -f tailscale
docker compose logs -f npm
docker compose logs -f derper  # 如果已启动
```

### 重启服务

```bash
# 重启核心服务
docker compose restart

# 重启单个服务
docker compose restart npm
```

### 备份数据

```bash
# 一键备份全部（含 .env）
tar czf nginx-deploy-backup-$(date +%Y%m%d).tar.gz \
  .env npm/data certbot/conf certbot/acme-home tailscale/state
```

### 恢复数据

```bash
# 解压备份到项目根目录
tar xzf nginx-deploy-backup-20260524.tar.gz

# 重启
docker compose up -d
```

### 卸载与重新部署

项目提供一键清理脚本，方便测试或彻底重装：

```bash
# 完整清理（删除所有容器、数据、证书和 cron 任务）
./scripts/uninstall.sh

# 自动化测试时跳过交互确认
./scripts/uninstall.sh --yes

# 保留 Tailscale（不删除容器和认证状态，避免重新申请 auth key）
./scripts/uninstall.sh --yes --keep-tailscale
```

清理完成后，直接重新运行 `./scripts/deploy.sh` 即可重新部署。

> ⚠️ **注意**：完整清理会删除 `certbot/` 目录，导致 acme.sh 丢失已申请的证书记录。Let's Encrypt 对同一域名有速率限制，**不要频繁完整清理+重部署**。如需频繁测试，可保留 `certbot/` 目录，或临时切换到 Let's Encrypt Staging 环境。

### 更新镜像

```bash
# 拉取最新镜像
docker compose pull

# 全部重建（核心 + Derper）
docker compose pull && docker compose --profile derper up -d --build
```

> ⚠️ **升级 NPM 版本前，务必重新测试 `init-db.py` 的兼容性。**

### 手动续签证书

```bash
./scripts/renew-cert.sh
```

> 正常情况下由 cron 自动执行，不需要手动操作。

---

## 故障排查

### Tailscale 无法认证

```bash
# 检查 Auth Key
grep TS_AUTHKEY .env

# 查看日志
docker compose logs -f tailscale

# 手动触发认证
docker exec tailscale tailscale up --authkey=tskey-auth-xxx
```

### NPM 管理界面无法访问

```bash
# 确认域名解析
dig nginx.teraai.cn

# 确认 443 端口可达
curl -I https://nginx.teraai.cn

# 检查 NPM 是否运行
docker compose ps

# 检查 NPM 日志
docker compose logs npm
```

### 证书过期或错误

```bash
# 查看证书有效期
openssl x509 -in certbot/conf/live/teraai.cn/fullchain.pem -noout -dates

# 手动续签
./scripts/renew-cert.sh

# 检查 cron 任务
crontab -l | grep renew-cert
```

### 无法访问家里服务（502 Bad Gateway）

```bash
# 确认家里 Tailscale 在线
docker exec tailscale tailscale status

# 确认家里 IP 可达
docker exec tailscale tailscale ping 100.x.x.x
docker exec tailscale wget -qO- http://100.x.x.x:8123

# 确认家里服务监听正确（不要只监听 127.0.0.1）
```

---

## 安全建议

- ✅ `.env` 文件设置 `chmod 600`
- ✅ 首次登录后立即修改 NPM 默认密码
- ✅ 81 端口不暴露在公网
- ✅ Tailscale Auth Key 设置为 **Reusable + Not Ephemeral**
- ✅ 定期检查 Tailscale Machines 列表，移除不认识设备
- ✅ deploy.sh 使用 `read_env_var()` 安全读取 `.env`，不会将密钥导出到全局环境（避免子进程继承敏感变量）

---

## 技术文档

- [部署技术详情](docs/deployment-guide.md)
- [SSL 证书方案设计](docs/ssl-cert-plan.md)

---

---

## TODO

以下功能尚未实现，欢迎 PR 或后续补充：

- [ ] **自动配置 Tailscale ACL**：当前需要手动在 Tailscale 控制台粘贴 `derpMap` JSON。后续可支持在 `.env` 中配置 `TAILSCALE_API_KEY`，由 `deploy.sh` 自动调用 Tailscale API 写入 ACL。
- [ ] **自动预填充 Derper 反代**：当前 `init-db.py` 不会自动创建 `derper.teraai.cn` 的 Proxy Host，需要手动在 NPM Web UI 中添加。后续可检测 `ENABLE_DERPER=true` 时自动预填充。

---

*项目版本: 2.1*
