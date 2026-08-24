"""问题类型分类器（P2）：规则 + LLM 双通道。

规则通道：正则关键词匹配，毫秒级响应，覆盖 90% 常见问法。
LLM 通道：规则不匹配或置信度过低时触发，处理复杂/模糊问题。

问题类型定义：
  FACT       — 查事实："XXX 是什么"、"XXX 在第几回出现"
  RELATION   — 查关系："林黛玉和薛宝钗什么关系"、"XXX 需要哪些材料"
  COMPARE    — 查对比："林黛玉和王熙凤性格有什么不同"
  PROCEDURE  — 查流程："XXX 怎么办理"、"办理流程是什么"
  LATEST     — 查最新："最近有什么变化"、"最新版本是什么"
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RouteResult:
    """路由分类结果。"""
    question_type: str          # FACT / RELATION / COMPARE / PROCEDURE / LATEST
    confidence: float           # 0-1
    method: str                 # "rule" / "llm"
    reason: str = ""            # 为什么这么分类（调试用）


# ── 规则模式 ────────────────────────────────────────────────

# 查事实：询问定义、属性、发生位置等
_FACT_PATTERNS = [
    # 直接问是什么
    r"^(什么|啥)是",
    r"^什么是",
    r"是什么意思",
    r"是什么(意思|东西|情况)?\s*[？?]?$",
    r"^(什么叫|啥叫)",
    # 询问属性/特征
    r"(有|是)(什么|啥|哪些)(特点|特征|性格|身份|背景|来历|出身|人|景点|成员)",
    r"(性格|身份|背景|来历|出身|特点|特征)(是|)什么",
    r"是谁\s*[？?]?$",
    r"^(谁|哪个人)",
    r"有哪些(特点|特征|人|景点|成员|角色)",
    # 询问位置/出处
    r"在第几回",
    r"在[哪那]一回",
    r"出自[哪那]",
    r"第几.[出章回]",
    # 名词解释型
    r"^(什么叫|何谓)",
    r"的定义",
    r"的含义",
    # ...的X是什么（末尾型）
    r"的(来历|出身|身份|性格|特点)(是什么|是啥|)",
]

# 查关系：询问人物/实体之间的关联
_RELATION_PATTERNS = [
    r"(谁|什么人|啥).*(关系|亲戚|亲属|关联|联系)",
    r"(关系|亲戚|亲属).*(是|叫)(什么|谁|啥)",
    r"(是|叫).*(什么|谁).*(表妹|表姐|表哥|表弟|堂妹|堂姐|堂哥|堂弟|妹妹|姐姐|哥哥|弟弟|母亲|父亲|女儿|儿子|夫人|妻子|丈夫|丫鬟|主人|师傅|徒弟|师父)",
    r"(表妹|表姐|表哥|表弟|堂妹|堂姐|堂哥|堂弟)是谁",
    r"(.*)和(.*)什么关系",
    r"(.*)是(.*)的(什么|谁)",
    r"(.*)的(父亲|母亲|妻子|丈夫|丫鬟|主人|官职|师傅|师父|徒弟)是",
    r"(.*)和(.*).*(关系|亲戚)",
    r"(.*)与(.*).*(关系|亲戚)",
    r"哪些(材料|文件|证件).*(需要|要求|必备)",
    r"(需要|要求|必备).*(哪些|什么)(材料|文件|证件)",
    r"属于.*(部门|机构|单位)",
]

# 查对比：询问两个或多个实体之间的差异/相似之处
_COMPARE_PATTERNS = [
    r"(区别|差别|差异|不同|不一样|异同)",
    r"(对比|比较|vs\.?|VS\.?)",
    r"(.*)和(.*)(哪个|谁).*(好|厉害|强|聪明|美|帅|高|大|小|多|少)",
    r"(有什么|有哪些|什么)(区别|差别|差异|不同)",
    r"(哪个|谁).*(更|比较)(好|厉害|强|聪明|美|帅)",
    r"(.*)与(.*)(的|之)(对比|比较|区别|差异)",
]

# 查流程：询问操作步骤、办事流程
_PROCEDURE_PATTERNS = [
    r"怎么(办|做|弄|搞|操作|申请|处理|走)",
    r"如何(办理|申请|操作|处理|进行)",
    r"(办理|申请|操作).*流程",
    r"流程.*(是什么|怎么|如何)",
    r"(步骤|过程).*(是什么|怎么|如何|有哪些)",
    r"(第一步|第二步|首先|然后|接着|最后).*做",
    r"需要.*哪些(步骤|手续|环节)",
    r"(手续|环节|步骤).*哪些",
    r"怎么.*(审批|报批|备案|登记)",
    r"办理.*(步骤|手续|流程|方法)",
]

# 查最新：询问更新、变化、版本
_LATEST_PATTERNS = [
    r"(最新|最近|近期|新出|新增|刚出|刚发布)",
    r"(更新|变化|变更|改动|修改|调整).*(什么|哪|怎么|了)",
    r"什么.*(更新|变化|变更|改动|修改|调整)",
    r"(新版|旧版).*(更新|变化|改动|变更)",  # 只匹配询问版本更新，不匹配对比
    r"有.*(更新|变化).*(吗|没|了)",
    r"(什么时候|何时).*(更新|发布|生效|实施)",
]


def _match_patterns(query: str, patterns: list[str]) -> float:
    """计算 query 匹配某组模式的程度，返回 0-1 的置信度。"""
    best = 0.0
    for pat in patterns:
        m = re.search(pat, query)
        if m:
            # 匹配长度越长，置信度越高
            match_len = m.end() - m.start()
            ratio = min(match_len / max(len(query), 1), 1.0)
            best = max(best, 0.6 + 0.4 * ratio)
    return round(best, 2)


def classify_rule(query: str) -> RouteResult | None:
    """规则分类：用正则关键词匹配判断问题类型。

    返回 None 表示规则无法确定（需要走 LLM）。
    """
    # ── 强信号优先检查：某些关键词的出现几乎可以确定问题类型 ──
    # 这些信号强度极高，遇到后直接返回，不再走模糊匹配
    if re.search(r"(最新|最近|近期|新出|新增|刚发布)", query):
        return RouteResult(
            question_type="LATEST",
            confidence=0.95,
            method="rule",
            reason=f"强信号: 最新/最近",
        )
    if re.search(r"(怎么|如何|流程|步骤|手续|办理|申请).{0,8}(办|做|弄|搞|操作|申请|处理|走|是什么)", query):
        return RouteResult(
            question_type="PROCEDURE",
            confidence=0.90,
            method="rule",
            reason=f"强信号: 流程/步骤",
        )

    scores: dict[str, float] = {}
    for ptype, patterns in [
        ("FACT", _FACT_PATTERNS),
        ("RELATION", _RELATION_PATTERNS),
        ("COMPARE", _COMPARE_PATTERNS),
        ("PROCEDURE", _PROCEDURE_PATTERNS),
        ("LATEST", _LATEST_PATTERNS),
    ]:
        s = _match_patterns(query, patterns)
        if s > 0:
            scores[ptype] = s

    if not scores:
        return None

    # 按置信度排序
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    best_type, best_score = ranked[0]

    # 如果最高分不够或与第二名差距太小，规则不可靠
    if best_score < 0.6:
        return None
    if len(ranked) >= 2 and ranked[0][1] - ranked[1][1] < 0.10:
        return None

    return RouteResult(
        question_type=best_type,
        confidence=best_score,
        method="rule",
        reason=f"关键词匹配: {best_type} (score={best_score})",
    )


def classify_llm(query: str) -> RouteResult:
    """LLM 分类：让模型判断问题类型。

    只在规则通道无法确定时调用。
    """
    from llm.base import get_llm

    prompt = f"""你是问题分类器。将用户问题分为以下类型之一：

- FACT: 询问事实、定义、属性、位置/出处（如 "XXX是什么" "XXX在第几回" "XXX的性格"）
- RELATION: 询问人物/实体之间的关系、归属（如 "A和B什么关系" "A属于哪个部门" "需要什么材料"）
- COMPARE: 比较两个或多个实体的异同（如 "A和B有什么区别" "哪个更好"）
- PROCEDURE: 询问操作流程、办事步骤（如 "怎么办理" "申请流程是什么"）
- LATEST: 询问最新的更新、变化、版本（如 "最近有什么变化" "最新版本是什么"）

只输出一个 JSON 对象，格式：{{"type": "FACT|RELATION|COMPARE|PROCEDURE|LATEST", "confidence": 0.0-1.0, "reason": "简短说明"}}

问题：{query}"""

    llm = get_llm()
    try:
        raw = llm.chat([{"role": "user", "content": prompt}])
        # 清理可能的 markdown code fence
        cleaned = raw.strip()
        cleaned = re.sub(r"```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"```", "", cleaned)
        cleaned = cleaned.strip()
        result = json.loads(cleaned)
        return RouteResult(
            question_type=result.get("type", "FACT"),
            confidence=float(result.get("confidence", 0.5)),
            method="llm",
            reason=result.get("reason", ""),
        )
    except Exception:
        # LLM 调用失败，默认走 FACT
        return RouteResult(
            question_type="FACT",
            confidence=0.3,
            method="llm_fallback",
            reason="LLM 分类失败，回退到 FACT",
        )


def classify(query: str, force_llm: bool = False) -> RouteResult:
    """统一分类入口：先走规则，不匹配再走 LLM。

    Args:
        query: 用户问题
        force_llm: 强制走 LLM（评测用）

    Returns:
        RouteResult 包含类型和置信度
    """
    if not force_llm:
        rule_result = classify_rule(query)
        if rule_result is not None:
            return rule_result

    return classify_llm(query)
