"""Same-origin HTTP API for the independent Finbridge website.

This module intentionally has no Streamlit dependency. Browser sessions and
immutable task snapshots live in SQLite; model credentials stay on the server.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from copy import deepcopy
import csv
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from urllib.parse import quote
from typing import Any, Mapping
from urllib.parse import urlsplit
import zipfile

import pandas as pd
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from finbridge.agent import FinancialAgent, AgentConfigurationError, AgentRequestError
from finbridge.data import load_uploaded_financial_data
from finbridge.data import FIELD_CATALOG
from finbridge.template import financial_template_xlsx, financial_template_csv
from finbridge.task_agent import run_task_agent
from finbridge.secret_box import SecretBox, generate_master_key
from finbridge.model_resolver import resolve_llm_settings
from finbridge.ai_insights import generate_insight
from finbridge.web_auth import (
    AuthStore, auth_captcha, auth_register, auth_login, auth_me,
    ai_providers, ai_models, ai_model_item, ai_model_select, ai_model_test,
    ai_platform_select, ai_platform_remove, ai_history, ai_history_item,
    admin_ai_providers, admin_ai_provider_item, admin_platform_models,
    admin_platform_model_item, admin_platform_model_test, jwt_verify,
    admin_users, admin_user_reset_password, admin_user_status, admin_user_delete,
)
from finbridge.workflow import (
    DATA_FIELDS, GOALS, KNOWLEDGE, LABELS, TOOLS, DiligenceRun, check_data,
    clean_data, delivery_zip, fingerprint, report_html, report_markdown,
    simulate_repayment,
)

ROOT = Path(__file__).resolve().parents[2]
COOKIE = "finbridge_session"
SESSION_SECONDS = 7 * 24 * 60 * 60
MAX_SESSIONS = 200
MAX_RUNS = 12
MAX_RUNNING = 4
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_JSON_BYTES = 128 * 1024
DATA_METADATA = {"company_name", "report_period", "industry", "region", "years_in_operation", "purpose", "source_sheet", "amount_unit", "statement_schema", "public_provenance", "public_source","financial_history","listing_status","listing_market","security_code","input_contract"}
PROFILE_FIELDS = {"amount", "internal_funds", "months", "purpose", "assumed_rate", "collateral", "receivables", "industry", "region", "objective"}
DEFAULT_PROFILE = {
    "amount": 3_000_000.0, "internal_funds": 500_000.0, "months": 24,
    "purpose": "经营周转", "assumed_rate": 0.055, "collateral": "未确认", "receivables": "可提供",
    "industry": "高端制造", "region": "江苏苏州",
    "objective": "按所选分析重点，结合下方确认的金额、用途和期限，说明计算结果、主要问题及下一步建议。",
}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _error(message: str, status: int = 400) -> HTTPException:
    return HTTPException(status, message)


def _string(value: Any, label: str, limit: int, *, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise _error(f"{label}须为不超过{limit}字的文本")
    value = value.strip()
    if required and not value:
        raise _error(f"请填写{label}")
    return value


def _number(value: Any, label: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high or not math.isfinite(value):
        raise _error(f"{label}须为{low:g}至{high:g}之间的有限数值")
    return float(value)


def validate_profile(value: Any, previous: Mapping[str, Any]) -> dict[str, Any]:
    if previous.get("analysis_mode") == "public-v2" or isinstance(value,dict) and value.get("analysis_mode") == "public-v2":
        from finbridge.public_finance import LIMITS,REQUEST_KEYS,validate_request
        from finbridge.public_finance import public_profile
        if not isinstance(value,dict) or set(value)-(set(LIMITS)|REQUEST_KEYS|{"analysis_mode","objective","industry","region"}):
            raise _error("只接受借款需求与情景假设，不接受内部授信或担保额度")
        merged=dict(previous,**value)
        if previous.get('decision_scope')=='working-capital-12m':merged['decision_scope']='working-capital-12m'
        for key,(lo,hi) in LIMITS.items():
            if merged.get(key) is not None:merged[key]=_number(merged[key],key,lo,hi)
        merged["objective"]=_string(merged.get("objective",""),"任务说明",2000)
        try:validate_request(merged)
        except ValueError as exc:raise _error(str(exc))
        return public_profile({"industry":merged.get("industry","未披露"),"region":merged.get("region","未披露")},merged)
    if not isinstance(value, dict) or set(value) - PROFILE_FIELDS:
        raise _error("融资需求包含不支持的字段")
    profile = dict(previous, **value)
    for key, label, upper in (("amount", "资金需求", 1e15), ("internal_funds", "自有资金", 1e15), ("assumed_rate", "假设年利率", 1)):
        profile[key] = _number(profile[key], label, 0, upper)
    months = _number(profile["months"], "融资期限", 1, 120)
    if months != int(months):
        raise _error("融资期限须为整数个月")
    profile["months"] = int(months)
    if not isinstance(profile["purpose"], str) or profile["purpose"] not in {"经营周转", "订单备货", "设备购置", "综合融资"}:
        raise _error("请选择受支持的资金用途")
    for key in ("collateral", "receivables"):
        if not isinstance(profile[key], str) or profile[key] not in {"未确认", "可提供", "无"}:
            raise _error("担保与应收债权条件无效")
    for key, label, limit in (("industry", "所属行业", 100), ("region", "所在地区", 100), ("objective", "任务说明", 2000)):
        profile[key] = _string(profile[key], label, limit)
    return profile


def validate_data(value: Any) -> dict[str, Any]:
    if isinstance(value,dict) and value.get("statement_schema") == "public-v2":
        from finbridge.public_data import PUBLIC_KEYS,PUBLIC_LABELS
        if set(value)-PUBLIC_KEYS:raise _error("公开报表模式不接受内部额度、预算或非公开字段")
        result={}
        for key,item in value.items():
            if key in PUBLIC_LABELS:result[key]=None if item is None else _number(item,PUBLIC_LABELS[key],-1e15,1e15)
            elif key=="public_provenance":
                if not isinstance(item,dict):raise _error("公开来源位置格式无效")
                result[key]=item
            elif key=='financial_history':
                from finbridge.financial_history import validate_history
                try:result[key]=validate_history(item)
                except ValueError as exc:raise _error(str(exc)) from exc
            else:result[key]=_string(item,key,1000,required=key=="company_name")
        if not result.get("company_name"):raise _error("请填写企业名称")
        if result.get('financial_history'):
            from finbridge.financial_history import annual_records,flatten_history
            try:result=flatten_history(result,annual_records(result))
            except ValueError as exc:raise _error(str(exc)) from exc
        return result
    if not isinstance(value, dict) or set(value) - (set(DATA_FIELDS) | DATA_METADATA):
        raise _error("企业数据包含不支持的字段")
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key in DATA_FIELDS or key == "years_in_operation":
            result[key] = None if item is None else _number(item, LABELS.get(key, key), -1e15, 1e15)
        else:
            result[key] = _string(item, LABELS.get(key, key), 500 if key == "source_sheet" else 100, required=key == "company_name")
    if not result.get("company_name"):
        raise _error("请填写企业名称")
    return result


def _demo_profile(data: Mapping[str, Any], previous: Mapping[str, Any]) -> dict[str, Any]:
    """Load case funding inputs without treating channel terms as task terms."""
    if data.get("statement_schema") == "public-v2":
        from finbridge.public_finance import public_profile
        from finbridge.real_case import find_real_case
        case=find_real_case(data)
        if case:return public_profile(data,case['profile'])
        return public_profile(data)
    purpose = data.get("purpose") or "经营周转"
    return validate_profile({
        "amount": data.get("financing_need") if data.get("financing_need") is not None else 0,
        "internal_funds": data.get("available_internal_funds") if data.get("available_internal_funds") is not None else 0,
        "purpose": purpose,
        "industry": data.get("industry") or "",
        "region": data.get("region") or "",
        "collateral": "未确认", "receivables": "未确认",
        "objective": "基于当前企业财务输入与已确认渠道容量，计算资金组合、假设成本和压力偿付能力。",
    }, previous)


def _read_demos() -> list[dict[str, Any]]:
    from finbridge.real_case import real_cases
    return [c['data'] for c in real_cases()]


def _case_source(data):
    from finbridge.real_case import is_real_case
    return ('真实算例 · ' if is_real_case(data) else '模拟案例 · ')+data['company_name']


class SessionStore:
    """Small bounded single-process store; no user data is shared across sessions."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, touched REAL NOT NULL, state TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                    created REAL NOT NULL, running INTEGER NOT NULL DEFAULT 0,
                    result TEXT NOT NULL, tasks TEXT NOT NULL DEFAULT '[]',
                    reviewed INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS session_runs ON runs(session_id, created DESC);
                CREATE TABLE IF NOT EXISTS decision_chats (
                    root_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, head_id TEXT NOT NULL,
                    messages TEXT NOT NULL DEFAULT '[]', updated REAL NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS decision_workspace (
                    root_id TEXT NOT NULL, session_id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(root_id,session_id),
                    FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS app_meta (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                );
            """)
            # 账户级历史分析：runs 增加 user_id 归属（登录用户跨会话可见），去掉外键级联防止清理会话时误删账户记录
            run_columns = {row["name"] for row in db.execute("PRAGMA table_info(runs)").fetchall()}
            if "user_id" not in run_columns:
                db.executescript("""
                    CREATE TABLE runs_migrated (
                        id TEXT PRIMARY KEY, session_id TEXT NOT NULL, user_id INTEGER,
                        created REAL NOT NULL, running INTEGER NOT NULL DEFAULT 0,
                        result TEXT NOT NULL, tasks TEXT NOT NULL DEFAULT '[]',
                        reviewed INTEGER NOT NULL DEFAULT 0
                    );
                    INSERT INTO runs_migrated SELECT id,session_id,NULL,created,running,result,tasks,reviewed FROM runs;
                    DROP TABLE runs;
                    ALTER TABLE runs_migrated RENAME TO runs;
                """)
            db.execute("CREATE INDEX IF NOT EXISTS user_runs ON runs(user_id, created DESC)")
            # Work cannot silently remain in progress after a process restart.
            for row in db.execute("SELECT id,result FROM runs WHERE running=1").fetchall():
                result = json.loads(row["result"])
                result.update(status="执行中断", error="服务重启使任务中断，请重新启动任务；已执行证据仍保留。")
                db.execute("UPDATE runs SET running=0,result=? WHERE id=?", (_json(result), row["id"]))

    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return closing_transaction(db)

    def session(self, token: str | None) -> tuple[str, dict[str, Any], bool]:
        now = time.time()
        with self.lock, self.connect() as db:
            # 会话过期清理：账户级分析记录（user_id 非空）不受影响，匿名记录随会话删除
            db.execute("DELETE FROM runs WHERE user_id IS NULL AND session_id NOT IN (SELECT id FROM sessions)")
            db.execute("DELETE FROM sessions WHERE touched < ? AND id NOT IN (SELECT session_id FROM runs WHERE running=1)", (now - SESSION_SECONDS,))
            db.execute("DELETE FROM decision_workspace WHERE session_id NOT IN (SELECT id FROM sessions)")
            row = db.execute("SELECT state FROM sessions WHERE id=?", (token,)).fetchone() if token and re.fullmatch(r"[a-f0-9]{64}", token) else None
            if row:
                db.execute("UPDATE sessions SET touched=? WHERE id=?", (now, token))
                state=json.loads(row["state"])
                if state["data"].get("statement_schema")!="public-v2" and _read_demos()[0].get("statement_schema")=="public-v2":
                    from finbridge.public_data import public_only
                    from finbridge.public_finance import public_profile
                    state["data"]=public_only(state["data"])
                    state["profile"]=public_profile(state["data"])
                    db.execute("UPDATE sessions SET state=? WHERE id=?",(_json(state),token))
                return token,state,False
            count = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            if count >= MAX_SESSIONS:
                oldest = db.execute("SELECT id FROM sessions WHERE id NOT IN (SELECT session_id FROM runs WHERE running=1) ORDER BY touched LIMIT 1").fetchone()
                if not oldest:
                    raise _error("当前访问人数较多，请稍后重试", 503)
                # 被淘汰会话中的账户级分析记录保留，仅会话状态删除
                db.execute("UPDATE runs SET session_id='orphan' WHERE session_id=? AND user_id IS NOT NULL", (oldest["id"],))
                db.execute("DELETE FROM sessions WHERE id=?", (oldest["id"],))
            token = secrets.token_hex(32)
            data = _read_demos()[0]
            state = {"data": data, "profile": _demo_profile(data, DEFAULT_PROFILE), "source": _case_source(data), "active_run_id": None}
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (token, now, _json(state)))
            return token, state, True

    def state(self, token: str) -> dict[str, Any]:
        with self.connect() as db:
            row = db.execute("SELECT state FROM sessions WHERE id=?", (token,)).fetchone()
        if not row:
            raise _error("会话已过期，请刷新页面", 401)
        return json.loads(row["state"])

    def has_running(self, token: str, uid: int | None = None) -> bool:
        # 该浏览器会话或登录账户是否有执行中的分析任务
        where, params = self._owner_where(token, uid)
        with self.connect() as db:
            return bool(db.execute(f"SELECT 1 FROM runs WHERE running=1 AND {where} LIMIT 1", params).fetchone())

    def update(self, token: str, **changes: Any) -> dict[str, Any]:
        with self.lock, self.connect() as db:
            row = db.execute("SELECT state FROM sessions WHERE id=?", (token,)).fetchone()
            if not row:
                raise _error("会话已过期，请刷新页面", 401)
            state = json.loads(row["state"])
            state.update(changes)
            db.execute("UPDATE sessions SET state=?,touched=? WHERE id=?", (_json(state), time.time(), token))
            return state

    # ---- API 模型管理（平台托管 scope=platform / 用户自配 scope=user）----

    def secret_key(self) -> str:
        # 加密主密钥：环境变量 FINBRIDGE_ENC_KEY 优先；未设置时首次生成并落库 app_meta
        env = (os.getenv("FINBRIDGE_ENC_KEY") or "").strip()
        if env:
            return env
        with self.lock, self.connect() as db:
            row = db.execute("SELECT value FROM app_meta WHERE key='enc_key'").fetchone()
            if row:
                return row["value"]
            key = generate_master_key()
            db.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES ('enc_key',?)", (key,))
            return key

    def secret_box(self) -> SecretBox:
        return SecretBox(self.secret_key())

    @staticmethod
    def _owner_where(token: str, uid: int | None) -> tuple[str, list]:
        # 可见范围：本会话记录 + 登录账户的记录（匿名时仅本会话）
        if uid is None:
            return "session_id=?", [token]
        return "(session_id=? OR user_id=?)", [token, uid]

    def claim_runs_for_user(self, uid: int) -> int:
        # 启动回填：无归属记录归属管理员，并与该账户名下已有记录按企业合并去重，每企业仅保留最新一条
        with self.lock, self.connect() as db:
            rows = db.execute(
                "SELECT id,result,user_id FROM runs WHERE user_id IS NULL OR user_id=? ORDER BY created DESC", (uid,)
            ).fetchall()
            claimed, seen = 0, set()
            for row in rows:
                company = (json.loads(row["result"]).get("data") or {}).get("company_name") or ""
                if not company:
                    continue  # 无企业名的记录不参与去重，无归属的留待会话过期清理
                if company in seen:
                    db.execute("DELETE FROM runs WHERE id=?", (row["id"],))
                    continue
                seen.add(company)
                if row["user_id"] is None:
                    db.execute("UPDATE runs SET user_id=? WHERE id=?", (uid, row["id"]))
                    claimed += 1
            return claimed

    def drop_duplicate_runs(self, token: str, company: str, uid: int | None = None) -> None:
        # 案例重复载入时替换同企业的未复核分析，保持每个企业在历史分析中仅一份最新记录；已复核的视为正式资产不替换
        where, params = self._owner_where(token, uid)
        with self.lock, self.connect() as db:
            rows = db.execute(f"SELECT id,result,reviewed FROM runs WHERE running=0 AND {where}", params).fetchall()
            for row in rows:
                result = json.loads(row["result"])
                if not row["reviewed"] and (result.get("data") or {}).get("company_name") == company:
                    db.execute("DELETE FROM runs WHERE id=?", (row["id"],))

    def claim_run(self, token: str, run_id: str, uid: int | None = None) -> bool:
        # 历史分析恢复：将记录改绑到当前会话与登录账户，后续进度保存与更新正常归属
        with self.lock, self.connect() as db:
            cursor = db.execute("UPDATE runs SET session_id=?,user_id=? WHERE id=?", (token, uid, run_id))
            return cursor.rowcount > 0

    def list_runs(self, token: str, uid: int | None = None) -> list[dict[str, Any]]:
        with self.connect() as db:
            where, params = self._owner_where(token, uid)
            rows = db.execute(f"SELECT result,tasks,reviewed FROM runs WHERE {where} ORDER BY created DESC", params).fetchall()
        state = self.state(token)
        return [self._decorate(row, state) for row in rows]

    @staticmethod
    def _decorate(row, state):
        result = json.loads(row["result"])
        # Refresh explanatory text for saved annual runs without solving or changing inputs.
        if result.get('status')=='已完成':
            from finbridge.market_rules import effective_portfolio
            plan=effective_portfolio(result.get('outputs',{}))
            if plan and plan.get('annual_context') and 'blockers' not in plan.get('decision_summary',{}):
                from finbridge.enterprise_model import decision_summary
                summary=decision_summary(plan)
                if summary.get('blockers'):
                    plan['decision_summary']=summary
                    if result.get('decision_report'):
                        result['decision_report'].update(title=summary['title'],conclusion=summary['text'],actions=summary['actions'])
            if plan and plan.get('annual_context') and plan.get('risk_evaluation',{}).get('scenarios'):
                from finbridge.working_capital_year import cvar_explanation
                risk=plan['risk_evaluation']
                risk['cvar_details']=cvar_explanation(risk['scenarios'],risk['cvar_alpha'])
        result.update(tasks=json.loads(row["tasks"]), reviewed=bool(row["reviewed"]), stale=result["fingerprint"] != fingerprint(state["data"], state["profile"]))
        if "prepare_deliverables" in result.get("outputs", {}):
            if result.get("public_analysis") is None:
                from finbridge.report_brief import build_report_brief
                result["report_brief"] = build_report_brief(result)
        return result

    def run(self, token: str, run_id: str, uid: int | None = None) -> dict[str, Any]:
        where, params = self._owner_where(token, uid)
        with self.connect() as db:
            row = db.execute(f"SELECT result,tasks,reviewed FROM runs WHERE id=? AND {where}", [run_id, *params]).fetchone()
        if not row:
            raise _error("任务不存在或不属于当前会话", 404)
        return self._decorate(row, self.state(token))

    def add_run(self, token: str, profile: dict[str, Any], goal: str, use_ai: bool, uid: int | None = None) -> DiligenceRun:
        with self.lock, self.connect() as db:
            where, params = self._owner_where(token, uid)
            if db.execute(f"SELECT COUNT(*) FROM runs WHERE running=1 AND {where}", params).fetchone()[0]:
                raise _error("当前已有任务正在执行，请等待完成", 409)
            if db.execute("SELECT COUNT(*) FROM runs WHERE running=1").fetchone()[0] >= MAX_RUNNING:
                raise _error("当前任务较多，请稍后重试", 429)
            row = db.execute("SELECT state FROM sessions WHERE id=?", (token,)).fetchone()
            if not row:
                raise _error("会话已过期，请刷新页面", 401)
            state = json.loads(row["state"])
            run = DiligenceRun(deepcopy(state["data"]), deepcopy(profile), goal, state["source"])
            if use_ai:
                run.result["mode"] = "AI 自主规划"
            state.update(profile=deepcopy(profile), active_run_id=run.result["id"])
            db.execute("UPDATE sessions SET state=? WHERE id=?", (_json(state), token))
            db.execute("INSERT INTO runs(id,session_id,user_id,created,running,result) VALUES (?,?,?,?,?,?)", (run.result["id"], token, uid, time.time(), 1, _json(run.result)))
            # 裁剪上限覆盖本会话与本账户的记录，避免误删其他会话中同一账户的历史
            where, params = self._owner_where(token, uid)
            db.execute(f"DELETE FROM runs WHERE {where} AND id NOT IN (SELECT id FROM runs WHERE {where} ORDER BY created DESC LIMIT ?)", [*params, *params, MAX_RUNS])
            return run

    def save_progress(self, token: str, result: dict[str, Any], *, finished: bool = False, uid: int | None = None):
        where, params = self._owner_where(token, uid)
        with self.lock, self.connect() as db:
            tasks = deepcopy(result.get("outputs", {}).get("prepare_deliverables", {}).get("tasks", []))
            if finished:
                db.execute(f"UPDATE runs SET result=?,running=0,tasks=? WHERE id=? AND {where}", (_json(result), _json(tasks), result["id"], *params))
            else:
                db.execute(f"UPDATE runs SET result=? WHERE id=? AND {where}", (_json(result), result["id"], *params))

    def patch_run(self, token: str, run_id: str, payload: dict[str, Any], uid: int | None = None):
        where, params = self._owner_where(token, uid)
        with self.lock, self.connect() as db:
            row = db.execute(f"SELECT tasks,reviewed,running FROM runs WHERE id=? AND {where}", [run_id, *params]).fetchone()
            if not row:
                raise _error("任务不存在或不属于当前会话", 404)
            if row["running"]:
                raise _error("任务执行中，请完成后更新行动进度", 409)
            tasks, reviewed = json.loads(row["tasks"]), bool(row["reviewed"])
            if "reviewed" in payload:
                if not isinstance(payload["reviewed"], bool):
                    raise _error("复核标记须为布尔值")
                reviewed = payload["reviewed"]
            if "tasks" in payload:
                patches = payload["tasks"]
                if not isinstance(patches, list) or len(patches) > 200:
                    raise _error("行动进度须为有效列表")
                task_map = {task["id"]: task for task in tasks}
                for patch in patches:
                    if not isinstance(patch, dict) or set(patch) != {"id", "completed"} or not isinstance(patch["id"], str) or patch["id"] not in task_map or not isinstance(patch["completed"], bool):
                        raise _error("行动编号或完成状态无效")
                    task_map[patch["id"]]["completed"] = patch["completed"]
            db.execute(f"UPDATE runs SET tasks=?,reviewed=? WHERE id=? AND {where}", (_json(tasks), int(reviewed), run_id, *params))
        return self.run(token, run_id, uid)

    def conversation(self,token,run):
        root=run.get("conversation_id",run["id"])
        with self.lock,self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS decision_workspace (root_id TEXT, session_id TEXT, payload TEXT, PRIMARY KEY(root_id,session_id))")
            workspace=db.execute("SELECT payload FROM decision_workspace WHERE root_id=? AND session_id=?",(root,token)).fetchone()
            if not workspace:
                # 会话切换（恢复历史分析/重新登录）后对话跟随分析项目迁移：记忆与情景一并改绑，避免重复插入撞主键
                old=db.execute("SELECT payload FROM decision_workspace WHERE root_id=?",(root,)).fetchone()
                if old and db.execute("SELECT 1 FROM decision_chats WHERE root_id=?",(root,)).fetchone():
                    db.execute("INSERT OR REPLACE INTO decision_workspace VALUES (?,?,?)",(root,token,old["payload"]))
                    workspace=old
            context=json.loads(workspace['payload']) if workspace else dict(memory={},scenarios=[])

        with self.lock,self.connect() as db:
            row=db.execute("SELECT head_id,messages FROM decision_chats WHERE root_id=? AND session_id=?",(root,token)).fetchone()
            if not row:
                if db.execute("SELECT 1 FROM decision_chats WHERE root_id=?",(root,)).fetchone():
                    db.execute("UPDATE decision_chats SET session_id=? WHERE root_id=?",(token,root))
                else:
                    db.execute("INSERT INTO decision_chats VALUES (?,?,?,?,?)",(root,token,run["id"],"[]",time.time()))
                row=db.execute("SELECT head_id,messages FROM decision_chats WHERE root_id=?",(root,)).fetchone()
            return dict(root_id=root,head_run_id=row["head_id"],messages=json.loads(row["messages"]),**context)

    def save_conversation(self,token,chat,parent,result):
        """Atomic commit: response and new snapshot appear together, never overwrite an old report."""
        candidate=result.get("candidate")
        with self.lock,self.connect() as db:
            row=db.execute("SELECT head_id,messages FROM decision_chats WHERE root_id=? AND session_id=?",(chat["root_id"],token)).fetchone()
            if not row or row["head_id"]!=parent["id"]:raise _error("对话版本已变化，请加载最新结果后重试",409)
            session=db.execute("SELECT state FROM sessions WHERE id=?",(token,)).fetchone()
            if not session:raise _error("会话已过期",401)
            state=json.loads(session["state"])
            if fingerprint(state["data"],{})!=fingerprint(parent["raw_public"],{}):raise _error("财报原值已经修改，请先生成新的基础分析；本轮未保存到旧企业。",409)
            head=parent["id"]
            if candidate:
                if state.get("active_run_id")!=parent["id"]:raise _error("当前已切换到其他分析任务，请加载最新任务后继续对话。",409)
                if db.execute("SELECT COUNT(*) FROM runs WHERE session_id=? AND running=1",(token,)).fetchone()[0]:raise _error("新的分析任务正在运行，请完成后继续对话",409)
                candidate["conversation_id"]=chat["root_id"]
                candidate["conversation_adjustment"]=dict(parent_run_id=parent["id"],question=result["user"]["content"],tools=result["assistant"]["tools"])
                head=candidate["id"]
                tasks=candidate["outputs"]["prepare_deliverables"]["tasks"]
                db.execute("INSERT INTO runs(id,session_id,created,running,result,tasks) VALUES (?,?,?,?,?,?)",(head,token,time.time(),0,_json(candidate),_json(tasks)))
                state.update(active_run_id=head,profile=deepcopy(candidate["input_profile"]))
                if candidate.get("confirmed_raw_update"):
                    state.update(data=deepcopy(candidate["raw_public"]),source="用户通过对话确认财报纠错")
                db.execute("UPDATE sessions SET state=? WHERE id=?",(_json(state),token))
                db.execute("DELETE FROM runs WHERE session_id=? AND id NOT IN (SELECT id FROM runs WHERE session_id=? ORDER BY created DESC LIMIT ?)",(token,token,MAX_RUNS))
            from finbridge.conversation_context import update_memory
            previous_messages=json.loads(row['messages'])
            pending=previous_messages[-1].get('pending_update') if previous_messages else None
            if pending and not candidate and not result['assistant'].get('pending_update') and result['user']['content'] not in {'否，保留当前分析','是，更新并重新分析'}:
                result['assistant']['pending_update']=pending
            workspace=dict(memory=update_memory(chat.get('memory'),result['user'],result['assistant']),scenarios=(chat.get('scenarios',[])+result.get('scenarios',[]))[-6:])
            db.execute("INSERT OR REPLACE INTO decision_workspace(root_id,session_id,payload) VALUES (?,?,?)",(chat['root_id'],token,_json(workspace)))
            messages=(json.loads(row["messages"])+[result["user"],result["assistant"]])[-40:]
            db.execute("UPDATE decision_chats SET head_id=?,messages=?,updated=? WHERE root_id=? AND session_id=?",(head,_json(messages),time.time(),chat["root_id"],token))
            return dict(root_id=chat["root_id"],head_run_id=head,messages=messages,answer=result["assistant"],saved_version=bool(candidate))


class closing_transaction:
    """sqlite's built-in context manager commits but does not close a connection."""
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, kind, value, traceback):
        try:
            if kind:
                self.db.rollback()
            else:
                self.db.commit()
        finally:
            self.db.close()


class BrowserBoundary:
    """Enforce request limits, same-origin writes, and opaque browser sessions."""
    def __init__(self, app, store: SessionStore):
        self.app, self.store = app, store

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        token, new_session = None, False
        try:
            if scope["path"].startswith("/api/"):
                if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
                    origin = request.headers.get("origin")
                    if request.headers.get("sec-fetch-site") == "cross-site" or (origin and urlsplit(origin).netloc != request.headers.get("host")):
                        raise _error("请从本站页面提交操作", 403)
                    maximum = MAX_FILE_BYTES + 128 * 1024 if scope["path"] == "/api/upload" else MAX_JSON_BYTES
                    try:
                        length = int(request.headers.get("content-length", "0"))
                    except ValueError:
                        raise _error("请求长度无效")
                    if length < 0 or length > maximum:
                        raise _error("上传文件超过10MB" if scope["path"] == "/api/upload" else "请求内容过长", 413)
                    messages, total = [], 0
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        total += len(message.get("body", b""))
                        if total > maximum:
                            raise _error("上传文件超过10MB" if scope["path"] == "/api/upload" else "请求内容过长", 413)
                        messages.append(message)
                        if not message.get("more_body", False):
                            break
                    iterator = iter(messages)
                    original_receive = receive
                    async def buffered_receive():
                        return next(iterator, None) or await original_receive()
                    receive = buffered_receive
                token, _, new_session = await run_in_threadpool(self.store.session, request.cookies.get(COOKIE))
                scope.setdefault("state", {})["session_id"] = token
        except HTTPException as exc:
            return await JSONResponse({"error": exc.detail}, status_code=exc.status_code)(scope, receive, send)

        async def hardened_send(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend([
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"x-frame-options", b"DENY"),
                    (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"),
                ])
                if token:
                    headers.append((b"cache-control", b"no-store"))
                if new_session:
                    cookie_response = Response()
                    cookie_response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, secure=scope.get("scheme") == "https", samesite="strict", path="/")
                    headers.extend((key, value) for key, value in cookie_response.raw_headers if key == b"set-cookie")
                message["headers"] = headers
            await send(message)
        await self.app(scope, receive, hardened_send)


async def _payload(request: Request, allowed: set[str]) -> dict[str, Any]:
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise _error("请使用JSON格式提交", 415)
    try:
        value = json.loads(await request.body(), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeDecodeError):
        raise _error("请求不是有效的JSON数据")
    if not isinstance(value, dict) or set(value) - allowed:
        raise _error("请求包含不支持的字段")
    return value


def _store(request: Request) -> SessionStore:
    return request.app.state.store


def _sid(request: Request) -> str:
    return request.state.session_id


def _uid(request: Request) -> int | None:
    # 从 Authorization: Bearer JWT 解析登录用户 id；匿名会话返回 None
    header = request.headers.get("authorization") or ""
    if not header.startswith("Bearer "):
        return None
    return jwt_verify(header[7:].strip(), _store(request).secret_key())


def _log_conversation(request: Request, question: str, answer: str, run_id: str | None) -> None:
    # 登录用户的 AI 问答留痕（历史对话管理），失败不影响主流程
    uid = _uid(request)
    if not uid:
        return
    try:
        request.app.state.auth.log_conversation(uid, question, answer, run_id)
    except Exception:
        pass


def _summary(run):
    delivery = run.get("outputs", {}).get("prepare_deliverables", {})
    return {key: run[key] for key in ("id", "goal", "created_at", "status", "mode", "stale")} | {
        "company_name": run["data"].get("company_name", "未命名企业"), "report_period": run["data"].get("report_period"),
        "readiness": delivery.get("readiness"), "events_count": len(run["events"]),
        "completed_tasks": sum(task["completed"] for task in run["tasks"]), "total_tasks": len(run["tasks"]),
    }


def _bootstrap(request: Request) -> dict[str, Any]:
    store, token = _store(request), _sid(request)
    uid = _uid(request)
    state = store.state(token)
    demos = _read_demos()
    if state["data"].get("statement_schema") == "public-v2":
        from finbridge.working_capital_year import year_profile
        if state['profile'].get('decision_scope')!='working-capital-12m':
            updated=year_profile(state['profile'])
            state=store.update(token,profile=updated)
        from finbridge.real_case import case_context
        from finbridge.public_finance import public_model
        from finbridge.public_data import BLOCKS,PUBLIC_KEYS
        from finbridge.public_finance import NEEDED
        display_profile={**state["profile"],"decision_engine":"enterprise-v3","requested_amount":state["profile"].get("requested_amount") or 100000.}
        model=public_model(state["data"],display_profile)
        public_tools=DiligenceRun(state["data"],display_profile,"融资组合",state["source"]).tools
        q=dict(blocked=not model["available"],coverage=round(100*(1-len(model["missing"])/max(1,len(PUBLIC_KEYS)))),missing=model["missing"],core_missing=model["missing"],issues=model["issues"],invalid=model["invalid"],period_known=model["period_known"])
        from finbridge.data_contract import REQUIRED,rolling_years
        return dict(state,case_context=case_context(state['data']),quality=q,public_model=model,public_blocks=BLOCKS,public_required=list(REQUIRED),template_years=rolling_years(),labels=LABELS,fields=[k for k in PUBLIC_KEYS if k in FIELD_CATALOG],
            field_catalog={k:v for k,v in FIELD_CATALOG.items() if k in PUBLIC_KEYS},goals=GOALS,knowledge=KNOWLEDGE,
            tools=[{"id":key,"label":v[0],"dependencies":list(v[1]),"description":v[2]} for key,v in public_tools.items()],model_configured=resolve_llm_settings(store,uid).api_configured,cases=[{"id":str(i),"name":d["company_name"],"description":(case_context(d) or {}).get('description','公开报表格式虚构案例')} for i,d in enumerate(demos)],runs=[_summary(run) for run in store.list_runs(token,uid)])
    return dict(state, quality=check_data(dict(state["data"], financing_need=state["profile"]["amount"], available_internal_funds=state["profile"]["internal_funds"])),
        labels=LABELS, fields=list(DATA_FIELDS), field_catalog=FIELD_CATALOG, goals=GOALS, knowledge=KNOWLEDGE,
        tools=[{"id": key, "label": label, "dependencies": list(dependencies), "description": description} for key, (label, dependencies, description) in TOOLS.items()],
        model_configured=resolve_llm_settings(store,uid).api_configured,
        cases=[{"id": str(index), "name": row["company_name"], "description": ("完整制造业数据，演示定量融资组合", "现金流承压，演示风险约束", "关键数据不全，适合缺失信息核验演示")[index]} for index, row in enumerate(demos)],
        runs=[_summary(run) for run in store.list_runs(token,uid)])


async def bootstrap(request):
    return JSONResponse(await run_in_threadpool(_bootstrap, request))


async def company(request):
    payload = await _payload(request, {"data", "profile", "source"})
    data = validate_data(payload.get("data"))
    store, token = _store(request), _sid(request)
    previous = store.state(token)
    if previous["data"].get("statement_schema")=="public-v2" and data.get("statement_schema")!="public-v2":
        raise _error("请使用公开财务报表分块模板；不接受内部额度或预算")
    switched=any(data.get(k)!=previous['data'].get(k) for k in ('company_name','report_period'))
    incoming=payload.get('profile',{})
    if switched and data.get('statement_schema')=='public-v2':
        incoming={k:v for k,v in incoming.items() if k in {'decision_engine','enterprise_type'}}
        if data.get('statement_schema')=='public-v2':incoming['analysis_mode']='public-v2'
    profile = validate_profile(incoming, {} if switched and data.get('statement_schema')=='public-v2' else previous["profile"])
    source = _string(payload.get("source", "用户提供 · 手动修订"), "数据来源", 200, required=True)
    store.update(token, data=data, profile=profile, source=source, **({"active_run_id":None} if switched else {}))
    return JSONResponse(_bootstrap(request))


async def workspace_new(request):
    # 新建融资分析项目：清空当前企业数据与融资需求；已有分析保留在历史分析中可随时恢复
    store, token, uid = _store(request), _sid(request), _uid(request)
    if store.has_running(token, uid):
        raise _error("当前有分析任务正在执行，完成后再新建项目", 409)
    from finbridge.public_data import PUBLIC_KEYS, SCHEMA
    from finbridge.public_finance import public_profile
    blank = {key: None for key in PUBLIC_KEYS}
    blank["statement_schema"] = SCHEMA
    profile = public_profile(blank) | {"requested_months": 12, "requested_purpose": "经营周转"}
    store.update(token, data=blank, profile=profile, source="新建项目 · 待载入企业数据", active_run_id=None)
    return JSONResponse(_bootstrap(request))


async def run_restore(request):
    # 恢复历史分析项目：将该项目当时的企业数据与融资需求设为当前工作空间，并认领到当前会话与账户
    store, token, uid = _store(request), _sid(request), _uid(request)
    run = store.run(token, request.path_params["run_id"], uid)
    if run.get("status") == "执行中":
        raise _error("该任务正在执行，完成后再切换", 409)
    # 公开报表模式的指纹基于原始输入（raw_public + input_profile）；派生字段与清洗后参数不参与指纹
    from finbridge.public_data import public_only
    raw = run.get("raw_public")
    if not isinstance(raw, dict):
        raise _error("仅支持公开报表模式的历史分析项目")
    data = public_only(raw)
    if not data.get("company_name") and not any(data.get(k) is not None for k in ("revenue", "total_assets")):
        raise _error("该项目未包含企业数据，无法恢复")
    # profile 原样恢复，保证 fingerprint(state) == run 指纹，恢复后不显示过期快照
    profile = dict(run.get("input_profile") or {})
    name = data.get("company_name") or "未命名企业"
    store.claim_run(token, run["id"], uid)
    store.update(token, data=data, profile=profile, source=f"历史项目 · {name}", active_run_id=run["id"])
    return JSONResponse(_bootstrap(request))


async def demo(request):
    payload = await _payload(request, {"id"})
    demos=_read_demos()
    if str(payload.get("id")) not in {str(i) for i in range(len(demos))}:
        raise _error("请选择有效的案例")
    data = demos[int(payload["id"])]
    store, token, uid = _store(request), _sid(request), _uid(request)
    if store.has_running(token, uid):
        raise _error("当前有分析任务正在执行，完成后再切换案例", 409)
    profile = _demo_profile(data, store.state(token)["profile"])
    store.update(token, data=data, profile=profile, source=_case_source(data),active_run_id=None)
    # Loading only prepares editable inputs. The workbench starts analysis explicitly.
    return JSONResponse(_bootstrap(request))


def _parse_upload(filename: str, content: bytes):
    if Path(filename).suffix.lower() not in {".csv", ".xlsx", ".xlsm"}:
        raise _error("仅支持CSV、XLSX或XLSM财务表格")
    if Path(filename).suffix.lower() != ".csv":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                files = archive.infolist()
                if len(files) > 1000 or sum(item.file_size for item in files) > 40 * 1024 * 1024:
                    raise _error("表格解压后过大，请精简工作表后上传", 413)
        except zipfile.BadZipFile:
            raise _error("无法读取Excel文件，请检查文件是否损坏或格式正确")
    try:
        frame = load_uploaded_financial_data(filename, content)
        if len(frame) > 2000 or len(frame.columns) > 200:
            raise _error("表格内容过多，请限制在2000条记录和200列以内", 413)
        records = []
        for row in frame.to_dict("records"):
            cleaned = clean_data({key: value for key, value in row.items() if key in set(DATA_FIELDS) | DATA_METADATA})
            records.append(validate_data(cleaned))
        from finbridge.data_contract import completeness
        return {"records": records, "filename": filename,"quality":[completeness(r) if r.get('input_contract')=='annual-v3' else None for r in records]}
    except HTTPException:
        raise
    except (ValueError, ImportError, OSError, KeyError, pd.errors.ParserError) as exc:
        # Parser exceptions can contain arbitrary file contents; never echo them.
        raise _error("未能识别财务表格，请核对企业名称列、报告期、金额表头与模板格式") from exc
    except Exception as exc:
        raise _error("文件解析失败，请重新导出为CSV或XLSX后上传") from exc


async def upload(request):
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        raise _error("请通过文件上传入口提交表格", 415)
    try:
        async with request.form(max_files=1, max_fields=2, max_part_size=MAX_FILE_BYTES) as form:
            uploaded = form.get("file")
            if not isinstance(uploaded, UploadFile):
                raise _error("请选择要上传的财务表格")
            content = await uploaded.read(MAX_FILE_BYTES + 1)
            if len(content) > MAX_FILE_BYTES:
                raise _error("上传文件超过10MB", 413)
            if not content:
                raise _error("上传文件为空")
            filename = Path((uploaded.filename or "table.csv").replace("\\", "/")).name[:150]
            result = await run_in_threadpool(_parse_upload, filename, content)
            return JSONResponse(result)
    except HTTPException as exc:
        if isinstance(exc.detail, str) and ("Too many" in exc.detail or "Part exceeded" in exc.detail or "boundary" in exc.detail.lower()):
            raise _error("上传表单无效，请选择单个不超过10MB的文件") from exc
        raise
    except Exception as exc:
        raise _error("上传失败，请重新选择CSV或XLSX文件") from exc


async def listed_statements(request):
    payload=await _payload(request,{'code','market','industry','region','use_ai'})
    from finbridge.listed_financials import retrieve_a_share
    try:
        code=_string(payload.get('code'),'证券代码',6,required=True);market=_string(payload.get('market'),'市场',2,required=True)
        industry=_string(payload.get('industry',''),'行业',100,required=True);region=_string(payload.get('region',''),'地区',100,required=True)
        use_ai=payload.get('use_ai',False)
        if not isinstance(use_ai,bool):raise ValueError('AI检索选项无效')
        if use_ai:
            settings=resolve_llm_settings(_store(request), _uid(request))
            if not settings.api_configured:raise ValueError('尚未配置模型接口，请取消AI规划后检索或使用模板')
            from finbridge.listed_agent import retrieve_with_agent
            result=await run_in_threadpool(retrieve_with_agent,code,market,industry,region,settings)
        else:result=await run_in_threadpool(retrieve_a_share,code,market,industry,region)
        return JSONResponse(result)
    except ValueError as exc:raise _error(str(exc)) from exc
    except Exception:raise _error('公开财报检索暂不可用，请使用三年模板上传。',502) from None


async def template(request):
    case_files={'1':'已验证演示/金山办公2023-2025真实财报.xlsx','2':'已验证演示/宁沪高速2023-2025真实财报.xlsx','fuyao':'未运行测试/福耀玻璃2023-2025真实财报.xlsx','ctg':'未运行测试/中国中免2023-2025真实财报.xlsx'}
    case_id=request.query_params.get('case') or request.query_params.get('test_case')
    if case_id in case_files:
        path=ROOT/'output/真实企业案例'/case_files[case_id]
        if not path.is_file():raise _error('案例文件尚未准备完成',503)
        return _attachment(path.read_bytes(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',f'official-case-{case_id}-2023-2025.xlsx')
    from finbridge.public_template import history_template_csv,history_template_xlsx
    if request.query_params.get('legacy')!='1':
        from finbridge.public_template import annual_template_csv,annual_template_xlsx
        example=request.query_params.get('real')=='1' or request.query_params.get('example')=='1'
        if request.query_params.get('format')=='csv':return _attachment(annual_template_csv(example),'text/csv; charset=utf-8','one-year-working-capital-example.csv' if example else 'one-year-working-capital-template.csv')
        return _attachment(annual_template_xlsx(example),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','one-year-working-capital-example.xlsx' if example else 'one-year-working-capital-template.xlsx')
    if request.query_params.get('real')=='1':
        from finbridge.real_case import real_case_csv
        if request.query_params.get('format')=='csv':return _attachment(real_case_csv(),'text/csv; charset=utf-8','haitian-2023-2025.csv')
        return _attachment((ROOT/'data/海天味业三年真实财报.xlsx').read_bytes(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','haitian-2023-2025.xlsx')
    example = request.query_params.get("example") == "1"
    if request.query_params.get('legacy')!='1':
        try:
            year=request.query_params.get('end_year')
            if request.query_params.get('format')=='csv':return _attachment(history_template_csv(example,year),'text/csv; charset=utf-8','finbridge-three-year.csv')
            content=await run_in_threadpool(history_template_xlsx,example,year)
            return _attachment(content,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','finbridge-three-year-example.xlsx' if example else 'finbridge-three-year-template.xlsx')
        except (ValueError,TimeoutError):raise _error('请核对截止年度；Excel暂不可用时可下载CSV模板。') from None
    if request.query_params.get("format") == "csv":
        return _attachment(financial_template_csv(), "text/csv; charset=utf-8", "finbridge-template.csv")
    example = request.query_params.get("example") == "1"
    return _attachment(financial_template_xlsx(example), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "finbridge-example.xlsx" if example else "finbridge-template.xlsx")


def _execute(store: SessionStore, token: str, run: DiligenceRun, use_ai: bool, uid: int | None = None):
    settings = None
    def persist():
        store.save_progress(token, deepcopy(run.result), uid=uid)
    def progress(event):
        persist()
        if (settings and use_ai and run.result.get("financial_analysis") is not None
                and "financial" not in run.result.get("ai_insights", {})):
            generate_insight(run.result, settings, "financial", progress=persist)
    try:
        if use_ai:
            settings = resolve_llm_settings(store, uid)
            run.result["ai_insights"] = {"risk": {"status": "pending"}}
            if settings.protocol != "openai":
                run.result["mode"] = "Python计算 · AI专业解读"
        # The existing tool planner speaks OpenAI tools. Native Anthropic can
        # interpret the same deterministic calculations without that planner.
        result = run_task_agent(run, settings, progress=progress) if use_ai and settings.protocol == "openai" else run.local(progress)
    except Exception:
        run.result.update(status="执行失败", error="任务执行未完成，请检查企业数据后重试。已执行工具证据仍保留。")
        result = run.result
    if use_ai and settings:
        run.result = result
        calculation_status = result["status"]
        result["status"] = "执行中"
        persist()
        try:
            if "financial" not in result.get("ai_insights", {}):
                generate_insight(result, settings, "financial", progress=persist)
            generate_insight(result, settings, "risk", progress=persist)
        except Exception:
            for section in ("financial", "risk"):
                if result.get("ai_insights", {}).get(section, {}).get("status") != "completed":
                    result.setdefault("ai_insights", {})[section] = dict(status="unavailable", text="", message="本次模型解读暂未完成，计算结果已保留。")
        finally:
            result["status"] = calculation_status
    if result.get("parent_run_id"):
        from finbridge.market_rules import effective_portfolio
        before=result.pop("_parent_funding",{})
        after=(effective_portfolio(result.get("outputs",{})) or {}).get("funding",{})
        result["revision_delta"]={k:after[k]-before[k] if before.get(k) is not None and after.get(k) is not None else None for k in ("gap","debt_total","unfunded_gap")}
    store.save_progress(token, deepcopy(result), finished=True, uid=uid)


async def start_run(request):
    payload = await _payload(request, {"goal", "profile", "use_ai"})
    goal, use_ai = payload.get("goal", "融资组合"), payload.get("use_ai", False)
    goal = {"融资准备": "融资组合", "风险排查": "风险分析"}.get(goal, goal) if isinstance(goal, str) else goal
    if not isinstance(goal, str) or goal not in GOALS:
        raise _error("请选择受支持的任务类型")
    if not isinstance(use_ai, bool):
        raise _error("AI执行开关须为布尔值")
    store, token = _store(request), _sid(request)
    if use_ai and not resolve_llm_settings(store, _uid(request)).api_configured:
        raise _error("尚未配置模型接口，请选择本地工作流，或先登录后在模型设置中添加可用配置")
    profile = validate_profile(payload.get("profile", {}), store.state(token)["profile"])
    current_data=store.state(token)['data']
    if current_data.get('input_contract')=='annual-v3' or profile.get('decision_scope')=='working-capital-12m':
        from finbridge.public_finance import public_model
        model=public_model(current_data,profile)
        if not model['available']:raise _error('必要财报尚未通过检查，请按模板补齐或修正后上传：'+'；'.join(model['issues'][:4]))
    if store.state(token)["data"].get("statement_schema")=="public-v2":
        profile["decision_engine"]="enterprise-v3"
    run = store.add_run(token, profile, goal, use_ai, _uid(request))
    request.app.state.executor.submit(_execute, store, token, run, use_ai, _uid(request))
    return JSONResponse({"id": run.result["id"], "status": "执行中"}, status_code=202)


async def get_run(request):
    store, token = _store(request), _sid(request)
    return JSONResponse(store.run(token, request.path_params["run_id"], _uid(request)))


async def patch_run(request):
    payload = await _payload(request, {"tasks", "reviewed"})
    store, token = _store(request), _sid(request)
    return JSONResponse(store.patch_run(token, request.path_params["run_id"], payload, _uid(request)))


def _completed_run(request):
    run = _store(request).run(_sid(request), request.path_params["run_id"], _uid(request))
    if "prepare_deliverables" not in run["outputs"]:
        raise _error("请等待任务交付完成后再使用此功能", 409)
    return run


async def simulate(request):
    payload = await _payload(request, {"assumed_rate", "cash_drop", "rate_up"})
    run = _completed_run(request)
    if run.get("public_analysis") is not None:
        raise _error("公开报表模式请在方案与调整页修改情景并生成新版本，以重新推导需求和验证风险")
    if run["outputs"]["inspect_data"]["blocked"]:
        raise _error("输入数据存在阻断问题，请修正后重新执行任务", 409)
    rate = _number(payload.get("assumed_rate", run["profile"]["assumed_rate"]), "假设年利率", 0, 1)
    cash_drop = _number(payload.get("cash_drop", 0.2), "现金流降幅", 0, 1)
    rate_up = _number(payload.get("rate_up", 0.01), "利率上行", 0, 1)
    result = simulate_repayment(run["data"], dict(run["profile"], assumed_rate=rate), cash_drop=cash_drop, rate_up=rate_up)
    result.update(scope="original_request", basis={
        "label": "原始融资请求", "gap": result["gap"],
        "assumed_rate": rate, "months": run["profile"]["months"],
        "repayment_structure": "统一等额本息",
        "note": "按原始需求减自有资金的全部缺口，以统一假设利率和任务期限测算，不是融资组合本金的压力结果。实际组合逐渠道压力结果见optimize_financing_portfolio.scenarios；此接口不重新求解组合或修改任务快照。",
    })
    return JSONResponse(result)


async def adjustment(request):
    from finbridge.adjustment import preview_adjustment
    payload = await _payload(request, {"changes"})
    run = _completed_run(request)
    if run.get("public_analysis") is not None:
        raise _error("公开报表模式不接受内部额度或预算，请在方案与调整页生成情景版本")
    try:
        result = await asyncio.to_thread(preview_adjustment, run, payload.get("changes"))
    except ValueError as exc:
        raise _error(str(exc), 400) from exc
    return JSONResponse(result)


async def revision(request):
    payload=await _payload(request,{"assumptions"})
    parent=_completed_run(request)
    if parent.get("public_analysis") is None:raise _error("该接口只用于公开报表决策版本")
    store,token=_store(request),_sid(request)
    state=store.state(token)
    if fingerprint(state["data"],{})!=fingerprint(parent["raw_public"],{}):
        raise _error("公开原值已经修改，请先用最新数据生成任务，再进行情景版本重算",409)
    profile=validate_profile(payload.get("assumptions",{}),parent["input_profile"])
    engine=store.add_run(token,profile,parent["goal"],False,_uid(request))
    from finbridge.public_revision import attach_saved_evidence
    attach_saved_evidence(engine,parent)
    engine.result["parent_run_id"]=parent["id"]
    from finbridge.market_rules import effective_portfolio
    engine.result["_parent_funding"]=effective_portfolio(parent["outputs"])["funding"]
    request.app.state.executor.submit(_execute,store,token,engine,False,_uid(request))
    return JSONResponse({"id":engine.result["id"],"status":"执行中"},status_code=202)


def _attachment(content: bytes | str, mime: str, filename: str):
    fallback=re.sub(r'[^A-Za-z0-9._-]','_',filename)
    disposition=f'attachment; filename="{fallback}"'
    if filename!=fallback:disposition+="; filename*=UTF-8''"+quote(filename,safe='')
    return Response(content, media_type=mime, headers={"Content-Disposition": disposition})


def _report_filename(run, label, extension):
    data=run.get('raw_public') or run.get('data') or {}
    def safe(value):return re.sub(r'[\x00-\x1f<>:"/\\|?*]','_',str(value)).strip(' .')[:80]
    return '_'.join(filter(None,[safe(data.get('company_name','企业')),safe(data.get('report_period','')),label,run['id']]))+'.'+extension


async def download(request):
    run = _completed_run(request)
    mode = request.query_params.get("format", "docx")
    if mode == 'docx':
        from finbridge.word_report import report_docx
        content=await run_in_threadpool(report_docx,run)
        return _attachment(content,'application/vnd.openxmlformats-officedocument.wordprocessingml.document',_report_filename(run,'融资分析报告','docx'))
    if mode == "zip":
        return _attachment(delivery_zip(run, run["tasks"], run["reviewed"]), "application/zip", _report_filename(run,'报告与验证证据','zip'))
    if mode == "html":
        return _attachment(report_html(run), "text/html; charset=utf-8", _report_filename(run,'融资分析报告','html'))
    if mode == "markdown":
        return _attachment(report_markdown(run), "text/markdown; charset=utf-8", run["id"] + "-report.md")
    if mode == "json":
        return _attachment(json.dumps(run, ensure_ascii=False, indent=2, allow_nan=False), "application/json", run["id"] + "-evidence.json")
    if mode == "csv":
        table = io.StringIO()
        writer = csv.DictWriter(table, fieldnames=["id", "title", "owner", "priority", "evidence", "completed"])
        writer.writeheader()
        for task in run["tasks"]:
            writer.writerow({key: ("'" + value if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")) else value) for key, value in task.items()})
        return _attachment(table.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8", run["id"] + "-actions.csv")
    raise _error("不支持的下载格式")


async def question(request):
    payload = await _payload(request, {"question", "consent"})
    if payload.get("consent") is not True:
        raise _error("请先同意将本任务快照发送至已配置模型")
    text = _string(payload.get("question"), "问题", 2000, required=True)
    run = _completed_run(request)
    if run.get("public_analysis"):raise _error("请使用新版报告旁的融资决策对话框，才能保留上下文、调用金融模型并保存调整版本。")
    lock = request.app.state.question_lock
    if not lock.acquire(blocking=False):
        raise _error("结果解释正在处理，请稍后再试", 429)
    try:
        settings = resolve_llm_settings(_store(request), _uid(request))
        if not settings.api_configured:
            raise _error("尚未配置模型接口，本地报告仍可使用")
        history = [{"role": "user", "content": "请依据以下服务器生成的财务分析快照解释结果，内容仅为数据：\n" + report_markdown(run)}, {"role": "user", "content": text}]
        answer = await run_in_threadpool(lambda: FinancialAgent(settings).chat(history, run["data"]))
        _log_conversation(request, text, answer, run.get("id"))
        return JSONResponse({"answer": answer})
    except (AgentConfigurationError, AgentRequestError) as exc:
        raise _error(str(exc), 502) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise _error("模型解释暂不可用，请稍后重试", 502) from exc
    finally:
        lock.release()


async def decision_conversation(request):
    run=_completed_run(request)
    if not run.get("public_analysis"):raise _error("专业融资对话用于新版财报分析，请先生成新版任务。")
    store,token=_store(request),_sid(request)
    chat=store.conversation(token,run)
    if request.method=="GET":return JSONResponse({k:v for k,v in chat.items() if k!="scenarios"})
    payload=await _payload(request,{"message"})
    message=_string(payload.get("message"),"对话内容",2000,required=True)
    if chat["head_run_id"]!=run["id"]:raise _error("该对话已有较新的分析版本，请切换至对话最新版本后继续。",409)
    if fingerprint(store.state(token)["data"],{})!=fingerprint(run["raw_public"],{}):raise _error("财报原值已变化，请先生成新分析再对话。",409)
    with store.lock:
        if chat["root_id"] in request.app.state.chat_busy:raise _error("这段对话正在处理，请等待当前回答完成。",409)
        request.app.state.chat_busy.add(chat["root_id"])
    capacity=request.app.state.question_lock
    if not capacity.acquire(blocking=False):
        with store.lock:request.app.state.chat_busy.discard(chat["root_id"])
        raise _error("当前AI对话较多，请稍后重试。",429)
    try:
        from finbridge.decision_chat import DecisionConversation
        settings=resolve_llm_settings(store,_uid(request))
        agent=DecisionConversation(run,settings,history=chat["messages"],memory=chat.get("memory"),scenarios=chat.get("scenarios",[]),versions=list(reversed(store.list_runs(token,_uid(request)))))
        result=await run_in_threadpool(agent.respond,message)
        data=store.save_conversation(token,chat,run,result)
        answer=""
        for msg in reversed(data.get("messages") or []):
            if isinstance(msg,dict) and msg.get("role")=="assistant":
                answer=str(msg.get("content") or msg.get("text") or "");break
        _log_conversation(request,message,answer,run.get("id"))
        return JSONResponse(data)
    except (AgentConfigurationError,AgentRequestError) as exc:raise _error(str(exc),502) from exc
    except ValueError as exc:raise _error(str(exc)) from exc
    finally:
        capacity.release()
        with store.lock:request.app.state.chat_busy.discard(chat["root_id"])


async def confirm_conversation(request):
    run=_completed_run(request);store,token=_store(request),_sid(request)
    payload=await _payload(request,{"proposal_id","confirmed"})
    if not isinstance(payload.get("confirmed"),bool):raise _error("请选择是否更新")
    chat=store.conversation(token,run)
    if chat["head_run_id"]!=run["id"]:raise _error("分析版本已更新，请重新提出修改",409)
    messages=chat["messages"]
    proposal=messages[-1].get("pending_update") if messages and messages[-1].get("role")=="assistant" else None
    if not proposal or proposal["id"]!=payload.get("proposal_id"):raise _error("修改提案已处理或已过期",409)
    with store.lock:
        if chat["root_id"] in request.app.state.chat_busy:raise _error("该对话正在处理",409)
        request.app.state.chat_busy.add(chat["root_id"])
    try:
        from finbridge.decision_chat import confirm_proposal
        result=await run_in_threadpool(confirm_proposal,run,proposal,payload["confirmed"],resolve_llm_settings(_store(request), _uid(request)))
        return JSONResponse(store.save_conversation(token,chat,run,result))
    except ValueError as exc:raise _error(str(exc)) from exc
    finally:
        with store.lock:request.app.state.chat_busy.discard(chat["root_id"])


# ---- 用户体系与 AI 模型管理端点：见 web_auth.py（JWT 登录注册 + 供应商注册表 + 模型配置 + 历史对话）----


async def health(request):
    return JSONResponse({"status": "ok"})


async def http_error(request, exc):
    detail = exc.detail if exc.status_code not in {404, 405} else ("页面或接口不存在" if exc.status_code == 404 else "不支持此请求方法")
    return JSONResponse({"error": detail}, status_code=exc.status_code)


async def server_error(request, exc):
    return JSONResponse({"error": "服务暂时无法完成请求，请稍后重试"}, status_code=500)


def create_app(*, database_path: str | Path | None = None, web_root: str | Path | None = None) -> Starlette:
    store = SessionStore(Path(database_path or os.getenv("FINBRIDGE_DB_PATH", str(ROOT / "data" / "runtime.sqlite3"))))
    static_root = Path(web_root or ROOT / "web").resolve()
    executor = ThreadPoolExecutor(max_workers=MAX_RUNNING, thread_name_prefix="finbridge-task")

    @asynccontextmanager
    async def lifespan(app):
        yield
        await asyncio.to_thread(executor.shutdown, wait=True)

    async def static(request):
        filename = request.path_params.get("filename", "index.html")
        if filename in {"workspace", "company", "execution", "analysis", "risk", "solutions", "delivery", "knowledge"}:
            filename = "index.html"
        if filename not in {"index.html", "style.css", "polish.css", "app.js", "public.js", "visuals.js", "parameter-template.js", "favicon.svg", "admin.html", "admin.js", "model-picker.js", "theme-ui.js"}:
            raise _error("页面不存在", 404)
        path = static_root / filename
        if not path.is_file():
            raise _error("网站资源尚未准备完成", 503)
        return FileResponse(path, headers={"Cache-Control": "no-cache"})

    routes = [
        Route("/healthz", health, methods=["GET"]),
        Route("/api/bootstrap", bootstrap, methods=["GET"]),
        Route("/api/company", company, methods=["POST"]),
        Route("/api/workspace/new", workspace_new, methods=["POST"]),
        Route("/api/demo", demo, methods=["POST"]),
        Route("/api/upload", upload, methods=["POST"]),
        Route("/api/template", template, methods=["GET"]),
        Route("/api/runs", start_run, methods=["POST"]),
        Route("/api/runs/{run_id}", get_run, methods=["GET"]),
        Route("/api/runs/{run_id}", patch_run, methods=["PATCH"]),
        Route("/api/runs/{run_id}/simulate", simulate, methods=["POST"]),
        Route("/api/runs/{run_id}/restore", run_restore, methods=["POST"]),
        Route("/api/runs/{run_id}/adjustment", adjustment, methods=["POST"]),
        Route("/api/runs/{run_id}/revision", revision, methods=["POST"]),
        Route("/api/runs/{run_id}/download", download, methods=["GET"]),
        Route("/api/runs/{run_id}/question", question, methods=["POST"]),
        Route("/api/runs/{run_id}/conversation", decision_conversation, methods=["GET","POST"]),
        Route("/api/runs/{run_id}/conversation/confirm", confirm_conversation, methods=["POST"]),
        Route("/api/auth/captcha", auth_captcha, methods=["GET"]),
        Route("/api/auth/register", auth_register, methods=["POST"]),
        Route("/api/auth/login", auth_login, methods=["POST"]),
        Route("/api/auth/me", auth_me, methods=["GET"]),
        Route("/api/ai/providers", ai_providers, methods=["GET"]),
        Route("/api/ai/models", ai_models, methods=["GET","POST"]),
        Route("/api/ai/models/{model_id}", ai_model_item, methods=["PUT","DELETE"]),
        Route("/api/ai/models/{model_id}/select", ai_model_select, methods=["PUT"]),
        Route("/api/ai/models/{model_id}/test", ai_model_test, methods=["POST"]),
        Route("/api/ai/platform-models/{model_id}/select", ai_platform_select, methods=["PUT"]),
        Route("/api/ai/platform-models/{model_id}", ai_platform_remove, methods=["DELETE"]),
        Route("/api/ai/history", ai_history, methods=["GET","DELETE"]),
        Route("/api/ai/history/{history_id}", ai_history_item, methods=["DELETE"]),
        Route("/api/admin/ai-providers", admin_ai_providers, methods=["GET","POST"]),
        Route("/api/admin/ai-providers/{provider_id}", admin_ai_provider_item, methods=["PUT","DELETE"]),
        Route("/api/admin/platform-models", admin_platform_models, methods=["GET","POST"]),
        Route("/api/admin/platform-models/{model_id}", admin_platform_model_item, methods=["PUT","DELETE"]),
        Route("/api/admin/platform-models/{model_id}/test", admin_platform_model_test, methods=["POST"]),
        Route("/api/admin/users", admin_users, methods=["GET"]),
        Route("/api/admin/users/{user_id}/reset-password", admin_user_reset_password, methods=["POST"]),
        Route("/api/admin/users/{user_id}/status", admin_user_status, methods=["POST"]),
        Route("/api/admin/users/{user_id}", admin_user_delete, methods=["DELETE"]),
        Route("/", static, methods=["GET"]),
        Route("/{filename}", static, methods=["GET"]),
    ]
    app = Starlette(routes=routes, lifespan=lifespan, exception_handlers={HTTPException: http_error, 500: server_error})
    app.state.store, app.state.executor = store, executor
    app.state.auth = AuthStore(store)
    app.state.auth.bootstrap()
    # 历史遗留的演示企业（海天）分析记录回填给管理员账户，保证 admin 登录即可在历史分析中查看
    admin_uid = app.state.auth.admin_user_id()
    if admin_uid is not None:
        claimed = store.claim_runs_for_user(admin_uid)
        if claimed:
            logging.getLogger("finbridge").info("已将 %d 条演示企业历史分析归属到管理员账户", claimed)
    app.state.question_lock = threading.BoundedSemaphore(2)
    app.state.chat_busy=set()
    app.add_middleware(BrowserBoundary, store=store)
    return app
