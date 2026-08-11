"""
多模型加权 token 选择模块。

当配置了多个通义千问模型 + token（MODEL_CONFIG_JSON）时，按权重随机轮换，
分摊单账号配额；未配置时回退到单模型 + 单 token。

@author: ziyu
@date: 2026-07-16
"""
from app.core.config import settings
import json
import random
from typing import Tuple
import logging



def get_weighted_model_token() -> Tuple[str, str]:
    """按权重随机选择一个通义千问模型及其 token，返回 (model, token)。

    优先读取 MODEL_CONFIG_JSON 多模型加权配置；为空时回退到 QWEN_MODEL + DASHSCOPE_API_KEY。
    两者都缺失则抛出 ValueError。
    """
    config_str = settings.MODEL_CONFIG_JSON

    if not config_str or config_str.strip() == "[]":
        if settings.qwen_model and settings.dashscope_api_key:
            return settings.qwen_model, settings.dashscope_api_key
        raise ValueError("请配置 MODEL_CONFIG_JSON，或同时配置 QWEN_MODEL 与 DASHSCOPE_API_KEY")

    config_list = json.loads(config_str)
    if not config_list:
        raise ValueError("MODEL_CONFIG_JSON 不能为空数组")

    # 构造加权池
    population = []
    weights = []

    for item in config_list:
        population.append((item["model"], item["token"]))
        weights.append(item.get("weight", 1))

    # 加权随机选择
    model, token = random.choices(population, weights=weights, k=1)[0]
    logging.info(f"选择模型: {model}")
    return model, token
