"""
检索配置数据模型：定义检索模式、混合策略及 RetrievalConfig 不可变配置对象。

承载按 (tenant_id, kb_id) 维度持久化的检索参数，并对外部传入 payload 做校验与归一化。

@author: ziyu
@date: 2026-07-16
"""
from dataclasses import asdict, dataclass
from typing import Any

from app.core.config import settings


# 检索模式常量
RETRIEVAL_MODE_VECTOR = "VECTOR"
RETRIEVAL_MODE_FULLTEXT = "FULLTEXT"
RETRIEVAL_MODE_HYBRID = "HYBRID"
# 混合检索策略常量
HYBRID_STRATEGY_RERANK = "RERANK"
HYBRID_STRATEGY_WEIGHT = "WEIGHT"

RETRIEVAL_MODES = {RETRIEVAL_MODE_VECTOR, RETRIEVAL_MODE_FULLTEXT, RETRIEVAL_MODE_HYBRID}
HYBRID_STRATEGIES = {HYBRID_STRATEGY_RERANK, HYBRID_STRATEGY_WEIGHT}


def _configured_choice(value: Any, choices: set[str], default: str) -> str:
    """从配置值中选取合法选项，非法或为空时回退默认值。"""
    text = str(value or default).strip().upper()
    return text if text in choices else default


# 全局默认配置（取自 settings，启动时计算一次）
DEFAULT_RETRIEVAL_MODE = _configured_choice(
    settings.retrieval_default_mode,
    RETRIEVAL_MODES,
    RETRIEVAL_MODE_HYBRID,
)
DEFAULT_HYBRID_STRATEGY = _configured_choice(
    settings.retrieval_default_hybrid_strategy,
    HYBRID_STRATEGIES,
    HYBRID_STRATEGY_RERANK,
)
DEFAULT_RERANK_MODEL = settings.default_rerank_model
DEFAULT_USE_RERANK = settings.retrieval_default_use_rerank
DEFAULT_SEMANTIC_WEIGHT = max(0.0, settings.retrieval_default_semantic_weight)
DEFAULT_KEYWORD_WEIGHT = max(0.0, settings.retrieval_default_keyword_weight)
DEFAULT_TOP_K = max(1, settings.retrieval_default_top_k)
DEFAULT_ENABLE_SOURCE = settings.retrieval_default_enable_source
DEFAULT_SCORE_THRESHOLD = max(0.0, settings.retrieval_default_score_threshold)

# 兼容检索服务中已有命名。
SEARCH_TYPE_VECTOR = RETRIEVAL_MODE_VECTOR
SEARCH_TYPE_FULLTEXT = RETRIEVAL_MODE_FULLTEXT
SEARCH_TYPE_HYBRID = RETRIEVAL_MODE_HYBRID


@dataclass(frozen=True)
class RetrievalConfig:
    """检索配置：按租户+知识库维度保存的检索参数（冻结数据类）。"""

    tenant_id: str
    kb_id: str
    retrieval_mode: str = DEFAULT_RETRIEVAL_MODE
    use_rerank: bool = DEFAULT_USE_RERANK
    rerank_model: str = DEFAULT_RERANK_MODEL
    hybrid_strategy: str = DEFAULT_HYBRID_STRATEGY
    semantic_weight: float = DEFAULT_SEMANTIC_WEIGHT
    keyword_weight: float = DEFAULT_KEYWORD_WEIGHT
    top_k: int = DEFAULT_TOP_K
    enable_source: bool = DEFAULT_ENABLE_SOURCE
    score_threshold: float = DEFAULT_SCORE_THRESHOLD

    @classmethod
    def default(cls, tenant_id: str, kb_id: str) -> "RetrievalConfig":
        """构造指定租户+知识库的默认配置（已归一化）。"""
        return cls(tenant_id=str(tenant_id), kb_id=str(kb_id)).normalized()

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "RetrievalConfig":
        """从外部 payload 构造配置：校验必填项、枚举值、数值范围，再归一化。"""
        tenant_id = _required_str(payload, "tenant_id")
        kb_id = _required_str(payload, "kb_id")
        retrieval_mode = _choice(
            payload.get("retrieval_mode"),
            RETRIEVAL_MODES,
            DEFAULT_RETRIEVAL_MODE,
        )
        hybrid_strategy = _choice(
            payload.get("hybrid_strategy"),
            HYBRID_STRATEGIES,
            DEFAULT_HYBRID_STRATEGY,
        )

        return cls(
            tenant_id=tenant_id,
            kb_id=kb_id,
            retrieval_mode=retrieval_mode,
            use_rerank=_bool(payload.get("use_rerank"), DEFAULT_USE_RERANK),
            rerank_model=_str(payload.get("rerank_model"), DEFAULT_RERANK_MODEL),
            hybrid_strategy=hybrid_strategy,
            semantic_weight=_weight(payload.get("semantic_weight"), DEFAULT_SEMANTIC_WEIGHT),
            keyword_weight=_weight(payload.get("keyword_weight"), DEFAULT_KEYWORD_WEIGHT),
            top_k=_positive_int(payload.get("top_k"), DEFAULT_TOP_K),
            enable_source=_bool(payload.get("enable_source"), DEFAULT_ENABLE_SOURCE),
            score_threshold=_score(payload.get("score_threshold"), DEFAULT_SCORE_THRESHOLD),
        ).normalized()

    def normalized(self) -> "RetrievalConfig":
        """归一化配置：按混合策略强制设定 use_rerank，并把权重和归一为 1。"""
        semantic = self.semantic_weight
        keyword = self.keyword_weight
        use_rerank = self.use_rerank
        if self.retrieval_mode == RETRIEVAL_MODE_HYBRID and self.hybrid_strategy == HYBRID_STRATEGY_WEIGHT:
            use_rerank = False
            total = semantic + keyword
            if total <= 0:
                semantic, keyword = DEFAULT_SEMANTIC_WEIGHT, DEFAULT_KEYWORD_WEIGHT
            elif abs(total - 1.0) > 0.0001:
                semantic = semantic / total
                keyword = keyword / total
        elif self.retrieval_mode == RETRIEVAL_MODE_HYBRID:
            use_rerank = True

        return RetrievalConfig(
            tenant_id=self.tenant_id,
            kb_id=self.kb_id,
            retrieval_mode=self.retrieval_mode,
            use_rerank=use_rerank,
            rerank_model=self.rerank_model,
            hybrid_strategy=self.hybrid_strategy,
            semantic_weight=round(semantic, 4),
            keyword_weight=round(keyword, 4),
            top_k=self.top_k,
            enable_source=self.enable_source,
            score_threshold=self.score_threshold,
        )

    def to_dict(self) -> dict[str, Any]:
        """序列化为字典，用于持久化或接口返回。"""
        return asdict(self)


def _required_str(payload: dict[str, Any], key: str) -> str:
    """取必填字符串字段，为空抛 ValueError。"""
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"缺少 {key}。")
    return value


def _str(value: Any, default: str) -> str:
    """取可选字符串，为空用默认值。"""
    text = str(value or "").strip()
    return text or default


def _choice(value: Any, choices: set[str], default: str) -> str:
    """取枚举值，不在候选集则用默认值。"""
    text = str(value or default).strip().upper()
    return text if text in choices else default


def _bool(value: Any, default: bool) -> bool:
    """宽容地把多种字面量解析为布尔，无法识别则用默认值。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on", "启用"}


def _positive_int(value: Any, default: int) -> int:
    """取正整数，非法或小于 1 则用默认值。"""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _score(value: Any, default: float) -> float:
    """取分数阈值，非负，非法用默认值。"""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, parsed)


def _weight(value: Any, default: float) -> float:
    """取权重值，非负，非法用默认值。"""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, parsed)
