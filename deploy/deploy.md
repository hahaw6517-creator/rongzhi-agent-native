# 融智 Agent · 服务器部署指南

> 「融智 Agent · 企业财务分析与融资决策」面向一般非金融企业：上传连续三年财务报表，
> 完成财务分析、融资组合决策、风险检验与 Word 报告交付。
> 本文件夹（`deploy/`）提供**离线镜像包 + 编排文件 + 环境变量模板 + 本文档**，
> 无需在服务器上构建，三条命令即可上线。

## 一、包内容清单

| 文件 | 说明 |
| --- | --- |
| `images/finbridge-images.tar` | 离线镜像包，内含 `finbridge:latest` 一个镜像（python:3.12-slim 基础，前后端一体，单容器） |
| `docker-compose.yml` | 服务器编排文件：引用镜像（无构建步骤），对外监听宿主机 8787 端口，数据落盘具名卷 `finbridge-data`，环境变量从 `.env` 读取 |
| `.env.example` | 环境变量模板：复制为 `.env` 并填入模型密钥 |
| `deploy.md` | 本文档 |

## 二、环境要求

| 项目 | 要求 |
| --- | --- |
| 系统 | Linux（Ubuntu / Debian / CentOS 等均可） |
| Docker | 20.10 及以上，且包含 `docker compose` 插件（或独立 `docker-compose`） |
| 架构 | x86_64（amd64） |
| 端口 | 对外占用宿主机 8787 端口；如需更换，直接编辑 compose 文件里的 `'8787:8000'` |
| 密钥 | `DEEPSEEK_API_KEY`（必需，模型能力）；`TAVILY_API_KEY`（可选，联网检索）；`ADMIN_PASSWORD`（可选，管理后台） |

检查环境是否就绪：

```bash
docker --version
docker compose version
```

## 三、快速开始（三条命令）

把整个 `deploy/` 文件夹上传到服务器任意目录（例如 `/opt/finbridge`），先配置密钥：

```bash
# 0. 配置环境变量（在 deploy 目录内）
cp .env.example .env
vi .env   # 填入 DEEPSEEK_API_KEY，可选填 TAVILY_API_KEY
```

然后：

```bash
# 1. 加载离线镜像
docker load -i images/finbridge-images.tar

# 2. 在后台启动服务（在 deploy 目录内执行）
docker compose up -d

# 3. 验证
docker compose ps
curl -I http://localhost:8787/healthz
```

看到容器 `finbridge` 为 `Up` 状态、`/healthz` 返回 `200`，即部署成功。
浏览器访问 `http://服务器公网IP:8787/` 即可使用。

> 注意：`/healthz` 只表示网页服务正常；模型调用、融资求解与 Word 导出需按「上线验收」逐项确认。

## 四、上线验收（部署后必做）

| 检查项 | 操作 |
| --- | --- |
| 页面打开 | 浏览器访问 `http://服务器公网IP:8787/` |
| 模板下载与 Excel 上传 | 在页面导入 `data/` 提供的三年财报模板或示例 |
| 分析执行 | 用公开演示数据跑通财务分析 → 融资决策 → 风险评估 |
| 临时对话情景 | 配置密钥后，在分析报告页发起专业对话并试算临时情景 |
| Word 报告下载 | 下载报告并确认可打开 |
| 会话隔离 | 用两个不同浏览器会话确认数据互不可见 |

## 五、常用配置

### 修改对外端口

编辑 `docker-compose.yml` 里的 `'8787:8000'`，把左边的 `8787` 改成目标端口后执行 `docker compose up -d` 重建即可，例如改成 9090：

```yaml
        ports:
            - '9090:8000'
```

### 云服务器安全组 / 防火墙

| 场景 | 操作 |
| --- | --- |
| 云厂商安全组 | 放行入方向 TCP `8787`（或自定义端口） |
| 服务器自带防火墙 | `sudo ufw allow 8787/tcp`（Ubuntu）或 `sudo firewall-cmd --permanent --add-port=8787/tcp && sudo firewall-cmd --reload`（CentOS） |

### 平台模型管理（可选）

在 `.env` 设置 `ADMIN_PASSWORD` 后，访问 `http://服务器公网IP:8787/admin.html` 登录（用户名 `admin`、密码为该环境变量、需输入图形验证码），可维护**平台托管**的模型密钥（OpenAI 兼容接口）：新增、编辑（API Key 留空表示保留原值）、启用、连通性测试与删除；并通过**用户管理**板块管理全部注册账户：重置密码、禁用/启用、删除（级联清理该账户数据）。

| 行为 | 说明 |
| --- | --- |
| 调用优先级 | 用户自配（页首「模型设置」，会话级）→ 平台托管（本页启用项）→ 环境变量（`.env` 中 `DEEPSEEK_API_KEY` 等） |
| 密钥存储 | Fernet 加密落库（`runtime.sqlite3`），接口只回掩码；主密钥默认自动生成存于 `app_meta` 表，可用 `FINBRIDGE_ENC_KEY` 指定 |
| `ADMIN_PASSWORD` 生效时机 | 仅在首次播种 admin 账户时生效；admin 已存在后修改该变量不会改变已有密码，改密请用后台「用户管理 → 重置密码」 |
| 未设置 `ADMIN_PASSWORD` | 管理后台不可用（登录返回 503），其余功能不受影响 |

### 域名与 HTTPS（可选）

服务本身只暴露一个 HTTP 端口，推荐在前面加一层 Nginx / Caddy 做域名解析与 HTTPS 反代，将域名流量转发到 `127.0.0.1:8787` 即可。

### 持久化卷权限

数据卷挂载在容器内 `/app/storage`，容器以非 root 用户 UID 10001 运行；具名卷由 Docker 创建时自动继承该权限，无需手工处理。若改用 bind mount，需保证宿主机目录对 UID 10001 可写。

## 六、数据与运维

会话、任务快照、聊天历史保存在容器内 `/app/storage/runtime.sqlite3`，落盘于具名卷 `finbridge-data`。

| 操作 | 命令 |
| --- | --- |
| 查看运行状态 | `docker compose ps` |
| 查看日志 | `docker compose logs -f agent` |
| 备份数据 | `docker run --rm -v finbridge_finbridge-data:/data -v $(pwd):/backup alpine tar czf /backup/finbridge-data-backup.tar.gz -C /data runtime.sqlite3` |
| 恢复数据 | `docker run --rm -v finbridge_finbridge-data:/data -v $(pwd):/backup alpine sh -c "cd /data && tar xzf /backup/finbridge-data-backup.tar.gz"`，然后 `docker compose restart agent` |
| 重启服务 | `docker compose restart` |
| 停止服务 | `docker compose down`（数据保留） |
| 清空所有运行数据 | `docker compose down -v && docker compose up -d`（删除卷，谨慎操作） |
| 彻底卸载 | `docker compose down -v && docker rmi finbridge:latest` |

### 升级新版本

#### 从 GitHub 一条命令更新现有网站

适用当前项目的 Linux + Docker Compose v2 部署：服务名 `agent`、镜像 `finbridge:latest`、容器名 `finbridge`，数据库持久化在 `/app/storage`。服务器需要 Git、Bash、`flock`，并能访问 GitHub、Docker 基础镜像和 Python 包源。

**已有本仓库源码的服务器，首次执行：**

```bash
# 进入服务器上的 rongzhi-agent-native 仓库目录后执行
git pull --ff-only && bash deploy/update.sh
```

**如果原来只上传了离线部署包，首次执行：**

```bash
git clone https://github.com/hahaw6517-creator/rongzhi-agent-native.git
cd rongzhi-agent-native
bash deploy/update.sh
```

原来的部署文件夹、`.env` 和 Compose 文件保留在原位置。脚本从运行中的容器读取原 Compose 路径和项目名，沿用原端口、网络、密钥配置及数据卷，无需把密钥复制到代码仓库。

**之后每次更新，只在这个仓库目录执行：**

```bash
bash deploy/update.sh
```

执行流程：拉取 `origin/main` → 创建并校验 SQLite 备份 → 从源码构建镜像 → 重建 `agent` 容器 → 检查 `/healthz`、镜像版本和持久化挂载。备份保存在服务器仓库的 `tmp/server-backups/时间/`，该目录不上传 GitHub，包含账户和分析数据，请按私有备份保管。

构建期间旧服务继续运行；切换容器时会短暂中断。脚本不会执行 `down -v` 或清理数据卷。重建或启动检查失败会尝试恢复旧镜像，数据库不会自动倒回备份。`/healthz` 验证服务启动，融资分析、模型问答与公网域名访问仍按下方验收表检查。

如服务器有未提交的代码或 Compose 改动，脚本会停止，先由部署者保留并处理这些改动。容器自定义名称可用 `FINBRIDGE_CONTAINER=实际容器名 bash deploy/update.sh`。原 Compose 路径已删除、镜像名称或存储布局不同的部署会停止并提示，需先核对配置。

Docker 的 `compose up` 会在镜像变化时重建容器并保留挂载卷：[官方说明](https://docs.docker.com/reference/cli/docker/compose/up/)。只执行 `git pull` 或 `docker compose restart` 不会把新的 Python/网页文件装进旧镜像。

#### 继续使用离线镜像包

将来有新版本时，会提供新的 `finbridge-images.tar`，在 `deploy` 目录执行：

```bash
docker load -i images/finbridge-images.tar
docker compose up -d
```

`up -d` 会用新镜像重建容器，运行数据因存放在独立卷中而自动保留；代码更新不会覆盖 `.env` 与卷内数据。

## 七、常见问题

| 现象 | 原因与解决 |
| --- | --- |
| `port is already allocated` | 8787 端口被占用：编辑 `docker-compose.yml` 里的 `'8787:8000'` 换成空闲端口，再 `docker compose up -d` |
| `permission denied` 连接 Docker | 当前用户不在 docker 组：用 `sudo` 执行，或 `sudo usermod -aG docker $USER` 后重新登录 |
| 页面能开但分析/对话报错 | 模型未配置或密钥无效：`docker compose logs agent` 排查；确认 `.env` 中 `DEEPSEEK_API_KEY` 已填写且未被空行/引号破坏 |
| 对话提示"模型未配置" | `.env` 缺失或 `env_file` 路径不对：`.env` 必须与 `docker-compose.yml` 同目录 |
| `no matching manifest for linux/arm64` | 镜像为 amd64 架构，需在 x86_64 服务器上运行 |
| 想验证镜像完整性 | `docker load` 成功输出 `Loaded image: finbridge:latest` 即说明 tar 完整可读 |
| 运行数据如何备份 | 见「数据与运维」表格；持久化存储不等于已经备份，请定期导出 |
