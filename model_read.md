# 部署说明

> ⚠️ 以下为通用部署参考，请用你自己的服务器信息替换占位内容。

## 服务器

- 操作系统：CentOS 7
- 端口：22
- 连接方式：ssh
- 部署路径：`<你的服务器部署路径>`
- 服务器账号：`<你的账号>`
- 本地 conda 环境：`pdf_model`
- 服务器 conda 环境：`dataset`

## 基础设施

ES、Milvus 均部署在 Docker 中，建议配置账号密码后对外暴露。

- **Elasticsearch + Kibana**：启动方式见 [docker/elasticsearch.sh](docker/elasticsearch.sh) 与 [docker/kibana.sh](docker/kibana.sh)（需先启动 ES）
- **Milvus**：启动方式见 [docker/milvus-compose.yml](docker/milvus-compose.yml)

## 环境变量

部署时在 `.env` 中填写：

- `MYSQL_*`：MySQL 连接信息
- `ES_*`：Elasticsearch 连接信息
- `MILVUS_*`：Milvus 连接信息
- `DASHSCOPE_API_KEY`：阿里云 DashScope（通义千问 / Embedding / Rerank）密钥
- `ACCESS_PASSWORD` / `API_TOKEN` / `FLASK_SECRET_KEY`：Web 与接口访问凭证
