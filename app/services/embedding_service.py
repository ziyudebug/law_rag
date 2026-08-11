"""
DashScope 向量服务模块。

调用阿里云 DashScope 多模态 Embedding 接口，把文本批量转为向量。
内置分批、限速、重试机制，避免触发接口限流并提高成功率。

@author: ziyu
@date: 2026-07-16
"""
import time
from http import HTTPStatus

import dashscope

from app.core.config import settings


class DashScopeEmbeddingService:
    """DashScope Embedding 服务：分批向量化 + 限速 + 失败重试。"""

    def __init__(
        self,
        model_name: str | None = None,
        batch_size: int | None = None,
        batch_interval_seconds: float | None = None,
        retry_count: int | None = None,
        retry_interval_seconds: float | None = None,
    ):
        self.model_name = model_name or settings.embedding_model
        self.batch_size = batch_size or settings.embedding_batch_size
        self.batch_interval_seconds = batch_interval_seconds or settings.embedding_batch_interval_seconds
        self.retry_count = retry_count or settings.embedding_retry_count
        self.retry_interval_seconds = retry_interval_seconds or settings.embedding_retry_interval_seconds

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """把一批文本转为向量，分批调用并限速；最终校验向量数量与文本数量一致。"""
        if not texts:
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch_texts = texts[start : start + self.batch_size]
            vectors.extend(self._embed_batch(batch_texts))
            time.sleep(self.batch_interval_seconds)

        if len(vectors) != len(texts):
            raise RuntimeError(f"向量数量不一致，文本 {len(texts)} 条，向量 {len(vectors)} 条。")
        return vectors

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """对单批文本调用 Embedding 接口，失败按 retry_count 重试。"""
        input_payload = [{"text": text} for text in texts]
        last_error: Exception | None = None
        for _ in range(self.retry_count):
            try:
                resp = dashscope.MultiModalEmbedding.call(
                    model=self.model_name,
                    input=input_payload,
                )
                if resp.status_code == HTTPStatus.OK:
                    return [item["embedding"] for item in resp.output["embeddings"]]
                last_error = RuntimeError(f"embedding失败: {resp.status_code} {getattr(resp, 'message', '')}")
            except Exception as exc:
                last_error = exc
            time.sleep(self.retry_interval_seconds)
        raise RuntimeError(f"embedding接口重试失败: {last_error}")
