# Plan: 集成 acme.sh 免费自动续签 SSL 证书到 nginx-deploy

## Background
当前项目 `nginx-deploy` 只有文档，缺少实际部署文件。用户希望参考 `NestGate` 的 acme.sh + DNS-01 方案，实现：
- 只签一个证书（通配符 `*.teraai.cn` + 裸域名 `teraai.cn`）
- 免费（Let's Encrypt）+ 自动续签
- `derper.teraai.cn`、`nginx.teraai.cn`、`teraai.cn` 共用此证书

## Key Challenge
当前项目使用 **Nginx Proxy Manager (NPM)**，它有内置 Let's Encrypt 但不支持 AliDNS 的 DNS-01 验证，也无法直接申请通配符。必须引入外部 acme.sh 管理证书，并解决 NPM 加载外部证书的问题。

## Proposed Approach
采用 **acme.sh 独立证书管理 + NPM Custom Certificate 手动首次上传 + 自动同步续签** 方案：

1. **acme.sh 容器化运行**（临时容器 `docker run --rm`，非常驻），参考 NestGate
2. **DNS-01 验证**：用 AliDNS API 签发 `*.teraai.cn` + `teraai.cn`
3. **证书持久化**：`./certbot/conf/live/teraai.cn/fullchain.pem` + `privkey.pem`
4. **NPM 挂载证书**：`./certbot/conf:/certs:ro`，NPM 容器内可读取
5. **首次使用**：在 NPM UI 中手动添加 Custom Certificate（上传证书文件）
6. **自动续签**：`renew-cert.sh` 调用 `acme.sh --cron`，续签后自动同步到 NPM 的 `custom_ssl` 目录，并 `nginx -s reload`

## Files to Create/Modify

### New Files
- `docker-compose.yml` — 编排 tailscale + npm + derper，npm 额外挂载 `/certs`
- `.env.example` — 环境变量模板（含 AliDNS API Key、域名、邮箱等）
- `scripts/issue-cert.sh` — 首次签发通配符证书（参考 NestGate）
- `scripts/renew-cert.sh` — 自动续签 + 安装证书 + reload
- `scripts/sync-cert-to-npm.sh` — 将新证书复制到 NPM custom_ssl 目录
- `certbot/acme-home/.gitkeep` — acme.sh 状态持久化目录
- `certbot/conf/.gitkeep` — 证书输出目录
- `npm/data/.gitkeep` — NPM 数据目录占位
- `npm/letsencrypt/.gitkeep` — NPM 证书目录占位
- `tailscale/state/.gitkeep` — Tailscale 状态目录占位
- `derper/Dockerfile` — Derper 构建文件（文档中已有，需创建）

### Modified Files
- `docs/deployment-guide.md` — 重写 SSL/证书相关章节，加入 acme.sh 配置、首次部署步骤、NPM 中使用 Custom Certificate 的方法
- `.gitignore` — 加入 `.env` 和敏感数据目录

## Implementation Details

### acme.sh 签发参数
```bash
acme.sh --issue --dns dns_ali \
  -d "teraai.cn" -d "*.teraai.cn" \
  --server letsencrypt --keylength ec-256
```

### NPM 证书同步逻辑
- NPM 的 Custom Certificate 存储在 `./npm/data/custom_ssl/<nice_name>/`
- `sync-cert-to-npm.sh` 遍历 `./npm/data/custom_ssl/` 下所有目录，读取 `metadata.json`，找到包含 `teraai.cn` 的条目
- 将 `fullchain.pem` 和 `privkey.pem` 复制到对应目录
- 执行 `docker compose exec npm nginx -s reload`
- 不依赖 sqlite3，只依赖 `grep` 和文件操作

### Cron 自动续签
在部署指南中说明：将 `renew-cert.sh` 加入宿主机 crontab（建议每周运行一次）：
```cron
0 3 * * 1 cd /opt/nginx-deploy && ./scripts/renew-cert.sh >> /var/log/acme-renew.log 2>&1
```

## Risk / Mitigation
- **NPM 升级后 custom_ssl 结构变化**：同步脚本只操作文件系统，不操作数据库，结构变化风险低
- **首次必须手动上传**：这是 NPM 的架构限制， unavoidable。已在文档中明确标注步骤
- ** AliDNS API 凭证泄露**：放入 `.env`，已加入 `.gitignore`
