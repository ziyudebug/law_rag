"""
Flask 应用工厂模块。

负责创建 Flask 应用实例，装配各业务 service（检索、上传、文件夹、检索范围解析）并挂载到
app.extensions，供路由层通过 current_app.extensions 取用；同时注册全部蓝图。

@author: ziyu
@date: 2026-07-27
"""
from flask import Flask


def create_app() -> Flask:
    """创建并装配 Flask 应用，返回可运行的应用实例。"""
    from app.api import register_blueprints
    from app.core.config import settings
    from app.repositories.retrieval_config_repository import RetrievalConfigRepository
    from app.repositories.folder_repository import FolderRepository
    from app.services.retrieval_service import RetrievalService
    from app.services.folder_service import FolderService
    from app.services.retrieval_scope_resolver import RetrievalScopeResolver
    from app.services.upload_bootstrap import build_upload_service
    from config.es_config import es_client
    from config.milvus_config import client as milvus_client

    app = Flask(__name__, template_folder="templates")
    app.config["MAX_CONTENT_LENGTH"] = settings.max_content_length
    app.json.ensure_ascii = False
    app.secret_key = settings.flask_secret_key

    # 检索配置仓储：按 tenant_id × kb_id 存取检索参数
    retrieval_config_repository = RetrievalConfigRepository()
    app.extensions["retrieval_config_repository"] = retrieval_config_repository
    # 文件夹仓储：操作文件树节点
    folder_repository = FolderRepository()
    app.extensions["folder_repository"] = folder_repository
    # 检索服务：向量 + 全文 + Rerank 的混合检索
    app.extensions["retrieval_service"] = RetrievalService(
        es_client=es_client,
        milvus_client=milvus_client,
        collection_name=settings.milvus_collection_name,
        config_repository=retrieval_config_repository,
        es_index_name=settings.es_chunk_index_name,
        embedding_model=settings.embedding_model,
        candidate_multiplier=settings.retrieval_candidate_multiplier,
        min_hybrid_candidate_k=settings.retrieval_min_candidate_k,
        rerank_instruct=settings.rerank_instruct,
    )
    # 上传服务：异步入库（解析 → 分段 → 向量化 → 双写索引）
    app.extensions["upload_service"] = build_upload_service(
        es_client=es_client,
        milvus_client=milvus_client,
        collection_name=settings.milvus_collection_name,
        es_index_name=settings.es_chunk_index_name,
        worker_count=settings.upload_worker_count,
        embedding_model=settings.embedding_model,
        embedding_batch_size=settings.embedding_batch_size,
        embedding_batch_interval_seconds=settings.embedding_batch_interval_seconds,
        embedding_retry_count=settings.embedding_retry_count,
        embedding_retry_interval_seconds=settings.embedding_retry_interval_seconds,
        parent_chunk_size=settings.parent_chunk_size,
        parent_chunk_overlap=settings.parent_chunk_overlap,
        child_chunk_size=settings.child_chunk_size,
        child_chunk_overlap=settings.child_chunk_overlap,
        table_row_group_size=settings.table_row_group_size,
    )
    # 文件夹服务：文件树增删改查 + ES 索引
    app.extensions["folder_service"] = FolderService(
        repository=folder_repository,
        es_client=es_client,
        es_index_name=settings.es_file_tree_index_name,
    )
    # 检索范围解析器：把文件夹/文档/节点约束解析为 document_id 过滤条件
    app.extensions["retrieval_scope_resolver"] = RetrievalScopeResolver(folder_repository=folder_repository)
    # token 校验失败日志路径
    app.extensions["err_log"] = settings.err_log


    register_blueprints(app)
    return app
