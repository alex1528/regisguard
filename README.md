# RegisGuard - 域名建设中页面管理系统

> 一站式管理多个域名"建设中"展示页，自动同步 Nginx 配置，Certbot 证书全自动化。

## 功能特性

- **域名 CRUD** — 通过 Web 管理面板增删改查域名配置
- **自动页面生成** — 根据域名列表自动生成带品牌主题的建设中页面
- **响应式主题系统** — Light / Dark / 跟随系统三档切换，三档断点（移动 / 平板 / 桌面）覆盖全部页面，统一设计令牌驱动样式，满足 WCAG AA 对比度与减弱动效偏好
- **Nginx 配置自动生成** — 每个域名独立 server block，自动重载
- **Certbot SSL 证书自动化** — 开启 HTTPS 自动申请证书，DNS 预检避免无效请求，后台线程自动续期
- **单域名 HTTPS 控制** — 每个域名独立控制 HTTPS，开启即自动申请/续期证书，HTTP 自动 301 跳转
- **DNS A 记录批量检测** — 一键检测所有域名的 www 子域名解析状态
- **IP 白名单 ACL** — 支持管理面板界面配置，登录前拦截
- **管理员密码修改** — 支持管理面板界面修改密码，即时生效
- **零数据库依赖** — SQLite 数据库存储，WAL 模式支持并发，首次启动自动从 JSON 迁移
- **systemd 自启动** — 服务开机自启，后台自动续期证书

## 技术栈

| 组件 | 技术 | 说明 |
| --- | --- | --- |
| 后端 | Python Flask + Waitress | 轻量级 Web 框架 + 生产级 WSGI 服务器 |
| 数据存储 | SQLite 数据库 | WAL 模式，自动从 JSON 迁移 |
| Web 服务器 | Nginx | 静态资源服务 + 反向代理 |
| SSL 证书 | Certbot | Let's Encrypt 自动申请/续期 |
| DNS 检测 | dnspython | 批量 A 记录查询 |
| 前端 | 原生 HTML/CSS/JS | 无框架依赖 |

## 目录结构

```text
/opt/regisguard/
├── app.py                 # Flask 主应用（路由、CRUD、后台线程）
├── config.py              # 路径常量、密钥、IP 白名单环境变量回退
├── db.py                  # SQLite 数据库层（CRUD、设置管理、JSON 迁移）
├── domains.json           # 初始数据源（首次启动后自动迁移至 SQLite）
├── requirements.txt       # Python 依赖
├── regisguard.service     # systemd 服务单元文件
├── deploy.sh              # 一键部署脚本
├── templates/
│   ├── index.html         # 管理面板页面（三标签页布局 + 主题切换器）
│   ├── login.html         # 密码登录页（响应式）
│   └── 403.html           # IP 白名单拒绝页（响应式）
├── static/
│   ├── css/
│   │   ├── tokens.css     # 设计令牌（颜色 / 间距 / 字号 / 圆角 / 阴影 / 动效）
│   │   └── admin.css      # 管理面板样式（令牌驱动 + 三档响应式断点）
│   └── js/
│       ├── admin.js       # 前端交互逻辑（54种随机渐变）
│       └── theme.js       # 主题运行时（解析 / 持久化 / 系统偏好订阅）
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
pip3 install flask flask-wtf dnspython waitress

# 2. 部署应用
mkdir -p /opt/regisguard
cp -r app.py config.py db.py domains.json requirements.txt \
  templates static scripts /opt/regisguard/
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

### SQLite 数据库

数据存储在 `data/regisguard.db` 中，使用 WAL 模式支持并发读写。首次启动时自动从 `domains.json` 迁移数据。

#### domains 表

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键，自增 |
| `domain` | TEXT | 完整域名（如 `www.example.com`），唯一约束 |
| `keyword` | TEXT | 用于前端页面识别的匹配关键字 |
| `gradient` | TEXT | CSS 渐变值，用于建设中页面的品牌色 |
| `https_enabled` | INTEGER | 单域名 HTTPS 开关（0/1），开启即自动申请证书 |
| `created_at` | TIMESTAMP | 创建时间 |
| `updated_at` | TIMESTAMP | 更新时间 |

#### settings 表

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `key` | TEXT | 设置键名，主键 |
| `value` | TEXT | 设置值 |

支持的设置键：

| 键名 | 说明 |
| --- | --- |
| `allowed_ips` | IP 白名单列表，逗号分隔，留空表示不限制 |
| `admin_password` | 管理员密码，留空时使用环境变量回退 |

### domains.json（仅用于初始迁移）

首次启动后，`domains.json` 中的数据会自动迁移至 SQLite 数据库，
此后该文件不再使用。如需重置数据，可删除 `data/regisguard.db`
并保留 `domains.json`。

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
| `PUT` | `/api/settings` | 更新全局设置（仅 IP 白名单） |
| `PUT` | `/api/password` | 修改管理员密码 |
| `POST` | `/api/ssl/issue` | 申请 SSL 证书（内部调用） |
| `POST` | `/api/ssl/renew` | 续期 SSL 证书（内部调用） |
| `GET` | `/api/ssl/status` | 查询所有证书状态（页面加载时由 `loadCertStatus()` 调用，回填"管理域名"列表的"到期时间"列） |
| `POST` | `/api/dns/check` | 批量检测域名 A 记录 |

## 单域名 HTTPS 控制

每个域名的 HTTPS 完全独立控制，无需全局开关。开启域名的 HTTPS 开关后：

1. 后端自动申请 Certbot 证书（webroot 模式）
2. Nginx 同时监听 80 和 443 端口
3. HTTP 请求自动 301 跳转到 HTTPS
4. 后台线程双级检查证书过期时间，自动续期

```text
域名 https_enabled
├── false → 仅监听 80 端口
└── true  → 检查证书文件是否存在
            ├── 无证书 → 仅监听 80（证书申请中）
            └── 有证书 → 监听 80 + 443，HTTP 自动 301 跳转 HTTPS
```

### 单域名 HTTPS 开启流程

1. 管理面板中切换域名的 HTTPS 开关为开启
2. 后端自动检测域名 DNS 解析状态，仅对可解析的域名申请证书
3. 证书申请成功后标记 `https_enabled = true`
4. 保存域名后自动编译并重载 Nginx 使配置生效
5. 后台线程双级检查证书过期时间，自动续期

### 证书自动续期策略

后台线程采用双级检查机制，确保证书在彻底过期前完成续期：

| 级别 | 触发条件 | 检查间隔 | 说明 |
| --- | --- | --- | --- |
| 正常 | 剩余 ≤30 天 | 每 24 小时 | 常规续期，提前一个月处理 |
| 紧急 | 剩余 ≤5 天 | 每 1 小时 | 强制续期，确保过期前完成 |

紧急模式下检查频率提升至每小时一次，保证在证书彻底过期
（Let's Encrypt 证书有效期 90 天，过期后无法续期只能重新申请）
之前完成续期操作。

> **注意**：证书申请和续期均已完全自动化，无需手动操作。
> 若域名 DNS 尚未配置或证书申请失败，系统会自动将 HTTPS 开关
> 回退至关闭状态，并在管理面板中显示具体失败原因，方便定位问题。
> 待 DNS 生效后再次切换 HTTPS 开关即可自动申请证书。

## Certbot 邮箱策略

每个域名使用独立的 `info@{bare_domain}` 邮箱申请证书，无需手动配置全局邮箱。例如：

| 域名 | Certbot 邮箱 |
| --- | --- |
| `www.example.com` | `info@example.com` |
| `www.example.org` | `info@example.org` |
| `www.example.net` | `info@example.net` |

## 证书申请策略

每个域名的证书统一在单次 certbot 调用中申请，www 子域名与裸域名
包含在同一张证书中，不分开申请。系统会先检测 DNS 解析状态：

| www 解析 | 裸域名解析 | certbot -d 参数 |
| --- | --- | --- |
| 有效 | 有效 | `-d www.{bare} -d {bare}` |
| 有效 | 无效 | `-d www.{bare}` |
| 无效 | 有效 | `-d {bare}` |
| 无效 | 无效 | 跳过申请，提示配置 DNS |

证书目录以 Certbot 首个 `-d` 参数命名，系统会自动检查裸域名和
`www.` 前缀两条路径，确保无论哪个目录存在都能正确加载。

证书申请失败时自动回退至 HTTP 状态，并在管理面板显示失败原因。

## IP 白名单 ACL

IP 白名单支持两级配置，登录前拦截：

1. **管理面板配置**（优先）：全局设置中的"IP 白名单"输入框，逗号分隔多个 IP
2. **环境变量回退**：`REGISGUARD_ALLOWED_IPS` 环境变量，
   当 settings 表中未配置时生效

支持 `X-Forwarded-For` 和 `X-Real-IP` 获取真实客户端 IP。

## 安全设计

| 机制 | 实现 |
| --- | --- |
| 管理面板认证 | 密码 + Flask Session |
| IP 白名单 | 管理面板全局设置中配置，登录前拦截 |
| CSRF 防护 | Flask-WTF 令牌 |
| 输入校验 | 域名格式校验、关键字必填 |
| Nginx 安全 | 配置校验后再重载，失败不 reload |
| 证书续期 | 后台双级检查（30天正常+5天紧急）+ Certbot systemd timer |

## 响应式主题系统

四类页面（管理面板、登录页、403 拒绝页、建设中页）共用一套基于 CSS 自定义属性的设计令牌，通过 `<html data-theme>` 切换 Light / Dark 两套主题。

### 主题模式

| 模式 | 行为 | 持久化 |
| --- | --- | --- |
| Light | 强制浅色，忽略系统偏好 | `localStorage["regisguard-theme"]` |
| Dark | 强制深色，忽略系统偏好 | `localStorage["regisguard-theme"]` |
| System | 跟随 `prefers-color-scheme`，系统切换时自动同步 | `localStorage["regisguard-theme"]`（默认值） |

- 切换器仅出现在管理面板 header；登录页、403 页、建设中页跟随系统偏好，不渲染切换控件。
- 切换器选中态绑定 `aria-pressed="true"` 选择器，无额外类名。
- 持久化只用浏览器 `localStorage`，每个浏览器独立，不写入 SQLite `settings` 表。
- 隐私模式 / 存储被禁用 / `matchMedia` 不可用时优雅降级为 Light，不抛错给用户。

### 设计令牌（`static/css/tokens.css`）

| 分类 | 命名前缀 | 档位 |
| --- | --- | --- |
| 间距 | `--rg-space-*` | xs / sm / md / lg |
| 字号 | `--rg-font-size-*` | sm / base / lg / xl |
| 圆角 | `--rg-radius-*` | sm / md / lg |
| 阴影 | `--rg-shadow-*` | sm / lg |
| 动效时长 | `--rg-duration-*` | fast / base |
| 字体栈 | `--rg-font-family` | 单值 |
| 颜色 | `--rg-color-*` | 每主题 ≥20 个，名称集合恒等 |

- 颜色令牌按主题在 `:root[data-theme="light"]` / `:root[data-theme="dark"]` 下定义，名称集合完全一致。
- 间距 / 字号 / 圆角 / 阴影 / 动效令牌在 `:root` 下定义，跨主题共享。
- 颜色取值经 WCAG AA 对比度调校（正文与背景 ≥4.5:1，焦点环与背景 ≥3:1）。

### 响应式断点

| 断点 | 视口范围 | 行为 |
| --- | --- | --- |
| Mobile | ≤480px | 单列堆叠，域名表格与 DNS 检测结果均切换为带字段标签的卡片视图（保留全部字段：域名、关键字、色彩、HTTPS、证书状态、到期时间、操作），点击目标 ≥40px，标签页横向滚动 |
| Tablet | 481–768px | 单列堆叠，编辑卡片置于表格之上 |
| Desktop | ≥769px | 左 320px 编辑卡片 + 右侧填满表格的双列布局 |

- 登录页：桌面端固定 360px，平板 / 移动端 88%–92% 宽度，移动端按钮和密码输入框高度 ∈ [44, 56]px。
- 403 页与建设中页：320–1920px 全程水平 + 垂直居中（边距差 ≤1px）。
- 视口跨断点变化由 CSS 媒体查询驱动，无 JS 介入，重排在浏览器渲染管线下完成。

### 可访问性

- **WCAG AA 对比度**：正文、主按钮、控制台前景色对比度 ≥4.5:1；徽章、焦点环 ≥3:1。
- **键盘焦点**：所有可聚焦元素提供 ≥2px `:focus-visible` 指示器（`outline` 或 `box-shadow`），与相邻像素对比度 ≥3:1。Tab 顺序与视觉顺序一致，禁用 / 隐藏元素不进入 Tab 链。
- **减弱动效**：`@media (prefers-reduced-motion: reduce)` 将所有元素及伪元素的 `transition-duration` / `animation-duration` 收敛至 ≤0.01s，`animation-iteration-count: 1`；建设中页 `.notice-banner` 关停 pulse 动画并消除 `transform`。

### 样式表加载顺序

四类页面都必须在 `<head>` 中先于其他样式表 / 内联 `<style>` 引入 `tokens.css`，否则 `var(--rg-*)` 引用会全部失效（页面将完全失去样式）：

| 页面 | 加载方式 |
| --- | --- |
| 管理面板 (`index.html`) | `<link rel="stylesheet" href="/static/css/tokens.css">` 在 `admin.css` 之前 |
| 登录页 (`login.html`) | `<link rel="stylesheet" href="/static/css/tokens.css">` 在内嵌 `<style>` 之前 |
| 403 页 (`403.html`) | `<link rel="stylesheet" href="/static/css/tokens.css">` 在内嵌 `<style>` 之前 |
| 建设中页 (`generate_html`) | `tokens.css` 全文内联到输出 HTML 的 `<style>` 块顶部 |

### FOUC 抑制

四类页面 `<head>` 末尾内联同步脚本，在首次绘制前完成 `data-theme` 解析：

- 管理面板版：读 `localStorage["regisguard-theme"]` + `matchMedia` 回退；
- 公开页版（登录 / 403 / 建设中）：仅 `matchMedia`，不读 `localStorage`，HTML 全文不含 `regisguard-theme` 字符串；
- 切换主题仅修改 `<html>.data-theme` 与 `.theme-btn[aria-pressed]`，不增删任何 `<link rel="stylesheet">` / `<style>` 节点。

### 服务端令牌内联

`generate_html()` 在每次生成建设中页时：

1. 读取 `static/css/tokens.css` 原文，内联到输出 HTML 的 `<style>` 块；
2. 重新解析输出令牌，与源令牌比对；
3. 不一致时以 `WARNING` 级别写入日志（`Construction page tokens out of sync: ...`），但不抛异常、不阻断 `apply_config`；
4. 保留每条域名的 `gradient` 字段作为 Logo `background`，`@supports not (background-clip: text)` 提供令牌驱动的纯色回退。



```bash
systemctl status regisguard    # 查看服务状态
systemctl restart regisguard   # 重启服务
systemctl stop regisguard      # 停止服务
journalctl -u regisguard -f    # 查看实时日志
```

## 默认凭据

| 项目 | 默认值 | 修改方式 |
| --- | --- | --- |
| 管理密码 | `admin123` | `REGISGUARD_ADMIN_PASSWORD` 环境变量或管理面板修改 |
| Secret Key | `change-me-in-production` | `REGISGUARD_SECRET_KEY` 环境变量 |
| Certbot 邮箱 | `info@{bare_domain}` | 自动按域名生成，无需手动配置 |
| IP 白名单 | 不限制 | 管理面板全局设置或 `REGISGUARD_ALLOWED_IPS` 环境变量 |
