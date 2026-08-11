# 创建 mapping
```angular2html
curl -X PUT "localhost:9200/kb_chunk_index" \
-H "Content-Type: application/json" \
-d '
{
 "settings":{
   "analysis":{
     "analyzer":{
       "default":{
          "type":"ik_max_word"
       }
     }
   }
 },
 "mappings":{
   "properties":{

     "chunk_id":{
       "type":"keyword"
     },

     "document_id":{
       "type":"keyword"
     },

     "tenant_id":{
       "type":"keyword"
     },

     "kb_id":{
       "type":"keyword"
     },
     "parent_id":{
       "type":"keyword"
     },


     "content":{
       "type":"text",
       "analyzer":"ik_max_word",
       "search_analyzer":"ik_smart"
     },


     "source_file":{
       "type":"keyword"
     },


     "metadata":{
       "type":"object"
     }

   }
 }
}
'
```
```angular2html
curl -X PUT "http://127.0.0.1:9200/kb_file_tree_index" \
-H "Content-Type: application/json" \
-d'
{
  "settings": {
    "analysis": {
      "analyzer": {
        "ik_text": {
          "type": "custom",
          "tokenizer": "ik_max_word"
        }
      }
    }
  },
  "mappings": {
    "properties": {
      "id": {
        "type": "long"
      },
      "tenant_id": {
        "type": "long"
      },
      "kb_id": {
        "type": "long"
      },
      "node_type": {
        "type": "integer"
      },
      "name": {
        "type": "text",
        "analyzer": "ik_text",
        "search_analyzer": "ik_smart"
      },
      "full_path": {
        "type": "text",
        "analyzer": "ik_text"
      },
      "extension": {
        "type": "keyword"
      },
      "path": {
        "type": "keyword"
      },
      "parent_id": {
        "type": "long"
      },
      "create_time": {
        "type": "date"
      }, 
      "document_id": {
        "type": "long"
      }
    }
  }
}'

```