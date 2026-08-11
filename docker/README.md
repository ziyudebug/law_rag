# docker/ · 基础设施部署脚本

各文件单一职责，按需执行：

| 文件 | 职责 | 启动命令 |
|------|------|----------|
| `elasticsearch.sh` | Elasticsearch 容器（含数据/插件卷、单节点、关闭安全） | `bash docker/elasticsearch.sh` |
| `kibana.sh` | Kibana 容器，连接上方 ES（`http://es:9200`） | `bash docker/kibana.sh` |
| `elasticsearch-mapping.md` | ES 索引 mapping（`kb_chunk_index` / `kb_file_tree_index`） | 见文件内 curl 命令 |
| `milvus-compose.yml` | Milvus Standalone（etcd + minio + milvus） | `docker compose -f docker/milvus-compose.yml up -d` |

## 依赖关系

- `kibana.sh` 依赖 `elasticsearch.sh` 创建的 `es-net` 网络与 `es` 容器，需先启动 ES。
- `elasticsearch-mapping.md` 中的 mapping 需在 ES 启动后执行（初始化数据库步骤）。
- `milvus-compose.yml` 与 ES 相互独立，可并行启动。

## 安全须知

脚本默认 `xpack.security.enabled=false`、Milvus/minio 使用默认密码，仅适用于内网/开发环境。
对外暴露前请务必开启鉴权并替换默认凭证，参见根目录 `readme.md` 的「安全须知」章节。
