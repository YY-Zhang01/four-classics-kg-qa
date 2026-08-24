"""智能路由模块（P2）：问题分类 + 策略分发。

对外暴露：
  route(question) → (RouteResult, Strategy)
  classify(question) → RouteResult
"""
from __future__ import annotations

from router.classifier import classify, RouteResult
from router.strategies import get_strategy, Strategy


def route(question: str) -> tuple[RouteResult, Strategy]:
    """统一路由入口：分类问题 → 返回对应策略。

    用法：
        result, strategy = route("林黛玉是什么性格")
        # result.question_type = "FACT"
        # strategy.name = "事实查询"
        # strategy.wiki_quota = 2, strategy.vector_quota = 3

    然后调用 fusion.search_with_strategy(query, strategy) 进行策略化检索。
    """
    result = classify(question)
    strategy = get_strategy(result.question_type)
    return result, strategy
