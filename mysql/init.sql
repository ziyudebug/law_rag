CREATE TABLE `kb_chunk_metadata` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键',
  `chunk_id` bigint NOT NULL COMMENT '分段ID',
  `law_name` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '法规名称',
  `industry` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '适用行业，例如化工、电镀',
  `pollutant` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '污染物，例如COD、VOCs',
  `behavior` varchar(256) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '违法行为，例如超标排放、无证排污',
  `penalty` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '处罚措施',
  `region` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '适用地区',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_chunk_id` (`chunk_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='环保法规知识增强信息表';


CREATE TABLE `kb_document` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '文档ID',
  `tenant_id` bigint NOT NULL COMMENT '租户ID',
  `kb_id` bigint NOT NULL COMMENT '所属知识库ID',
  `file_name` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '文件名称',
  `file_url` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '文件存储地址，例如MinIO地址',
  `file_type` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '文件类型 PDF DOCX XLSX',
  `file_size` bigint DEFAULT NULL COMMENT '文件大小，单位字节',
  `status` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '处理状态 UPLOADING/PARSING/EMBEDDING/DONE/FAILED',
  `chunk_count` int DEFAULT '0' COMMENT '生成的分段数量',
  `version` varchar(32) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '文档版本',
  `effective_date` date DEFAULT NULL COMMENT '生效日期',
  `expire_date` date DEFAULT NULL COMMENT '失效日期',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '上传时间',
  PRIMARY KEY (`id`),
  KEY `idx_tenant_id` (`tenant_id`),
  KEY `idx_kb_id` (`kb_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库文档表';
CREATE TABLE `kb_document_chunk` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '分段ID',
  `tenant_id` bigint NOT NULL COMMENT '租户ID',
  `document_id` bigint NOT NULL COMMENT '所属文档ID',
  `chunk_no` int NOT NULL COMMENT '当前文档中的分段序号',
  `content` text COLLATE utf8mb4_unicode_ci COMMENT '分段文本内容',
  `page_no` int DEFAULT NULL COMMENT '所在页码',
  `chapter` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '章节，例如第五章 法律责任',
  `article` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '条款，例如第三十五条',
  `token_count` int DEFAULT NULL COMMENT '文本token数量',
  `milvus_id` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Milvus中的向量ID',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `parent_chunk_id` bigint DEFAULT NULL COMMENT '父分段',
  PRIMARY KEY (`id`),
  KEY `idx_document_id` (`document_id`),
  KEY `idx_tenant_id` (`tenant_id`),
  KEY `idx_parent_chunk_id` (`parent_chunk_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库文本分段子表';

CREATE TABLE `kb_document_parent_chunk` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '分段ID',
  `tenant_id` bigint NOT NULL COMMENT '租户ID',
  `document_id` bigint NOT NULL COMMENT '所属文档ID',
  `chunk_no` int NOT NULL COMMENT '当前文档中的分段序号',
  `content` text CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci COMMENT '分段文本内容',
  `page_no` int DEFAULT NULL COMMENT '所在页码',
  `chapter` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '章节，例如第五章 法律责任',
  `article` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '条款，例如第三十五条',
  `token_count` int DEFAULT NULL COMMENT '文本token数量',
  `milvus_id` varchar(128) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Milvus中的向量ID',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_document_id` (`document_id`),
  KEY `idx_tenant_id` (`tenant_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库文本分段父表';

CREATE TABLE `kb_knowledge_base` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '知识库ID',
  `tenant_id` bigint NOT NULL COMMENT '所属租户ID',
  `name` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '知识库名称',
  `description` varchar(512) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '知识库描述',
  `status` tinyint DEFAULT '1' COMMENT '状态 1启用 0禁用',
  `create_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_tenant_id` (`tenant_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库信息表';

CREATE TABLE `kb_retrieval_config` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `tenant_id` bigint NOT NULL COMMENT '租户ID',
  `kb_id` bigint NOT NULL COMMENT '知识库ID，每个知识库对应一套检索配置',
  `retrieval_mode` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'HYBRID' COMMENT '当前生效检索方式 VECTOR向量检索 FULLTEXT全文检索 HYBRID混合检索，三选一',
  `use_rerank` tinyint NOT NULL DEFAULT '1' COMMENT '当前检索方式是否使用rerank模型 1是 0否；混合检索RERANK策略固定为1',
  `rerank_model` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'qwen3-rerank' COMMENT '当前检索方式使用的rerank模型名称',
  `hybrid_strategy` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'RERANK' COMMENT '混合检索内部排序策略 RERANK使用重排序模型 WEIGHT使用语义和关键词权重；仅retrieval_mode为HYBRID时生效',
  `semantic_weight` decimal(6,4) NOT NULL DEFAULT '0.6000' COMMENT '混合检索权重策略中的语义向量权重；仅HYBRID且hybrid_strategy为WEIGHT时生效',
  `keyword_weight` decimal(6,4) NOT NULL DEFAULT '0.4000' COMMENT '混合检索权重策略中的关键词全文权重；仅HYBRID且hybrid_strategy为WEIGHT时生效',
  `top_k` int NOT NULL DEFAULT '5' COMMENT '当前检索方式返回Top K数量',
  `enable_source` tinyint NOT NULL DEFAULT '1' COMMENT '当前检索方式是否返回source信息 1返回 0不返回',
  `score_threshold` decimal(12,8) NOT NULL DEFAULT '0.00000000' COMMENT '当前检索方式Score最小阈值，支持小数，低于该值的结果过滤',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '配置状态 1启用 0禁用',
  `create_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_tenant_kb` (`tenant_id`,`kb_id`),
  KEY `idx_tenant_id` (`tenant_id`),
  KEY `idx_kb_id` (`kb_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库检索配置表';
