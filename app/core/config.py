"""
应用配置中心。

所有可部署环境中可能变化的参数统一从环境变量（.env）读取，业务代码只依赖 settings，
便于在不同环境切换而无需改动源码。

@author: ziyu
@date: 2026-08-11
"""
from functools import lru_cache
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置。字段名可直接作为环境变量名的大写形式使用。"""

    # Flask / Web
    flask_secret_key: str = "change-me"
    flask_debug: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 5001
    max_content_length_mb: int = 50
    access_password: str = "change-me"
    api_token: str = "change-me"
    err_log: str = "token_error_logs.txt"

    # MySQL
    mysql_host: str = "localhost"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "dataset"
    mysql_echo: bool = False
    mysql_pool_recycle: int = 300

    # Elasticsearch
    es_url: str = "http://localhost:9200"
    es_username: str = ""
    es_password: str = ""
    es_chunk_index_name: str = "kb_chunk_index"
    es_file_tree_index_name: str = "kb_file_tree_index"

    # Milvus
    milvus_alias: str = "default"
    milvus_host: str = "127.0.0.1"
    milvus_port: str = "19530"
    milvus_username: str = ""
    milvus_password: str = ""
    milvus_collection_name: str = "zczj_all_tenant"
    embedding_dim: int = 1024
    milvus_vector_index_type: str = "HNSW"
    milvus_vector_metric_type: str = "COSINE"
    milvus_vector_index_m: int = 16
    milvus_vector_index_ef_construction: int = 128
    milvus_search_metric_type: str = "COSINE"
    milvus_search_nprobe: int = 16

    # Embedding / Rerank / Qwen
    embedding_model: str = "multimodal-embedding-v1"
    embedding_batch_size: int = 20
    embedding_batch_interval_seconds: float = 0.2
    embedding_retry_count: int = 3
    embedding_retry_interval_seconds: float = 1.0
    default_rerank_model: str = "qwen3-rerank"
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = ""
    qwen_temperature: float = 0.1
    dashscope_api_key: str = ""
    model_config_json: str = "[]"
    rerank_instruct: str = (
        "你是一个环保法规知识库检索排序模型。"
        "请根据用户问题判断候选文本相关性。"
        "优先考虑法律法规、污染物排放标准、企业环保责任、合规要求等内容。"
    )

    # Retrieval defaults
    retrieval_default_mode: str = "HYBRID"
    retrieval_default_hybrid_strategy: str = "RERANK"
    retrieval_default_use_rerank: bool = False
    retrieval_default_semantic_weight: float = 0.6
    retrieval_default_keyword_weight: float = 0.4
    retrieval_default_top_k: int = 5
    retrieval_default_enable_source: bool = True
    retrieval_default_score_threshold: float = 0.0
    retrieval_candidate_multiplier: int = 2
    retrieval_min_candidate_k: int = 20

    # PaddleOCR / OCR cache
    # paddle_ocr_api_url: str = "https://ze43n754f721d5of.aistudio-app.com/layout-parsing"
    paddle_vl_backend: str = "vllm-server"
    paddle_vl_server_url: str = "http://127.0.0.1:9889/v1"
    paddle_ocr_output_root: str = ""

    # Upload / Chunking
    upload_worker_count: int = 2
    parent_chunk_size: int = 1000
    parent_chunk_overlap: int = 100
    child_chunk_size: int = 200
    child_chunk_overlap: int = 50
    table_row_group_size: int = 3

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow",
        case_sensitive=False,
    )

    @property
    def database_url(self) -> str:
        """拼接 SQLAlchemy 可用的 MySQL 连接串，密码做 URL 编码。"""
        user = quote_plus(self.mysql_user)
        password = quote_plus(self.mysql_password)
        return f"mysql+pymysql://{user}:{password}@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"

    @property
    def max_content_length(self) -> int:
        """Flask 上传请求体大小上限（字节）。"""
        return self.max_content_length_mb * 1024 * 1024

    @property
    def ERR_LOG(self) -> str:
        """token 校验失败日志路径（大写别名，供鉴权层使用）。"""
        return self.err_log

    @property
    def MODEL_CONFIG_JSON(self) -> str:
        """多模型加权配置 JSON 字符串（大写别名）。"""
        return self.model_config_json

    @property
    def DASHSCOPE_API_KEY(self) -> str:
        """DashScope API Key（大写别名）。"""
        return self.dashscope_api_key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """获取单例 Settings（带 lru 缓存，避免重复解析 .env）。"""
    return Settings()


settings = get_settings()
