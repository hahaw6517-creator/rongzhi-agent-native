"""用户体系与 AI 模型配置：注册/登录（图形验证码 + JWT）、供应商注册表、多模型配置、平台托管模型与历史对话管理。

复刻自 Project/template（大福食刻）的 AI 助手配置方法，API 契约逐字段对齐：
- 认证：GET /api/auth/captcha（SVG 图形验证码，一次性消费）→ POST /api/auth/register
  （用户名 3-32 位字母数字下划线、密码 ≥6 位）→ POST /api/auth/login（成功写 last_login），
  签发 7 天期 HS256 JWT，前端以 Authorization: Bearer 携带。
- 模型：ai_provider 供应商注册表（后台可维护，10 项默认种子）→ ai_model 用户多配置
  （上限 6 套，首套自动「使用中」，删除使用中项自动回落）→ ai_platform_model 平台托管
  （后台配置密钥，用户免配置直接选用）。密钥 Fernet 加密落库、接口仅回掩码。
- 历史对话：ai_conversation 留痕，支持最近 20 条 / 单条删除 / 清空。
AI 模型只负责理解、调度与解释；Python 计算与验证链路不受影响。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import random
import re
import secrets
import sqlite3
import time
from typing import Any, Mapping

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from finbridge.secret_box import mask_key

JWT_TTL_SECONDS = 7 * 24 * 60 * 60
CAPTCHA_TTL_SECONDS = 300
MODEL_LIMIT = 6
HISTORY_LIMIT = 20
PROTOCOLS = ("openai", "anthropic")
PROTOCOL_LABELS = {"openai": "OpenAI 兼容", "anthropic": "Anthropic"}
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")
PROVIDER_KEY_RE = re.compile(r"^[a-z0-9_]{2,32}$")
HTTP_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
CAPTCHA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 无 0/O/1/I 歧义字符

# 默认供应商注册表：与 template（大福食刻）保持一致
AI_PROVIDERS_DEFAULT = (
    ("custom", "自定义", "openai", "", "", "", 1),
    ("deepseek", "DeepSeek", "openai", "https://api.deepseek.com/v1", "https://platform.deepseek.com", "https://api-docs.deepseek.com", 10),
    ("qwen", "通义千问", "openai", "https://dashscope.aliyuncs.com/compatible-mode/v1", "https://bailian.console.aliyun.com", "https://help.aliyun.com/zh/dashscope/developer-reference/compatibility-of-openai-with-dashscope", 20),
    ("kimi", "Kimi", "openai", "https://api.moonshot.cn/v1", "https://platform.moonshot.cn", "https://platform.moonshot.cn/docs", 30),
    ("zhipu", "智谱 GLM", "openai", "https://open.bigmodel.cn/api/paas/v4", "https://open.bigmodel.cn", "https://open.bigmodel.cn/dev/api", 40),
    ("doubao", "豆包", "openai", "https://ark.cn-beijing.volces.com/api/v3", "https://console.volcengine.com/ark", "https://www.volcengine.com/docs/82379", 50),
    ("siliconflow", "硅基流动", "openai", "https://api.siliconflow.cn/v1", "https://cloud.siliconflow.cn", "https://docs.siliconflow.cn", 60),
    ("hunyuan", "腾讯混元", "openai", "https://api.hunyuan.cloud.tencent.com/v1", "https://console.cloud.tencent.com/hunyuan", "https://cloud.tencent.com/document/product/1729", 70),
    ("minimax", "MiniMax", "openai", "https://api.minimax.chat/v1", "https://platform.minimaxi.com", "https://platform.minimaxi.com/document", 80),
    ("mimo", "小米 MiMo", "openai", "https://api.xiaomimimo.com/v1", "https://xiaomimimo.com", "https://xiaomimimo.com/docs", 90),
)


def _error(message: str, status: int = 400) -> HTTPException:
    """构造与 web_api 一致的 HTTPException 错误。"""
    return HTTPException(status_code=status, detail=message)


async def _payload(request, required_keys: set[str]) -> dict:
    """解析 JSON 请求体；body 不是 JSON 对象时报 415。"""
    try:
        data = json.loads((await request.body()).decode("utf-8") or "{}")
    except ValueError as exc:
        raise _error("请求体必须是 JSON 对象", 415) from exc
    if not isinstance(data, dict):
        raise _error("请求体必须是 JSON 对象", 415)
    missing = required_keys - set(data)
    if missing:
        raise _error(f"缺少必要字段: {','.join(sorted(missing))}")
    return data


def _string(value, field: str, limit: int, required: bool = False) -> str:
    """字符串清洗：去首尾空白、限长、可选必填。"""
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise _error(f"{field}格式不正确")
    value = value.strip()
    if required and not value:
        raise _error(f"请输入{field}")
    if len(value) > limit:
        raise _error(f"{field}最多 {limit} 个字符")
    return value


# ---- 口令哈希（stdlib PBKDF2，零新依赖） ----

def hash_password(password: str) -> str:
    """PBKDF2-SHA256 加盐哈希，格式 pbkdf2_sha256$iterations$salt$hex。"""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), 260_000)
    return f"pbkdf2_sha256$260000${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """校验口令哈希；格式异常一律视为不匹配。"""
    try:
        _, iterations, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("ascii"), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, AttributeError):
        return False


# ---- JWT（HS256 手写实现，7 天有效期） ----

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def jwt_sign(user_id: int, secret: str) -> str:
    """签发 HS256 JWT（uid + exp）。"""
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8"))
    payload = _b64url(json.dumps({"uid": int(user_id), "exp": int(time.time()) + JWT_TTL_SECONDS}, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(secret.encode("utf-8"), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(signature)}"


def jwt_verify(token: str, secret: str) -> int | None:
    """校验 JWT，返回 uid；签名/过期/格式问题一律返回 None。"""
    try:
        header, payload, signature = token.split(".")
        expected = hmac.new(secret.encode("utf-8"), f"{header}.{payload}".encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url(expected), signature):
            return None
        data = json.loads(_b64url_decode(payload))
        if int(data.get("exp", 0)) < time.time():
            return None
        uid = data.get("uid")
        return int(uid) if uid is not None else None
    except (ValueError, TypeError):
        return None


# ---- 图形验证码（零依赖 SVG，一次性消费） ----

def make_captcha_text() -> str:
    """生成 4 位无歧义验证码字符。"""
    return "".join(random.choices(CAPTCHA_CHARS, k=4))


def captcha_svg(text: str) -> str:
    """渲染 SVG 验证码：随机旋转/配色 + 干扰线与噪点。"""
    palette = ("#2f5d50", "#3a6ea5", "#8a5a44", "#5b4a8a", "#316d3f")
    width, height = 124, 46
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             f'<rect width="{width}" height="{height}" fill="#f4f6f3" rx="6"/>']
    for index, char in enumerate(text):
        color = random.choice(palette)
        x = 22 + index * 26 + random.randint(-3, 3)
        y = 32 + random.randint(-3, 3)
        angle = random.randint(-24, 24)
        size = random.choice((26, 28, 30))
        parts.append(
            f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" font-family="Georgia, serif" '
            f'font-weight="bold" transform="rotate({angle} {x} {y})">{char}</text>')
    for _ in range(3):
        color = random.choice(palette)
        x1, y1, x2, y2 = (random.randint(0, width), random.randint(0, height),
                          random.randint(0, width), random.randint(0, height))
        parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="1" stroke-opacity=".45"/>')
    for _ in range(26):
        parts.append(f'<circle cx="{random.randint(0, width)}" cy="{random.randint(0, height)}" r="1" '
                     f'fill="{random.choice(palette)}" fill-opacity=".4"/>')
    parts.append("</svg>")
    return "".join(parts)


class closing_transaction:
    """提交/回滚并关闭 SQLite 连接（与 web_api.SessionStore 相同模式）。"""

    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def __enter__(self) -> sqlite3.Connection:
        return self.db

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.db.commit()
        else:
            self.db.rollback()
        self.db.close()
        return False


def _ts(value: float | None) -> str:
    """时间戳转 'YYYY-MM-DD HH:MM:SS'（与 template 的 DATETIME 回显一致）。"""
    if not value:
        return ""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))


def _iso(value: float | None) -> str:
    """ISO8601 时间（历史对话列表用）。"""
    if not value:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(value)) + time.strftime("%z")


def _public_user(row: sqlite3.Row) -> dict:
    """用户对外字段（与 template /auth/me 对齐，不含敏感信息）。"""
    return {"id": row["id"], "username": row["username"], "nickname": row["nickname"],
            "role": row["role"], "status": row["status"]}


def _mask_cipher(box, cipher: str) -> str:
    """掩码需短暂解密（与 template 一致）；解密失败标注而不泄露内容。"""
    try:
        return mask_key(box.decrypt(cipher))
    except ValueError:
        return "解密失败"


def _model_view(box, row: sqlite3.Row) -> dict:
    """用户模型对外字段：仅掩码，不回明文密钥。"""
    cipher = row["api_key_enc"] or ""
    return {"id": row["id"], "platformId": row["platform_id"], "provider": row["provider_key"],
            "protocol": row["protocol"], "baseUrl": row["base_url"], "modelId": row["model_id"],
            "name": row["display_name"] or row["model_id"], "displayName": row["display_name"],
            "hasKey": bool(cipher), "apiKeyMasked": _mask_cipher(box, cipher) if cipher else "",
            "isSelected": bool(row["is_selected"]), "createdAt": _ts(row["created"])}


class AuthStore:
    """用户、验证码、供应商注册表、模型配置与历史对话的 SQLite 存取（复用 SessionStore 的库/锁/密钥盒）。"""

    def __init__(self, session_store):
        self._store = session_store

    # --- 通用 ---
    @property
    def path(self) -> str:
        return self._store.path

    @property
    def lock(self):
        return self._store.lock

    def secret_box(self):
        return self._store.secret_box()

    def secret_key(self) -> str:
        return self._store.secret_key()

    def connect(self) -> closing_transaction:
        """打开一个提交型 SQLite 连接。"""
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return closing_transaction(db)

    # --- 启动引导 ---
    def bootstrap(self) -> None:
        """建表、种子供应商、播种管理员、迁移旧平台托管配置（全部幂等）。"""
        self.ensure_schema()
        self.seed_providers()
        self.migrate_platform_provider_column()
        self.migrate_legacy_platform_models()
        self.ensure_admin()
        self.seed_platform_from_env()

    def seed_platform_from_env(self) -> None:
        """平台托管为空且环境变量配置了 DEEPSEEK_API_KEY 时，播种默认 DeepSeek 托管模型（幂等）。

        让部署时通过环境变量提供的密钥自动转为后台可见的平台托管配置，
        密钥 Fernet 加密落库；管理员已配置过托管模型时不做任何事。
        """
        api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            return
        with self.lock, self.connect() as db:
            if db.execute("SELECT COUNT(*) AS c FROM ai_platform_model").fetchone()["c"]:
                return
            base_url = os.environ.get("BASE_URL", "").strip() or "https://api.deepseek.com/v1"
            model_id = os.environ.get("MODEL", "").strip() or "deepseek-chat"
            cipher = self.secret_box().encrypt(api_key)
            db.execute(
                "INSERT INTO ai_platform_model (name,provider,protocol,base_url,model_id,api_key_enc,enabled,sort_order,created) "
                "VALUES (?,?,?,?,?,?,1,0,?)",
                ("DeepSeek 官方", "deepseek", "openai", base_url, model_id, cipher, time.time()))

    def ensure_schema(self) -> None:
        """创建用户体系相关表。"""
        with self.connect() as db:
            db.executescript("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    nickname TEXT NOT NULL,
    role INTEGER NOT NULL DEFAULT 0,
    status INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL,
    last_login REAL
);
CREATE TABLE IF NOT EXISTS captchas (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_provider (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    protocol TEXT NOT NULL DEFAULT 'openai',
    base_url TEXT NOT NULL DEFAULT '',
    console_url TEXT NOT NULL DEFAULT '',
    model_doc_url TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS ai_model (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    platform_id INTEGER,
    provider_key TEXT NOT NULL,
    protocol TEXT NOT NULL DEFAULT 'openai',
    base_url TEXT NOT NULL DEFAULT '',
    model_id TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL DEFAULT '',
    api_key_enc TEXT NOT NULL DEFAULT '',
    is_selected INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ai_model_user ON ai_model(user_id);
CREATE TABLE IF NOT EXISTS ai_platform_model (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    protocol TEXT NOT NULL DEFAULT 'openai',
    base_url TEXT NOT NULL,
    model_id TEXT NOT NULL,
    api_key_enc TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_conversation (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL DEFAULT '',
    run_id TEXT,
    created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ai_conversation_user ON ai_conversation(user_id, created);
""")

    def seed_providers(self) -> None:
        """补插缺失的默认供应商（幂等，不影响后台已改动的项）。"""
        with self.connect() as db:
            existing = {row["provider_key"] for row in db.execute("SELECT provider_key FROM ai_provider")}
            for key, name, protocol, base_url, console_url, doc_url, order in AI_PROVIDERS_DEFAULT:
                if key not in existing:
                    db.execute(
                        "INSERT INTO ai_provider (provider_key,name,protocol,base_url,console_url,model_doc_url,enabled,sort_order) "
                        "VALUES (?,?,?,?,?,?,1,?)", (key, name, protocol, base_url, console_url, doc_url, order))

    def migrate_platform_provider_column(self) -> None:
        """旧库 ai_platform_model 缺 provider 列时补齐（与前台模型配置保持同一套字段）。"""
        with self.connect() as db:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(ai_platform_model)")}
            if "provider" not in columns:
                db.execute("ALTER TABLE ai_platform_model ADD COLUMN provider TEXT NOT NULL DEFAULT ''")

    def migrate_legacy_platform_models(self) -> None:
        """把旧 api_models(scope=platform) 迁入 ai_platform_model；会话级自配数据废弃清理。"""
        with self.connect() as db:
            tables = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "api_models" not in tables:
                return
            legacy = db.execute("SELECT name, base_url, model, api_key_enc FROM api_models WHERE scope='platform' ORDER BY id").fetchall()
            if legacy and db.execute("SELECT COUNT(*) AS c FROM ai_platform_model").fetchone()["c"] == 0:
                now = time.time()
                for index, row in enumerate(legacy):
                    db.execute(
                        "INSERT INTO ai_platform_model (name,protocol,base_url,model_id,api_key_enc,enabled,sort_order,created) "
                        "VALUES (?,?, 'openai', ?, ?, 1, ?, ?)",
                        (row["name"] or "平台托管模型", row["base_url"] or "", row["model"] or "", row["api_key_enc"] or "", index, now))
            db.execute("DELETE FROM api_models")

    def ensure_admin(self) -> None:
        """users 为空且配置了 ADMIN_PASSWORD 时，播种管理员账号 admin。"""
        password = os.environ.get("ADMIN_PASSWORD", "").strip()
        if not password:
            return
        with self.connect() as db:
            if db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] == 0:
                now = time.time()
                db.execute("INSERT INTO users (username,password_hash,nickname,role,status,created) VALUES (?,?,?,?,0,?)",
                           ("admin", hash_password(password), "管理员", 1, now))

    # --- 用户 ---
    def has_admin(self) -> bool:
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) AS c FROM users WHERE role=1").fetchone()["c"] > 0

    def admin_user_id(self) -> int | None:
        """返回首位管理员的用户 id，用于启动时认领历史演示分析；无管理员返回 None。"""
        with self.connect() as db:
            row = db.execute("SELECT id FROM users WHERE role=1 ORDER BY created LIMIT 1").fetchone()
            return row["id"] if row else None

    def create_user(self, username: str, password: str, nickname: str) -> sqlite3.Row:
        """注册用户；系统无管理员时首位注册者自动成为管理员。"""
        role = 0 if self.has_admin() else 1
        now = time.time()
        with self.connect() as db:
            if db.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                raise _error("用户名已被注册", 409)
            db.execute("INSERT INTO users (username,password_hash,nickname,role,status,created) VALUES (?,?,?,?,0,?)",
                       (username, hash_password(password), nickname or username, role, now))
            return db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()

    def find_user_by_username(self, username: str) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()

    def get_user(self, uid: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()

    def touch_login(self, uid: int) -> None:
        with self.connect() as db:
            db.execute("UPDATE users SET last_login=? WHERE id=?", (time.time(), uid))

    # --- 后台用户管理 ---
    def list_users(self) -> list[dict]:
        """全部账户清单，附各自历史分析数量（后台）。"""
        with self.connect() as db:
            rows = db.execute(
                "SELECT u.*, (SELECT COUNT(*) FROM runs r WHERE r.user_id=u.id) AS run_count "
                "FROM users u ORDER BY u.role DESC, u.created").fetchall()
        return [{"id": row["id"], "username": row["username"], "nickname": row["nickname"],
                 "role": row["role"], "disabled": bool(row["status"]), "created": row["created"],
                 "lastLogin": row["last_login"], "runs": row["run_count"]} for row in rows]

    def admin_reset_password(self, uid: int, new_password: str) -> None:
        """管理员重置任意账户密码。"""
        if len(new_password) < 6:
            raise _error("密码至少 6 位")
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
                raise _error("账户不存在", 404)
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(new_password), uid))

    def admin_set_status(self, uid: int, disabled: bool, operator_id: int) -> None:
        """禁用/启用账户；管理员不能禁用自己。"""
        if uid == operator_id:
            raise _error("不能禁用当前登录的管理员账户")
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
                raise _error("账户不存在", 404)
            db.execute("UPDATE users SET status=? WHERE id=?", (1 if disabled else 0, uid))

    def admin_delete_user(self, uid: int, operator_id: int) -> None:
        """删除账户并级联清理其历史分析、自配模型与问答记录；不能删除自己。"""
        if uid == operator_id:
            raise _error("不能删除当前登录的管理员账户")
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM users WHERE id=?", (uid,)).fetchone():
                raise _error("账户不存在", 404)
            db.execute("DELETE FROM runs WHERE user_id=?", (uid,))
            db.execute("DELETE FROM ai_model WHERE user_id=?", (uid,))
            db.execute("DELETE FROM ai_conversation WHERE user_id=?", (uid,))
            db.execute("DELETE FROM users WHERE id=?", (uid,))

    # --- 验证码 ---
    def create_captcha(self) -> tuple[str, str]:
        """生成一次性验证码，返回 (captcha_id, svg)。"""
        code = make_captcha_text()
        captcha_id = secrets.token_hex(12)
        with self.connect() as db:
            db.execute("DELETE FROM captchas WHERE expires < ?", (time.time(),))
            db.execute("INSERT INTO captchas (id,code,expires) VALUES (?,?,?)", (captcha_id, code, time.time() + CAPTCHA_TTL_SECONDS))
        return captcha_id, captcha_svg(code)

    def consume_captcha(self, captcha_id: str, code: str) -> bool:
        """校验并立即作废验证码（防重放）。"""
        with self.connect() as db:
            row = db.execute("SELECT code, expires FROM captchas WHERE id=?", (captcha_id or "",)).fetchone()
            db.execute("DELETE FROM captchas WHERE id=?", (captcha_id or "",))
        if not row or row["expires"] < time.time():
            return False
        return bool(code) and row["code"].upper() == str(code).strip().upper()

    # --- 供应商注册表 ---
    def list_providers(self, enabled_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM ai_provider" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY sort_order, id"
        with self.connect() as db:
            rows = db.execute(sql).fetchall()
        return [{"id": row["id"], "providerKey": row["provider_key"], "name": row["name"], "protocol": row["protocol"],
                 "baseUrl": row["base_url"], "consoleUrl": row["console_url"], "modelDocUrl": row["model_doc_url"],
                 "enabled": bool(row["enabled"]), "sortOrder": row["sort_order"]} for row in rows]

    def save_provider(self, data: Mapping[str, Any], provider_id: int | None = None) -> dict:
        """新增/编辑供应商（后台）。"""
        name = _string(data.get("name"), "供应商名称", 64, required=True)
        provider_key = _string(data.get("providerKey") or data.get("provider_key"), "供应商标识", 32)
        protocol = _string(data.get("protocol") or "openai", "接口类型", 32) or "openai"
        base_url = _string(data.get("baseUrl") or data.get("base_url"), "接口地址", 255)
        console_url = _string(data.get("consoleUrl") or data.get("console_url"), "控制台链接", 255)
        model_doc_url = _string(data.get("modelDocUrl") or data.get("model_doc_url"), "模型文档链接", 255)
        enabled = 1 if (data.get("enabled") is None or data.get("enabled")) else 0
        try:
            sort_order = int(data.get("sortOrder") or data.get("sort_order") or 0)
        except (TypeError, ValueError):
            raise _error("排序序号必须是整数")
        if not name:
            raise _error("请输入供应商名称")
        if not provider_key or not PROVIDER_KEY_RE.match(provider_key):
            raise _error("供应商标识需为 2-32 位小写字母、数字或下划线")
        if protocol not in PROTOCOLS:
            raise _error("接口类型仅支持 openai 或 anthropic")
        for label, url in (("接口地址", base_url), ("控制台链接", console_url), ("模型文档链接", model_doc_url)):
            if url and not HTTP_URL_RE.match(url):
                raise _error(f"{label}需以 http(s):// 开头")
        with self.connect() as db:
            dup = db.execute("SELECT id FROM ai_provider WHERE provider_key=?", (provider_key,)).fetchone()
            if dup and dup["id"] != provider_id:
                raise _error("该供应商标识已存在", 409)
            if provider_id is None:
                cursor = db.execute(
                    "INSERT INTO ai_provider (provider_key,name,protocol,base_url,console_url,model_doc_url,enabled,sort_order) "
                    "VALUES (?,?,?,?,?,?,?,?)", (provider_key, name, protocol, base_url, console_url, model_doc_url, enabled, sort_order))
                provider_id = cursor.lastrowid
            else:
                if not db.execute("SELECT 1 FROM ai_provider WHERE id=?", (provider_id,)).fetchone():
                    raise _error("供应商不存在", 404)
                db.execute(
                    "UPDATE ai_provider SET provider_key=?,name=?,protocol=?,base_url=?,console_url=?,model_doc_url=?,enabled=?,sort_order=? WHERE id=?",
                    (provider_key, name, protocol, base_url, console_url, model_doc_url, enabled, sort_order, provider_id))
            row = db.execute("SELECT * FROM ai_provider WHERE id=?", (provider_id,)).fetchone()
        return {
            "id": row["id"], "providerKey": row["provider_key"], "name": row["name"], "protocol": row["protocol"],
            "baseUrl": row["base_url"], "consoleUrl": row["console_url"], "modelDocUrl": row["model_doc_url"],
            "enabled": bool(row["enabled"]), "sortOrder": row["sort_order"]}

    def delete_provider(self, provider_id: int) -> None:
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM ai_provider WHERE id=?", (provider_id,)).fetchone():
                raise _error("供应商不存在", 404)
            db.execute("DELETE FROM ai_provider WHERE id=?", (provider_id,))

    # --- 用户模型配置 ---
    def list_models(self, user_id: int) -> dict:
        """返回 {list, selectedId, platform}，字段与 template GET /ai/models 对齐。

        list 仅含自配项（平台引用行不占列表，单独在 platform 分组返回）；
        排序：使用中优先、其余按添加时间倒序。
        """
        box = self.secret_box()
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM ai_model WHERE user_id=? AND platform_id IS NULL ORDER BY is_selected DESC, id DESC",
                (user_id,)).fetchall()
            platform = db.execute("SELECT * FROM ai_platform_model WHERE enabled=1 ORDER BY sort_order, id").fetchall()
            used = db.execute(
                "SELECT platform_id, is_selected FROM ai_model WHERE user_id=? AND platform_id IS NOT NULL", (user_id,)).fetchall()
        used_map = {row["platform_id"]: row["is_selected"] for row in used}
        selected = next((row for row in rows if row["is_selected"]), None)
        return {"list": [_model_view(box, row) for row in rows], "selectedId": selected["id"] if selected else None,
                "platform": [{"id": row["id"], "name": row["name"], "protocol": row["protocol"], "modelId": row["model_id"],
                              "isSelected": used_map.get(row["id"]) == 1} for row in platform]}

    def _normalize_model_input(self, data: Mapping[str, Any]) -> dict:
        """校验并规范模型表单输入（与 template add_user_model/update_user_model 相同口径）。"""
        provider = _string(data.get("provider"), "供应商", 32, required=True)
        protocol = _string(data.get("protocol") or "openai", "接口类型", 32) or "openai"
        base_url = _string(data.get("baseUrl") or data.get("base_url"), "接口地址", 255, required=True)
        model_id = _string(data.get("modelId") or data.get("model_id"), "模型 ID", 128, required=True)
        display_name = _string(data.get("displayName") or data.get("display_name"), "展示名称", 64)
        api_key = _string(data.get("apiKey") or data.get("api_key"), "API Key", 255)
        if protocol not in PROTOCOLS:
            raise _error("接口类型仅支持 openai 或 anthropic")
        if not HTTP_URL_RE.match(base_url):
            raise _error("接口地址需以 http(s):// 开头")
        if not model_id:
            raise _error("请输入模型 ID")
        with self.connect() as db:
            provider_row = db.execute("SELECT protocol, base_url FROM ai_provider WHERE provider_key=?", (provider,)).fetchone()
        if not provider_row:
            raise _error("供应商不存在，请重新选择")
        if base_url == provider_row["base_url"] and provider_row["base_url"]:
            base_url = provider_row["base_url"]
        return {"provider": provider, "protocol": protocol, "baseUrl": base_url, "modelId": model_id,
                "displayName": display_name, "apiKey": api_key}

    def add_model(self, user_id: int, data: Mapping[str, Any]) -> None:
        """新增自配模型；需填 API 密钥，上限 6 套，首套自动「使用中」。"""
        item = self._normalize_model_input(data)
        if not item["apiKey"]:
            raise _error("请填写 API 密钥")
        with self.connect() as db:
            count = db.execute("SELECT COUNT(*) AS c FROM ai_model WHERE user_id=?", (user_id,)).fetchone()["c"]
            if count >= MODEL_LIMIT:
                raise _error(f"最多添加 {MODEL_LIMIT} 个模型，请先删除不用的配置")
            first = count == 0
            db.execute(
                "INSERT INTO ai_model (user_id,platform_id,provider_key,protocol,base_url,model_id,display_name,api_key_enc,is_selected,created) "
                "VALUES (?,NULL,?,?,?,?,?,?,?,?)",
                (user_id, item["provider"], item["protocol"], item["baseUrl"], item["modelId"], item["displayName"],
                 self.secret_box().encrypt(item["apiKey"]), 1 if first else 0, time.time()))

    def update_model(self, user_id: int, model_id: int, data: Mapping[str, Any]) -> None:
        """编辑自配模型；API Key 留空则保留原值。"""
        item = self._normalize_model_input(data)
        with self.lock, self.connect() as db:
            row = db.execute("SELECT * FROM ai_model WHERE id=? AND user_id=? AND platform_id IS NULL", (model_id, user_id)).fetchone()
            if not row:
                raise _error("模型不存在或无权操作", 404)
            cipher = self.secret_box().encrypt(item["apiKey"]) if item["apiKey"] else row["api_key_enc"]
            db.execute(
                "UPDATE ai_model SET provider_key=?,protocol=?,base_url=?,model_id=?,display_name=?,api_key_enc=? WHERE id=?",
                (item["provider"], item["protocol"], item["baseUrl"], item["modelId"], item["displayName"], cipher, model_id))

    def delete_model(self, user_id: int, model_id: int) -> None:
        """删除自配模型；删除「使用中」项时自动回落到最新一条自配配置。"""
        with self.lock, self.connect() as db:
            row = db.execute("SELECT * FROM ai_model WHERE id=? AND user_id=? AND platform_id IS NULL", (model_id, user_id)).fetchone()
            if not row:
                raise _error("模型不存在或无权操作", 404)
            db.execute("DELETE FROM ai_model WHERE id=?", (model_id,))
            if row["is_selected"]:
                fallback = db.execute(
                    "SELECT id FROM ai_model WHERE user_id=? AND platform_id IS NULL ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
                if fallback:
                    db.execute("UPDATE ai_model SET is_selected=1 WHERE id=?", (fallback["id"],))

    def select_model(self, user_id: int, model_id: int) -> None:
        """切换「使用中」到某条自配模型。"""
        with self.lock, self.connect() as db:
            row = db.execute("SELECT id FROM ai_model WHERE id=? AND user_id=? AND platform_id IS NULL", (model_id, user_id)).fetchone()
            if not row:
                raise _error("模型不存在或无权操作", 404)
            db.execute("UPDATE ai_model SET is_selected=0 WHERE user_id=?", (user_id,))
            db.execute("UPDATE ai_model SET is_selected=1 WHERE id=?", (model_id,))

    def select_platform_model(self, user_id: int, platform_id: int) -> None:
        """选用平台托管模型：清空「使用中」后写入引用行。"""
        with self.lock, self.connect() as db:
            platform = db.execute("SELECT * FROM ai_platform_model WHERE id=? AND enabled=1", (platform_id,)).fetchone()
            if not platform:
                raise _error("平台模型不存在或未启用", 404)
            db.execute("UPDATE ai_model SET is_selected=0 WHERE user_id=?", (user_id,))
            ref = db.execute("SELECT id FROM ai_model WHERE user_id=? AND platform_id=?", (user_id, platform_id)).fetchone()
            if ref:
                db.execute("UPDATE ai_model SET is_selected=1, provider_key='platform', protocol=?, base_url=?, model_id=?, display_name=? WHERE id=?",
                           (platform["protocol"], platform["base_url"], platform["model_id"], platform["name"], ref["id"]))
            else:
                db.execute(
                    "INSERT INTO ai_model (user_id,platform_id,provider_key,protocol,base_url,model_id,display_name,api_key_enc,is_selected,created) "
                    "VALUES (?,?,?,?,?,?,'',?,1,?)",
                    (user_id, platform_id, "platform", platform["protocol"], platform["base_url"], platform["model_id"], platform["name"], time.time()))

    def remove_platform_model(self, user_id: int, platform_id: int) -> None:
        """移除平台托管模型引用；若原为「使用中」则回落到最新自配配置。"""
        with self.lock, self.connect() as db:
            ref = db.execute("SELECT * FROM ai_model WHERE user_id=? AND platform_id=?", (user_id, platform_id)).fetchone()
            if not ref:
                raise _error("未选用该平台模型", 404)
            db.execute("DELETE FROM ai_model WHERE id=?", (ref["id"],))
            fallback = db.execute(
                "SELECT id FROM ai_model WHERE user_id=? AND platform_id IS NULL ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
            if fallback:
                db.execute("UPDATE ai_model SET is_selected=1 WHERE id=?", (fallback["id"],))

    def get_model_row(self, user_id: int, model_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute("SELECT * FROM ai_model WHERE id=? AND user_id=?", (model_id, user_id)).fetchone()

    def get_platform_row(self, platform_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute("SELECT * FROM ai_platform_model WHERE id=?", (platform_id,)).fetchone()

    # --- 平台托管模型（后台） ---
    def admin_list_platform(self) -> list[dict]:
        box = self.secret_box()
        with self.connect() as db:
            rows = db.execute("SELECT * FROM ai_platform_model ORDER BY sort_order, id").fetchall()
        # 第一个启用项即默认生效配置（未自配模型用户与匿名会话实际调用的模型）
        default_id = next((row["id"] for row in rows if row["enabled"]), None)
        return [{"id": row["id"], "name": row["name"], "provider": row["provider"] if "provider" in row.keys() else "",
                 "protocol": row["protocol"], "baseUrl": row["base_url"],
                 "modelId": row["model_id"], "keyMasked": _mask_cipher(box, row["api_key_enc"]) if row["api_key_enc"] else "",
                 "hasKey": bool(row["api_key_enc"]), "enabled": bool(row["enabled"]),
                 "isDefault": row["id"] == default_id, "sortOrder": row["sort_order"],
                 "createdAt": _ts(row["created"])} for row in rows]

    def admin_save_platform(self, data: Mapping[str, Any], platform_id: int | None = None) -> dict:
        """新增/编辑平台托管模型；API Key 留空保留原值，密文 Fernet 落库。provider 与前台模型配置同源。"""
        name = _string(data.get("name"), "名称", 64, required=True)
        provider = _string(data.get("provider") or data.get("provider_key"), "供应商标识", 32)
        protocol = _string(data.get("protocol") or "openai", "接口类型", 32) or "openai"
        base_url = _string(data.get("baseUrl") or data.get("base_url"), "接口地址", 255, required=True)
        model_id = _string(data.get("modelId") or data.get("model_id"), "模型 ID", 128, required=True)
        api_key = _string(data.get("apiKey") or data.get("api_key"), "API Key", 255)
        enabled = 1 if (data.get("enabled") is None or data.get("enabled")) else 0
        try:
            sort_order = int(data.get("sortOrder") or data.get("sort_order") or 0)
        except (TypeError, ValueError):
            raise _error("排序序号必须是整数")
        if not name:
            raise _error("请输入名称")
        if protocol not in PROTOCOLS:
            raise _error("接口类型仅支持 openai 或 anthropic")
        if not HTTP_URL_RE.match(base_url):
            raise _error("接口地址需以 http(s):// 开头")
        if not model_id:
            raise _error("请输入模型 ID")
        with self.lock, self.connect() as db:
            if platform_id is None:
                if not api_key:
                    raise _error("请输入 API Key")
                cipher = self.secret_box().encrypt(api_key)
                cursor = db.execute(
                    "INSERT INTO ai_platform_model (name,provider,protocol,base_url,model_id,api_key_enc,enabled,sort_order,created) VALUES (?,?,?,?,?,?,?,?,?)",
                    (name, provider, protocol, base_url, model_id, cipher, enabled, sort_order, time.time()))
                platform_id = cursor.lastrowid
            else:
                row = db.execute("SELECT * FROM ai_platform_model WHERE id=?", (platform_id,)).fetchone()
                if not row:
                    raise _error("平台模型不存在", 404)
                cipher = self.secret_box().encrypt(api_key) if api_key else row["api_key_enc"]
                db.execute(
                    "UPDATE ai_platform_model SET name=?,provider=?,protocol=?,base_url=?,model_id=?,api_key_enc=?,enabled=?,sort_order=? WHERE id=?",
                    (name, provider, protocol, base_url, model_id, cipher, enabled, sort_order, platform_id))
            db.execute("UPDATE ai_model SET display_name=? WHERE platform_id=?", (name, platform_id))
        return {"id": platform_id}

    def admin_delete_platform(self, platform_id: int) -> None:
        with self.lock, self.connect() as db:
            if not db.execute("SELECT 1 FROM ai_platform_model WHERE id=?", (platform_id,)).fetchone():
                raise _error("平台模型不存在", 404)
            db.execute("DELETE FROM ai_model WHERE platform_id=?", (platform_id,))
            db.execute("DELETE FROM ai_platform_model WHERE id=?", (platform_id,))

    # --- 历史对话 ---
    def log_conversation(self, user_id: int, question: str, answer: str, run_id: str | None = None) -> None:
        """留痕一条 AI 问答（失败不影响主流程，由调用方吞异常）。"""
        with self.connect() as db:
            db.execute("INSERT INTO ai_conversation (user_id,question,answer,run_id,created) VALUES (?,?,?,?,?)",
                       (user_id, question[:2000], (answer or "")[:4000], run_id, time.time()))

    def history(self, user_id: int) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT id, question, answer, run_id, created FROM ai_conversation WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, HISTORY_LIMIT)).fetchall()
        return [{"id": row["id"], "question": row["question"], "answer": row["answer"], "runId": row["run_id"],
                 "createdAt": _iso(row["created"])} for row in rows]

    def delete_history_item(self, user_id: int, history_id: int) -> None:
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM ai_conversation WHERE id=? AND user_id=?", (history_id, user_id)).fetchone():
                raise _error("记录不存在", 404)
            db.execute("DELETE FROM ai_conversation WHERE id=?", (history_id,))

    def clear_history(self, user_id: int) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM ai_conversation WHERE user_id=?", (user_id,))


# ---- 鉴权守卫 ----

def _auth(request) -> AuthStore:
    return request.app.state.auth


def current_user(request) -> sqlite3.Row | None:
    """从 Authorization: Bearer JWT 解析当前用户；未登录/无效返回 None。"""
    header = request.headers.get("authorization") or ""
    if not header.startswith("Bearer "):
        return None
    uid = jwt_verify(header[7:].strip(), _auth(request).secret_key())
    if uid is None:
        return None
    return _auth(request).get_user(uid)


def require_user(request) -> sqlite3.Row:
    user = current_user(request)
    if not user:
        raise _error("请先登录", 401)
    if user["status"] == 1:
        raise _error("账户已被禁用，请联系管理员", 403)
    return user


def require_admin(request) -> sqlite3.Row:
    user = require_user(request)
    if user["role"] != 1:
        raise _error("需要管理员权限", 403)
    return user


# ---- 认证端点 ----

async def auth_captcha(request):
    """GET /api/auth/captcha：{captchaId, imageBase64}；DEBUG=1 时附带 debugCode。"""
    captcha_id, svg = _auth(request).create_captcha()
    image = "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
    result = {"captchaId": captcha_id, "imageBase64": image}
    if os.environ.get("DEBUG", "").strip() == "1":
        result["debugCode"] = ""  # 与 template 口径一致：不向客户端下发明文
    return JSONResponse(result)


async def auth_register(request):
    """POST /api/auth/register：验证码 + 用户名/密码校验，签发 JWT。"""
    payload = await _payload(request, {"username", "password", "captchaId", "captchaCode"})
    code = _string(payload.get("captchaCode"), "验证码", 8, required=True)
    if not _auth(request).consume_captcha(_string(payload.get("captchaId"), "验证码标识", 64, required=True), code):
        raise _error("验证码错误或已过期")
    username = _string(payload.get("username"), "用户名", 32, required=True)
    password = _string(payload.get("password"), "密码", 64, required=True)
    nickname = _string(payload.get("nickname"), "昵称", 32)
    if not USERNAME_RE.match(username):
        raise _error("用户名需为 3-32 位字母、数字或下划线")
    if len(password) < 6:
        raise _error("密码至少 6 位")
    user = _auth(request).create_user(username, password, nickname)
    token = jwt_sign(user["id"], _auth(request).secret_key())
    return JSONResponse({"token": token, "user": _public_user(user)})


async def auth_login(request):
    """POST /api/auth/login：验证码 + 口令校验，签发 JWT 并写 last_login。"""
    payload = await _payload(request, {"username", "password", "captchaId", "captchaCode"})
    code = _string(payload.get("captchaCode"), "验证码", 8, required=True)
    if not _auth(request).consume_captcha(_string(payload.get("captchaId"), "验证码标识", 64, required=True), code):
        raise _error("验证码错误或已过期")
    username = _string(payload.get("username"), "用户名", 32, required=True)
    password = _string(payload.get("password"), "密码", 64, required=True)
    user = _auth(request).find_user_by_username(username)
    if not user or not verify_password(password, user["password_hash"]):
        raise _error("用户名或密码错误", 401)
    if user["status"] == 1:
        raise _error("账户已被禁用，请联系管理员", 403)
    _auth(request).touch_login(user["id"])
    token = jwt_sign(user["id"], _auth(request).secret_key())
    return JSONResponse({"token": token, "user": _public_user(user)})


async def auth_me(request):
    """GET /api/auth/me：返回当前登录用户。"""
    return JSONResponse({"user": _public_user(require_user(request))})


# ---- AI 模型端点（登录用户） ----

async def ai_providers(request):
    """GET /api/ai/providers：启用中的供应商注册表。"""
    require_user(request)
    return JSONResponse({"list": _auth(request).list_providers(enabled_only=True)})


async def ai_models(request):
    """GET/POST /api/ai/models：模型列表 / 新增自配模型。"""
    user = require_user(request)
    if request.method == "GET":
        return JSONResponse(_auth(request).list_models(user["id"]))
    payload = await _payload(request, set())
    _auth(request).add_model(user["id"], payload)
    return JSONResponse({"ok": True, "message": "模型已添加", "models": _auth(request).list_models(user["id"])})


async def ai_model_item(request):
    """PUT/DELETE /api/ai/models/{id}：编辑（API Key 留空保留）/ 删除（使用中自动回落）。"""
    user = require_user(request)
    try:
        model_id = int(request.path_params["model_id"])
    except (KeyError, ValueError):
        raise _error("模型 ID 不正确", 404)
    if request.method == "PUT":
        payload = await _payload(request, set())
        _auth(request).update_model(user["id"], model_id, payload)
        return JSONResponse({"ok": True, "message": "配置已保存", "models": _auth(request).list_models(user["id"])})
    _auth(request).delete_model(user["id"], model_id)
    return JSONResponse({"ok": True, "message": "已删除", "models": _auth(request).list_models(user["id"])})


async def ai_model_select(request):
    """PUT /api/ai/models/{id}/select：切换「使用中」。"""
    user = require_user(request)
    try:
        model_id = int(request.path_params["model_id"])
    except (KeyError, ValueError):
        raise _error("模型 ID 不正确", 404)
    _auth(request).select_model(user["id"], model_id)
    return JSONResponse({"ok": True, "models": _auth(request).list_models(user["id"])})


def _test_target_row(auth: AuthStore, user, model_id: int):
    """定位连通性测试目标行（自配模型或平台引用行）。"""
    row = auth.get_model_row(user["id"], model_id)
    if not row:
        raise _error("模型不存在或无权操作", 404)
    if row["platform_id"]:
        platform = auth.get_platform_row(row["platform_id"])
        if not platform:
            raise _error("平台模型不存在", 404)
        cipher = platform["api_key_enc"]
    else:
        cipher = row["api_key_enc"]
    if not cipher:
        raise _error("该模型未配置 API Key")
    return {"baseUrl": row["base_url"], "modelId": row["model_id"], "apiKey": auth.secret_box().decrypt(cipher)}


def _run_model_test(base_url: str, api_key: str, model_id: str) -> dict:
    """连通性测试：用 1 token 的最小补全验证地址、密钥与模型名可用（与 web_api._test_model 同口径）。"""
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=15, max_retries=0)
    completion = client.chat.completions.create(model=model_id, messages=[{"role": "user", "content": "ping"}], max_tokens=1)
    return {"ok": bool(completion and completion.choices), "model": model_id}


async def ai_model_test(request):
    """POST /api/ai/models/{id}/test：对自配模型发起连通性测试。"""
    from starlette.concurrency import run_in_threadpool

    user = require_user(request)
    try:
        model_id = int(request.path_params["model_id"])
    except (KeyError, ValueError):
        raise _error("模型 ID 不正确", 404)
    target = _test_target_row(_auth(request), user, model_id)
    try:
        result = await run_in_threadpool(_run_model_test, target["baseUrl"], target["apiKey"], target["modelId"])
    except Exception as exc:
        raise _error(f"连通性测试失败: {exc}", 502) from exc
    return JSONResponse({"ok": True, "message": "连通性测试通过", "test": result})


async def ai_platform_select(request):
    """PUT /api/ai/platform-models/{id}/select：选用平台托管模型。"""
    user = require_user(request)
    try:
        platform_id = int(request.path_params["model_id"])
    except (KeyError, ValueError):
        raise _error("平台模型 ID 不正确", 404)
    _auth(request).select_platform_model(user["id"], platform_id)
    return JSONResponse({"ok": True, "models": _auth(request).list_models(user["id"])})


async def ai_platform_remove(request):
    """DELETE /api/ai/platform-models/{id}：移除平台托管模型引用。"""
    user = require_user(request)
    try:
        platform_id = int(request.path_params["model_id"])
    except (KeyError, ValueError):
        raise _error("平台模型 ID 不正确", 404)
    _auth(request).remove_platform_model(user["id"], platform_id)
    return JSONResponse({"ok": True, "models": _auth(request).list_models(user["id"])})


# ---- 历史对话端点 ----

async def ai_history(request):
    """GET/DELETE /api/ai/history：最近 20 条 / 清空全部（历史分析中的问答留痕）。"""
    user = require_user(request)
    if request.method == "DELETE":
        _auth(request).clear_history(user["id"])
        return JSONResponse({"ok": True, "message": "已清空问答记录"})
    return JSONResponse({"list": _auth(request).history(user["id"])})


async def ai_history_item(request):
    """DELETE /api/ai/history/{id}：删除单条历史记录。"""
    user = require_user(request)
    try:
        history_id = int(request.path_params["history_id"])
    except (KeyError, ValueError):
        raise _error("记录不存在", 404)
    _auth(request).delete_history_item(user["id"], history_id)
    return JSONResponse({"ok": True, "message": "已删除"})


# ---- 后台管理端点（JWT role=1） ----

async def admin_ai_providers(request):
    """GET/POST /api/admin/ai-providers：供应商注册表管理。"""
    require_admin(request)
    if request.method == "POST":
        payload = await _payload(request, set())
        item = _auth(request).save_provider(payload)
        return JSONResponse({"ok": True, "message": "供应商已保存", "item": item})
    return JSONResponse({"list": _auth(request).list_providers()})


async def admin_ai_provider_item(request):
    """PUT/DELETE /api/admin/ai-providers/{id}。"""
    require_admin(request)
    try:
        provider_id = int(request.path_params["provider_id"])
    except (KeyError, ValueError):
        raise _error("供应商不存在", 404)
    if request.method == "PUT":
        payload = await _payload(request, set())
        item = _auth(request).save_provider(payload, provider_id)
        return JSONResponse({"ok": True, "message": "供应商已保存", "item": item})
    _auth(request).delete_provider(provider_id)
    return JSONResponse({"ok": True, "message": "已删除"})


async def admin_platform_models(request):
    """GET/POST /api/admin/platform-models：平台托管模型管理（密钥仅掩码回显）。"""
    require_admin(request)
    if request.method == "POST":
        payload = await _payload(request, set())
        _auth(request).admin_save_platform(payload)
        return JSONResponse({"ok": True, "message": "平台模型已保存"})
    return JSONResponse({"list": _auth(request).admin_list_platform()})


async def admin_platform_model_item(request):
    """PUT/DELETE /api/admin/platform-models/{id}：编辑（API Key 留空保留）/ 删除。"""
    require_admin(request)
    try:
        platform_id = int(request.path_params["model_id"])
    except (KeyError, ValueError):
        raise _error("平台模型不存在", 404)
    if request.method == "PUT":
        payload = await _payload(request, set())
        _auth(request).admin_save_platform(payload, platform_id)
        return JSONResponse({"ok": True, "message": "平台模型已保存"})
    _auth(request).admin_delete_platform(platform_id)
    return JSONResponse({"ok": True, "message": "已删除"})


async def admin_platform_model_test(request):
    """POST /api/admin/platform-models/{id}/test：平台托管模型连通性测试。"""
    from starlette.concurrency import run_in_threadpool

    require_admin(request)
    try:
        platform_id = int(request.path_params["model_id"])
    except (KeyError, ValueError):
        raise _error("平台模型不存在", 404)
    platform = _auth(request).get_platform_row(platform_id)
    if not platform:
        raise _error("平台模型不存在", 404)
    if not platform["api_key_enc"]:
        raise _error("该模型未配置 API Key")
    try:
        result = await run_in_threadpool(
            _run_model_test, platform["base_url"], _auth(request).secret_box().decrypt(platform["api_key_enc"]), platform["model_id"])
    except Exception as exc:
        raise _error(f"连通性测试失败: {exc}", 502) from exc
    return JSONResponse({"ok": True, "message": "连通性测试通过", "test": result})


async def admin_users(request):
    """GET /api/admin/users：全部账户清单（含分析数量、状态）。"""
    require_admin(request)
    return JSONResponse({"list": _auth(request).list_users()})


async def admin_user_reset_password(request):
    """POST /api/admin/users/{user_id}/reset-password：重置指定账户密码。"""
    require_admin(request)
    try:
        user_id = int(request.path_params["user_id"])
    except (KeyError, ValueError):
        raise _error("账户不存在", 404)
    payload = await _payload(request, {"password"})
    new_password = _string(payload.get("password"), "新密码", 64, required=True)
    _auth(request).admin_reset_password(user_id, new_password)
    return JSONResponse({"ok": True, "message": "密码已重置"})


async def admin_user_status(request):
    """POST /api/admin/users/{user_id}/status：禁用/启用账户（不能操作自己）。"""
    admin = require_admin(request)
    try:
        user_id = int(request.path_params["user_id"])
    except (KeyError, ValueError):
        raise _error("账户不存在", 404)
    payload = await _payload(request, {"disabled"})
    disabled = bool(payload.get("disabled"))
    _auth(request).admin_set_status(user_id, disabled, admin["id"])
    return JSONResponse({"ok": True, "message": "账户已禁用" if disabled else "账户已启用"})


async def admin_user_delete(request):
    """DELETE /api/admin/users/{user_id}：删除账户并级联清理其数据（不能删除自己）。"""
    admin = require_admin(request)
    try:
        user_id = int(request.path_params["user_id"])
    except (KeyError, ValueError):
        raise _error("账户不存在", 404)
    _auth(request).admin_delete_user(user_id, admin["id"])
    return JSONResponse({"ok": True, "message": "账户已删除"})
