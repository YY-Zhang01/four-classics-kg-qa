"""审核模块（P4）：待审队列查询、状态流转、操作日志。

审核范围：
  chunk     — 低置信度知识块
  kg_triple — 低置信度 KG 三元组（confidence < 0.8）
  wiki_page — 新生成的 Wiki 页面（首次生成默认待审）

状态流转：
  pending → approved (生效)
  pending → rejected (废弃，记原因)
  pending → needs_revision (退回，附修改意见)
  approved → deprecated (旧版本标记失效)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ── 状态常量 ──
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_NEEDS_REVISION = "needs_revision"
STATUS_DEPRECATED = "deprecated"

VALID_STATUSES = {STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED, STATUS_NEEDS_REVISION, STATUS_DEPRECATED}

# confidence 低于此值的自动进待审
AUTO_REVIEW_THRESHOLD = 0.8


@dataclass
class ReviewTarget:
    """审核目标摘要。"""
    target_type: str          # "chunk" / "kg_triple" / "wiki_page"
    target_id: str            # chunks.id / kg_triples.id / wiki_pages.id
    title: str = ""           # 简短标识
    detail: dict = field(default_factory=dict)  # 完整数据（供详情页展示）
    confidence: float = 0.0
    review_status: str = STATUS_PENDING
    domain: str = ""
    created_at: str = ""


@dataclass
class ReviewStats:
    """审核统计。"""
    pending_chunks: int = 0
    pending_kg: int = 0
    pending_wiki: int = 0
    total_pending: int = 0
    approved_today: int = 0
    rejected_today: int = 0

    @property
    def has_pending(self) -> bool:
        return self.total_pending > 0
