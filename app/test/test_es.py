"""
Elasticsearch 分块索引检索与清理测试脚本。

提供按租户/知识库/文档的全文检索、按条件删除索引文档的开发期验证能力。

@author: ziyu
@date: 2026-07-16
"""
from app.core.config import settings
from config.es_config import es_client


# ==========================
# ES连接
# ==========================

es = es_client
INDEX_NAME = settings.es_chunk_index_name



def search_chunk(
        question,
        tenant_id,
        kb_id,
        document_id=None,
        size=5
):
    """
    ES知识库检索

    :param question: 用户问题
    :param tenant_id: 租户
    :param kb_id: 知识库
    :param document_id: 文档(可选)
    """


    filters = [

        {
            "term":{
                "tenant_id":tenant_id
            }
        },

        {
            "term":{
                "kb_id":kb_id
            }
        }

    ]


    # 如果指定文档
    if document_id:

        filters.append(

            {
                "term":{
                    "document_id":document_id
                }
            }

        )



    body = {


        "size":size,


        "_source":[

            "chunk_id",
            "document_id",
            "content",
            "source_file",
            "metadata"

        ],


        "query":{

            "bool":{


                # 关键词匹配
                "must":[

                    {
                        "match":{

                            "content":question

                        }
                    }

                ],


                # 租户/知识库/文档过滤
                "filter":filters

            }

        }

    }



    resp = es.search(

        index=INDEX_NAME,

        body=body

    )


    return resp

def delete_es_document(
        tenant_id,
        kb_id,
        document_id=None
):
    """按 tenant_id/kb_id/document_id 删除 ES 分块索引中的文档。"""


    filters=[

        {
            "term":{
                "tenant_id":tenant_id
            }
        },

        {
            "term":{
                "kb_id":kb_id
            }
        }

    ]


    if document_id:

        filters.append({

            "term":{
                "document_id":document_id
            }

        })


    resp = es_client.delete_by_query(

        index=INDEX_NAME,

        query={

            "bool":{

                "filter":filters

            }

        }

    )


    print(resp)

if __name__ == "__main__":

    delete_es_document(
        tenant_id="1",
        kb_id="1")

    # result = search_chunk(
    #
    #     question="环境保护法",
    #
    #     tenant_id="1",
    #
    #     kb_id="1",
    #
    #     document_id="2",
    #
    #     size=5
    #
    # )
    #
    #
    # print(
    #     "命中数量:",
    #     result["hits"]["total"]
    # )
    #
    #
    # print("====================")
    #
    #
    # for hit in result["hits"]["hits"]:
    #
    #
    #     print(
    #         "score:",
    #         hit["_score"]
    #     )
    #
    #
    #     source=hit["_source"]
    #
    #
    #     print(
    #         "chunk_id:",
    #         source["chunk_id"]
    #     )
    #
    #
    #     print(
    #         "document_id:",
    #         source["document_id"]
    #     )
    #
    #
    #     print(
    #         "文件:",
    #         source["source_file"]
    #     )
    #
    #
    #     print(
    #         "内容:"
    #     )
    #
    #
    #     print(
    #         source["content"][:300]
    #     )
    #
    #
    #     print(
    #         "metadata:",
    #         json.dumps(
    #             source["metadata"],
    #             ensure_ascii=False
    #         )
    #     )
    #
    #
    #     print("--------------------")
