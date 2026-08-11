"""
Elasticsearch 客户端模块。

配置了账号密码时走 basic_auth，否则保持匿名连接（本地开发兼容）。
显式声明 compatible-with=8，避免 elasticsearch-py 9.x 默认发 version 9 的 Accept 头被 ES 8.x 拒绝。

@author: ziyu
@date: 2026-07-29
"""
from elasticsearch import Elasticsearch

from app.core.config import settings

# 配置了账号密码时走 basic_auth，否则保持匿名连接（本地开发兼容）
# 显式声明 compatible-with=8，避免 elasticsearch-py 9.x 默认发 version 9 的 Accept 头被 ES 8.x 拒绝
_COMPAT_HEADERS = {
    "Accept": "application/vnd.elasticsearch+json; compatible-with=8",
    "Content-Type": "application/vnd.elasticsearch+json; compatible-with=8",
}

# 全局 ES 客户端实例
es_client = Elasticsearch(
    settings.es_url,
    basic_auth=(settings.es_username, settings.es_password) if settings.es_username else None,
    headers=_COMPAT_HEADERS,
)
