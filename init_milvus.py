"""
Milvus 向量库初始化脚本。

负责创建知识库分段的 Collection（含多租户 partition_key 隔离）、向量索引与辅助索引，
若 Collection 已存在则直接加载到内存。可单独执行：python init_milvus.py

@author: ziyu
@date: 2026-07-21
"""
from config.milvus_config import client
from pymilvus import DataType
from app.core.config import settings

# 知识库分段集合名
c_name = settings.milvus_collection_name
if client.has_collection(c_name):
    # 集合已存在，直接加载到内存供检索使用
    client.load_collection(c_name)
    print(f"加载{c_name}完成")
else:
    # id
    schema = client.create_schema(primary_field="chunk_id", auto_id=False)
    # 分段id
    schema.add_field(
        field_name="chunk_id",
        datatype=DataType.VARCHAR,
        max_length=128,
        is_primary=True
    )
    # 文档id
    schema.add_field(
        field_name="document_id",
        datatype=DataType.VARCHAR,
        max_length=128
    )
    # 租户id
    schema.add_field(field_name="tenant_id", datatype=DataType.VARCHAR, max_length=64, is_partition_key=True)
    # 知识库id
    schema.add_field(field_name="kb_id", datatype=DataType.VARCHAR, max_length=64)
    # 文档内容
    schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=65535)
    # 向量
    schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=settings.embedding_dim)
    # 文件地址
    schema.add_field(field_name="source_file", datatype=DataType.VARCHAR, max_length=512)
    schema.add_field(field_name="parent_id", datatype=DataType.VARCHAR, max_length=128)
    # 分段元数据
    schema.add_field(field_name="metadata", datatype=DataType.JSON)
    # 多租户隔离开启
    params = {"partitionkey.isolation": True}
    client.create_collection(
        collection_name=c_name,
        schema=schema,
        properties=params
    )
    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="vector",
        index_type=settings.milvus_vector_index_type,
        metric_type=settings.milvus_vector_metric_type,
        params={
            "M": settings.milvus_vector_index_m,
            "efConstruction": settings.milvus_vector_index_ef_construction,
        },
    )
    index_params.add_index(field_name="kb_id", index_type="INVERTED")
    index_params.add_index(field_name="document_id", index_type="INVERTED")

    client.create_index(collection_name=c_name, index_params=index_params)
    print("MilvusClient 创建完成")
    client.load_collection(c_name)
