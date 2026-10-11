# -*- coding: utf-8 -*-
"""RRF 倒数排名融合（k=60）——BM25 与 kNN 两路召回的融合层。"""
from __future__ import annotations

RRF_K = 60


def rrf_fuse(result_lists: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """多路召回结果融合。

    result_lists: 每路一个 chunk_id 有序列表（按相关性降序）；
    返回 [(chunk_id, rrf_score)] 按融合分降序。
    """
    scores: dict[str, float] = {}
    for results in result_lists:
        for rank, chunk_id in enumerate(results):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
