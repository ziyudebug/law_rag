"""
Qwen 大模型结构化抽取：基于 OpenAI 兼容接口流式生成并解析为 JSON。

按加权多模型令牌轮换选用模型与 API Key，用于从监测报告文本中抽取结构化信息。

@author: ziyu
@date: 2026-07-17
"""
import json
import re
from typing import Any, Iterator
from sqlalchemy.orm import Session

from openai import OpenAI
from app.core.database import db
import random
from typing import List
from app.core.token import get_weighted_model_token
from app.core.config import settings

# 启动时按权重选定默认模型与 API Key
DEFAULT_MODEL, DEFAULT_API_KEY = get_weighted_model_token()



def _build_client() -> OpenAI:
    """构造 OpenAI 兼容客户端（指向 Qwen base_url）。"""
    return OpenAI(
        api_key=DEFAULT_API_KEY,
        base_url=settings.qwen_base_url,
    )


def build_prompt(document_text: str,prompt: str = None) -> str:
    """拼装抽取提示词：把文档内容与抽取要求组装成 user 消息。"""
    return f"""以下是我提供的监测报告文本，请你严格基于这些内容抽取信息，不要编造。

==================== 文档内容开始 ====================
{document_text}
==================== 文档内容结束 ====================

抽取要求：
{prompt}
"""


def _extract_json_text(content: str) -> str:
    """从模型返回文本中提取合法 JSON 片段（优先代码块，其次首尾花括号）。"""
    candidates = [content.strip()]
    fenced_blocks = re.findall(r"```(?:json)?\s*(.*?)```", content, flags=re.DOTALL | re.IGNORECASE)
    candidates.extend(block.strip() for block in fenced_blocks if block.strip())

    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(content[start : end + 1].strip())

    for candidate in candidates:
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue

    raise ValueError("Qwen 返回内容不是合法 JSON。")


def parse_structured_json_text(content: str) -> dict[str, Any]:
    """把模型返回文本解析为 dict，无法解析抛 ValueError。"""
    return json.loads(_extract_json_text(content))


def _normalize_content_piece(content: Any) -> str:
    """把流式增量内容（str/对象列表）规整为字符串。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = getattr(item, "text", None)
            if text:
                parts.append(text)
                continue
            if isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
        return "".join(parts)
    return ""

def get_db_session():
    """依赖注入：获取数据库会话。"""
    with db.SessionLocal() as session:
        try:
            yield session
        finally:
            session.close()
def stream_structured_json_text(document_text: str,prompt: str = None,session: Session = get_db_session()) -> Iterator[str]:
    """流式调用 Qwen 抽取，逐块 yield 增量文本。"""
    cleaned_text = document_text.strip()
    if not cleaned_text:
        raise ValueError("传给 Qwen 的文档内容为空。")
    model_name = settings.qwen_model or DEFAULT_MODEL
    print(f"Qwen 模型: {model_name}")
    completion = _build_client().chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": build_prompt(cleaned_text,prompt)}],
        temperature=settings.qwen_temperature,
        stream=True,
    )

    for chunk in completion:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        content = _normalize_content_piece(getattr(delta, "content", None))
        if content:
            yield content


def generate_structured_json(document_text: str,prompt: str,session: Session = get_db_session()) -> dict[str, Any]:
    """同步抽取：收集全部流式输出后解析为 JSON dict。"""
    collected = "".join(stream_structured_json_text(document_text,prompt=prompt,session=session))
    return parse_structured_json_text(collected)
