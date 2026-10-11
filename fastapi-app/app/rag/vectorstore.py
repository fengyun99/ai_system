# -*- coding: utf-8 -*-
"""ES 混合检索层——BM25(jieba 预分词) + kNN 向量双路召回，租户过滤含祖先链扩展。

索引设计（index: ai_kb）：
  text        原文（index=False，仅存储回显）
  tokens      jieba 预分词空格串（whitespace 分析器）——BM25 打分字段
  text_vector dense_vector(HNSW, cosine)——kNN 打分字段
  dept_code/is_public/biz_type/theme/knowledge_id/title 过滤与回显字段
"""
from __future__ import annotations

import uuid
from typing import Any

import jieba
from elasticsearch import Elasticsearch

from app.settings import get_settings

_es: Elasticsearch | None = None
_INDEX: str = ""


def get_es() -> Elasticsearch:
    global _es, _INDEX
    if _es is None:
        s = get_settings()["es"]
        scheme = s.get("scheme", "http")
        _es = Elasticsearch(
            f"{scheme}://{s['host']}:{s['port']}",
            basic_auth=(s["username"], s["password"]),
            # ES 8 自签证书部署下免校验（演示环境）
            verify_certs=scheme != "https",
            ssl_show_warn=False,
        )
        _INDEX = s.get("index", "ai_kb")
    return _es


def index_name() -> str:
    global _INDEX
    if not _INDEX:
        s = get_settings()["es"]
        _INDEX = s.get("index", "ai_kb")
    return _INDEX


def ensure_index() -> None:
    es = get_es()
    dims = int(get_settings()["es"].get("vector_dims", 1536))
    if not es.indices.exists(index=index_name()):
        es.indices.create(index=index_name(), body={
            "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            "mappings": {
                "properties": {
                    "knowledge_id": {"type": "long"},
                    "chunk_id": {"type": "keyword"},
                    "title": {"type": "keyword"},
                    "text": {"type": "text", "index": False},
                    "tokens": {"type": "text", "analyzer": "whitespace"},
                    "text_vector": {
                        "type": "dense_vector", "dims": dims,
                        "index": True, "similarity": "cosine",
                    },
                    "dept_code": {"type": "keyword"},
                    "is_public": {"type": "integer"},
                    "biz_type": {"type": "keyword"},
                    "theme": {"type": "keyword"},
                }
            },
        })


def jieba_tokens(text: str) -> str:
    return " ".join(t.strip() for t in jieba.cut(text) if t.strip())


def _visibility_filter(dept_no: str, extra_depts: list[str]) -> dict:
    """租户过滤：本部门全量 ∪ 祖先链公开知识（兄弟互不可见）。"""
    should = [{"term": {"dept_code": dept_no}}]
    if extra_depts:
        should.append({"bool": {"must": [
            {"terms": {"dept_code": extra_depts}},
            {"term": {"is_public": 1}},
        ]}})
    return {"bool": {"should": should, "minimum_should_match": 1}}


def hybrid_search(query: str, query_vector: list[float], dept_no: str,
                  extra_depts: list[str], theme: str = "", size: int = 20) -> dict[str, list[dict]]:
    """双路召回：BM25(tokens) + kNN(vector)，各自返回 chunk_id 有序列表与文档明细。

    返回 {"bm25": [...], "knn": [...]}，每路按自身得分降序。
    """
    es = get_es()
    filt = _visibility_filter(dept_no, extra_depts)
    if theme:
        filt = {"bool": {"must": [filt, {"term": {"theme": theme}}]}}

    token_query = {"match": {"tokens": {"query": jieba_tokens(query), "operator": "or"}}}
    bm25_body = {"query": {"bool": {"must": [token_query], "filter": [filt]}},
                 "size": size, "_source": ["chunk_id"]}
    knn_body = {
        "knn": {
            "field": "text_vector", "query_vector": query_vector,
            "k": size, "num_candidates": max(size * 5, 50),
            "filter": filt,
        },
        "size": size, "_source": ["chunk_id"],
    }
    resp = es.msearch(index=index_name(), searches=[{}, bm25_body, {}, knn_body])
    bm25_hits = resp["responses"][0].get("hits", {}).get("hits", [])
    knn_hits = resp["responses"][1].get("hits", {}).get("hits", [])
    return {
        "bm25": [{"chunk_id": h["_source"]["chunk_id"], "score": h["_score"]} for h in bm25_hits],
        "knn": [{"chunk_id": h["_source"]["chunk_id"], "score": h["_score"]} for h in knn_hits],
    }


def mget_chunks(chunk_ids: list[str]) -> dict[str, dict]:
    """按 chunk_id 批量取文档明细（去重保序）。"""
    if not chunk_ids:
        return {}
    es = get_es()
    resp = es.mget(index=index_name(), body={"ids": chunk_ids})
    out: dict[str, dict] = {}
    for doc in resp["docs"]:
        if doc.get("found"):
            src = doc["_source"]
            out[src["chunk_id"]] = src
    return out


def bulk_index_chunks(knowledge_id: int, title: str, dept_no: str, biz_type: str,
                      theme: str, is_public: int, chunks: list[str],
                      vectors: list[list[float]]) -> int:
    es = get_es()
    actions: list[dict] = []
    for text, vec in zip(chunks, vectors):
        chunk_id = uuid.uuid4().hex
        actions.append({"index": {"_index": index_name(), "_id": chunk_id}})
        actions.append({
            "knowledge_id": knowledge_id, "chunk_id": chunk_id, "title": title,
            "text": text, "tokens": jieba_tokens(text), "text_vector": vec,
            "dept_code": dept_no, "is_public": is_public, "biz_type": biz_type,
            "theme": theme,
        })
    if actions:
        es.bulk(body=actions, refresh="wait_for")
    return len(chunks)


def delete_by_knowledge(knowledge_id: int) -> None:
    get_es().delete_by_query(index=index_name(), body={"query": {"term": {"knowledge_id": knowledge_id}}},
                             refresh=True)


def count_docs(dept_no: str | None = None) -> int:
    es = get_es()
    body: dict[str, Any] = {"query": {"match_all": {}}}
    if dept_no:
        body = {"query": {"term": {"dept_code": dept_no}}}
    return es.count(index=index_name(), body=body)["count"]


def mget_all_knowledge_ids() -> set[int]:
    """scroll 零正文枚举索引内全部 knowledge_id（对账用）。"""
    es = get_es()
    ids: set[int] = set()
    resp = es.search(index=index_name(), body={
        "query": {"match_all": {}}, "_source": ["knowledge_id"],
        "size": 1000, "sort": ["_doc"],
    })
    while True:
        hits = resp["hits"]["hits"]
        if not hits:
            break
        ids.update(int(h["_source"]["knowledge_id"]) for h in hits)
        cursor = hits[-1]["sort"]
        resp = es.search(index=index_name(), body={
            "query": {"match_all": {}}, "_source": ["knowledge_id"],
            "size": 1000, "sort": ["_doc"],
            "search_after": cursor,
        })
    return ids
