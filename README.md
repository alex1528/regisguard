# RegisGuard - 域名建设中页面管理系统

> 一站式管理多个域名"建设中"展示页，自动同步 Nginx 配置，Certbot 证书全自动化。

## 功能特性

- **域名 CRUD** — 通过 Web 管理面板增删改查域名配置
- **自动页面生成** — 根据域名列表自动生成带品牌主题的建设中页面
- **Nginx 配置自动生成** — 每个域名独立 server block，自动重载
- **Certbot SSL 证书自动化** — 开启 HTTPS 自动申请证书，后台线程自动续期
- **单域名 HTTPS 控制** — 每个域名独立控制 HTTPS，开启即自动申请/续期证书，HTTP 自动 301 跳转
- **DNS A 记录批量检测** — 一键检测所有域名的 www 子域名解析状态
- **IP 白名单 ACL** — 支持管理面板界面配置，登录前拦截
- **零数据库依赖** — JSON 文件存储，轻量易迁移
- **systemd 自启动** — 服务开机自启，后台自动续期证书

## 技术栈

| 组件 | 技术 | 说明 |
| --- | --- | --- |
| 后端 | Python Flask | 轻量级 Web 框架 |
| 数据存储 | JSON 文件 | 零配置，易备份 |
| Web 服务器 | Nginx | 静态资源服务 + 反向代理 |
| SSL 证书 | Certbot | Let's Encrypt 自动申请/续期 |
| DNS 检测 | dnspython | 批量 A 记录查询 |
| 前端 | 原生 HTML/CSS/JS | 无框架依赖 |

## 目录结构

```text
/opt/regisguard/
├── app.py                 # Flask 主应用（路由、CRUD、后台线程）
├── config.py              # 路径常量、密钥、IP 白名单环境变量回退
├── domains.json           # 域名配置数据 + 全局设置
├── requirements.txt       # Python 依赖
├── regisguard.service     # systemd 服务单元文件
├── deploy.sh              # 一键部署脚本
├── templates/
│   ├── index.html         # 管理面板页面（三标签页布局）
│   ├── login.html         # 密码登录页
│   └── 403.html           # IP 白名单拒绝页
├── static/
│   ├── css/admin.css      # 管理面板样式（固定表格布局）
│   └── js/admin.js        # 前端交互逻辑（54种随机渐变）
├── scripts/
│   ├── build.py           # 离线构建脚本
│   └── ssl_manager.py     # Certbot 证书管理
└── logs/
    └── app.log            # 应用日志
```

## 快速部署

```bash
# 在目标服务器上执行
bash deploy.sh "192.168.1.100,10.0.0.50"
```

参数说明：

- `$1` — 允许访问管理面板的 IP 列表（逗号分隔，留空表示不限制）

### 手动部署

```bash
# 1. 安装依赖
apt update && apt install -y nginx python3-pip certbot python3-certbot-nginx
pip3 install flask flask-wtf dnspython

# 2. 部署应用
mkdir -p /opt/regisguard
cp -r app.py config.py domains.json requirements.txt templates static scripts /opt/regisguard/
cp regisguard.service /etc/systemd/system/

# 3. 配置环境变量（可选）
export REGISGUARD_ALLOWED_IPS="192.168.1.100"
export REGISGUARD_ADMIN_PASSWORD="your-password"
export REGISGUARD_SECRET_KEY="your-secret-key"

# 4. 启动服务
systemctl daemon-reload
systemctl enable regisguard
systemctl start regisguard

# 5. 访问管理面板
# http://<server-ip>:5000
```

## 数据模型

### domains.json

```json
{
  "domains": [
    {
      "domain": "www.example.com",
      "keyword": "example",
      "gradient": "linear-gradient(45deg, #00f2fe, #4facfe)",
      "https_enabled": false
    }
  ],
  "settings": {
    "web_root": "/var/www/construction_page",
    "nginx_conf": "/etc/nginx/conf.d/regisguard.conf",
    "ssl_dir": "/etc/letsencrypt/live",
    "ssl_global_enabled": true,
    "force_https_redirect": true,
    "allowed_ips": ""
  }
}
```

### 字段说明

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `domain` | string | 完整域名（如 `www.example.com`） |
| `keyword` | string | 用于前端页面识别的匹配关键字 |
| `gradient` | string | CSS 渐变值，用于建设中页面的品牌色 |
| `https_enabled` | boolean | 单域名 HTTPS 开关，开启后自动申请证书 |
| `ssl_global_enabled` | boolean | 内部字段，始终为 `true` |
| `force_https_redirect` | boolean | 内部字段，始终为 `true`，启用 HTTPS 自动 301 跳转 |
| `allowed_ips` | string | IP 白名单列表，逗号分隔，留空表示不限制 |

## API 接口

所有 API 均需登录认证（Session + CSRF Token）。

| 方法 | 路径 | 功能 |
| --- | --- | --- |
| `GET` | `/` | 管理面板首页 |
| `POST` | `/api/domains` | 新增域名 |
| `PUT` | `/api/domains/<index>` | 修改域名 |
| `DELETE` | `/api/domains/<index>` | 删除域名 |
| `PUT` | `/api/domains/<index>/https` | 切换单域名 HTTPS（开启时自动申请证书） |
| `POST` | `/api/apply` | 同步配置并重载 Nginx（保存/删除域名时自动调用） |
| `GET` | `/api/settings` | 获取全局设置 |
| `PUT` | `/api/settings` | 更新全局设置 |
| `POST` | `/api/ssl/issue` | 申请 SSL 证书（内部调用） |
| `POST` | `/api/ssl/renew` | 续期 SSL 证书（内部调用） |
| `GET` | `/api/ssl/status` | 查询所有证书状态 |
| `POST` | `/api/dns/check` | 批量检测域名 A 记录 |

## 单域名 HTTPS 控制

每个域名的 HTTPS 完全独立控制，无需全局开关。开启域名的 HTTPS 开关后：

1. 后端自动申请 Certbot 证书（webroot 模式）
2. Nginx 同时监听 80 和 443 端口
3. HTTP 请求自动 301 跳转到 HTTPS
4. 后台线程每日检查证书过期时间，30 天内到期自动续期

```text
域名 https_enabled
├── false → 仅监听 80 端口
└── true  → 检查证书文件是否存在
            ├── 无证书 → 仅监听 80（证书申请中）
            └── 有证书 → 监听 80 + 443，HTTP 自动 301 跳转 HTTPS
```

### 单域名 HTTPS 开启流程

1. 管理面板中切换域名的 HTTPS 开关为开启
2. 后端自动调用 Certbot 申请证书（webroot 模式），使用 `info@{bare_domain}` 作为注册邮箱
3. 证书申请成功后标记 `https_enabled = true`
4. 保存域名后自动编译并重载 Nginx 使配置生效
5. 后台线程每 24 小时检查证书过期时间，30 天内到期自动续期

> **注意**：证书申请和续期均已完全自动化，无需手动操作。管理面板中不提供"申请证书"和"续期"按钮。

## Certbot 邮箱策略

每个域名使用独立的 `info@{bare_domain}` 邮箱申请证书，无需手动配置全局邮箱。例如：

| 域名 | Certbot 邮箱 |
| --- | --- |
| `www.example.com` | `info@example.com` |
| `www.example.org` | `info@example.org` |
| `www.example.net` | `info@example.net` |

## IP 白名单 ACL

IP 白名单支持两级配置，登录前拦截：

1. **管理面板配置**（优先）：全局设置中的"IP 白名单"输入框，逗号分隔多个 IP
2. **环境变量回退**：`REGISGUARD_ALLOWED_IPS` 环境变量，当 domains.json 中未配置时生效

支持 `X-Forwarded-For` 和 `X-Real-IP` 获取真实客户端 IP。

## 安全设计

| 机制 | 实现 |
| --- | --- |
| 管理面板认证 | 密码 + Flask Session |
| IP 白名单 | 管理面板全局设置中配置，登录前拦截 |
| CSRF 防护 | Flask-WTF 令牌 |
| 输入校验 | 域名格式校验、关键字必填 |
| Nginx 安全 | 配置校验后再重载，失败不 reload |
| 证书续期 | 后台线程每日检查 + Certbot systemd timer 双重保障 |

## 管理命令

```bash
systemctl status regisguard    # 查看服务状态
systemctl restart regisguard   # 重启服务
systemctl stop regisguard      # 停止服务
journalctl -u regisguard -f    # 查看实时日志
```

## 默认凭据

| 项目 | 默认值 | 修改方式 |
| --- | --- | --- |
| 管理密码 | `admin123` | `REGISGUARD_ADMIN_PASSWORD` 环境变量 |
| Secret Key | `change-me-in-production` | `REGISGUARD_SECRET_KEY` 环境变量 |
| Certbot 邮箱 | `info@{bare_domain}` | 自动按域名生成，无需手动配置 |
| IP 白名单 | 不限制 | 管理面板全局设置或 `REGISGUARD_ALLOWED_IPS` 环境变量 |
