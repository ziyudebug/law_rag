"""
Milvus 向量检索与集合管理测试脚本。

提供单条文本向量化、向量相似检索、按租户/知识库删除数据、删除集合等开发期验证能力。

@author: ziyu
@date: 2026-07-21
"""
from dashscope import MultiModalEmbedding
from config.milvus_config import client
from app.core.config import settings

# 向量模型
EMBED_MODEL = settings.embedding_model
# 集合名
COLLECTION = settings.milvus_collection_name

def get_text_embedding(text: str):
    """单条文本生成向量。"""
    input_data = [{"text": text}]
    resp = MultiModalEmbedding.call(
        model=EMBED_MODEL,
        input=input_data
    )
    if resp.status_code != 200:
        raise Exception(f"向量化失败: {resp.code} {resp.message}")
    return resp.output["embeddings"][0]["embedding"]


def milvus_vector_search_test(search_text: str, kb_id: str = "1", tenant_id: str = "1", top_k: int = 5):
    """
    Milvus 向量检索测试方法
    :param search_text: 检索文本
    :param kb_id: 知识库过滤条件
    :param top_k: 返回相似条数
    """
    # 1. 加载集合（已加载可注释，避免重复加载耗时）
    client.load_collection(COLLECTION)

    # 2. 生成查询向量
    query_vec = get_text_embedding(search_text)

    # 3. 向量相似度检索
    search_result = client.search(
        collection_name=COLLECTION,
        data=[query_vec],          # 查询向量数组
        filter=f'kb_id == "{kb_id}" && tenant_id == "{tenant_id}"',
        output_fields=["chunk_id", "content", "metadata"],
        limit=top_k,
        search_params={
            "metric_type": settings.milvus_search_metric_type,
            "params": {"nprobe": settings.milvus_search_nprobe}
        }
    )

    # 4. 打印检索结果
    print(f"===== 检索文本：{search_text} =====")
    for hits in search_result:
        for hit in hits:
            print(f"相似度分数: {hit.score:.4f}")
            print(f"chunk_id: {hit.entity.get('chunk_id')}")
            print(f"content: {hit.entity.get('content')}")
            print(f"metadata: {hit.entity.get('metadata')}")
            print("-" * 60)

    return search_result



def delete_collection(tenant_id: str = "1", kb_id: str = "1"):
    """按 tenant_id+kb_id 删除 Milvus 中的分块数据。"""
    client.delete(

        collection_name=COLLECTION,

        filter=f"""
        tenant_id == "{tenant_id}"
        && kb_id == "{kb_id}"
        """

    )

def delete_list():
    """直接删除整个集合（开发期清空数据用）。"""
    coll_name = COLLECTION

    if client.has_collection(coll_name):
        client.drop_collection(coll_name)

if __name__ == "__main__":
    # 调用测试
    # test_query = "检测单位"
    #
    # milvus_vector_search_test(search_text=test_query, kb_id="1", tenant_id="1", top_k=5)
    # delete_collection(tenant_id="1", kb_id="1")
    delete_list()
