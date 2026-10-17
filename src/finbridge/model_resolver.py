"""按「用户自配 → 平台托管 → 环境变量」优先级解析生效的 LLM 配置。

只改变 OpenAI client 的 base_url/api_key/model 来源，AI 模型负责理解、
调度、解释，Python 负责计算与验证的既有流程不变。
模型配置来自 web_auth 的用户体系：登录用户可多套自配并切换「使用中」，
或一键选用平台托管模型；匿名会话回落平台托管与环境变量。
"""
from __future__ import annotations

from finbridge.config import Settings, load_settings


def resolve_llm_settings(store, user_id: int | None) -> Settings:
    """返回当前登录用户（或匿名降级）生效的 Settings；api_key 为解密后的明文。

    优先级：用户选中的自配模型 → 用户选中的平台托管模型 → 任一启用的平台托管模型 → 环境变量。
    """
    with store.connect() as db:
        selected = None
        if user_id is not None:
            selected = db.execute(
                "SELECT platform_id, base_url, model_id, api_key_enc FROM ai_model "
                "WHERE user_id=? AND is_selected=1 ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
        if selected and selected["platform_id"]:
            selected = db.execute(
                "SELECT base_url, model_id, api_key_enc FROM ai_platform_model WHERE id=? AND enabled=1",
                (selected["platform_id"],)).fetchone()
        elif selected is None:
            selected = db.execute(
                "SELECT base_url, model_id, api_key_enc FROM ai_platform_model WHERE enabled=1 "
                "ORDER BY sort_order, id LIMIT 1").fetchone()
    if selected and selected["api_key_enc"] and selected["base_url"] and selected["model_id"]:
        key = store.secret_box().decrypt(selected["api_key_enc"])
        return Settings(api_key=key, base_url=selected["base_url"], model=selected["model_id"])
    return load_settings()
