"""把 claims 的 scope 与 evidence 原话解析为结构化工况框与证据门槛。

解析是严格的：无法识别的分句会报错并列出原文，由复核员扩展规则，
而不是默默放过。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

PHASE_WORDS = (("升温后", "afterheat"), ("暖身", "warmup"))
MODE_WORDS = (("自动模式", "auto"), ("手控模式", "manual"),
              ("手控", "manual"), ("手动", "manual"), ("自动", "auto"))

CN_NUMERALS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
               "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


class ScopeError(ValueError):
    pass


class EvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class Scope:
    series: str
    roads: tuple
    phase: str
    mode: str


@dataclass(frozen=True)
class Criteria:
    pairing: str | None = None              # new_old：新旧实测配对
    max_temp_diff: int | None = None        # 起始温度差上限（°C）
    common_speed: tuple | None = None       # 共同速度暴露下限（km/h）
    min_duration: int | None = None         # 每个运行最短时长（分钟）
    require_observed_interval: bool = False  # 观察须覆盖比较区间
    min_continuous_obs: int | None = None   # 每侧连续观察（分钟）
    min_continuous_interval: int | None = None  # 连续区间（分钟）
    per_segment: bool = False               # 分路段核定
    new_full_course: bool = False           # 新版全程独立观察
    explicit_absence: bool = False          # 需明确未出现


def parse_scope(text, ledger) -> Scope:
    rest = text
    series = next((s for s in sorted(ledger.series(), key=len, reverse=True)
                   if rest.startswith(s)), None)
    if series is None:
        raise ScopeError(f"工况框未识别车系：{text}")
    rest = rest[len(series):]
    mode = None
    for word, code in MODE_WORDS:
        if rest.endswith(word):
            mode, rest = code, rest[: -len(word)]
            break
    phase = None
    for word, code in PHASE_WORDS:
        if rest.endswith(word):
            phase, rest = code, rest[: -len(word)]
            break
    if mode is None or phase is None:
        raise ScopeError(f"工况框未识别阶段或模式：{text}")
    roads = tuple(rest.split("及")) if rest else ()
    if not roads or any(r not in ledger.roads() for r in roads):
        raise ScopeError(f"工况框未识别路段：{text}")
    return Scope(series, roads, phase, mode)


def parse_evidence(text, claim_type, required) -> Criteria:
    kwargs = {}
    for clause in re.split(r"[，。]", text):
        clause = clause.strip()
        if not clause:
            continue
        if clause == "新旧实测配对":
            kwargs["pairing"] = "new_old"
        elif m := re.fullmatch(r"速度范围至少有(\d+)至(\d+)\s*km/h的共同暴露", clause):
            kwargs["common_speed"] = (int(m[1]), int(m[2]))
        elif m := re.fullmatch(r"速度(\d+)至(\d+)\s*km/h", clause):
            kwargs["common_speed"] = (int(m[1]), int(m[2]))
        elif m := re.fullmatch(r"(?:起始温度差|温差)至多(\d+)度", clause):
            kwargs["max_temp_diff"] = int(m[1])
        elif m := re.fullmatch(r"每个运行至少(\d+)分钟且观察覆盖其比较区间", clause):
            kwargs["min_duration"] = int(m[1])
            kwargs["require_observed_interval"] = True
        elif m := re.fullmatch(r"每侧连续观察至少(\d+)分钟", clause):
            kwargs["min_continuous_obs"] = int(m[1])
        elif m := re.fullmatch(r"分路段至少([一二两三四五六七八九十])次新版全程独立观察", clause):
            kwargs["per_segment"] = True
            kwargs["new_full_course"] = True
            count = CN_NUMERALS[m[1]]
            if count != required:
                raise EvidenceError(
                    f"分句“{clause}”的次数 {count} 与 required={required} 不一致")
        elif m := re.fullmatch(r"连续区间至少(\d+)分钟", clause):
            kwargs["min_continuous_interval"] = int(m[1])
        elif clause == "需明确未出现":
            kwargs["explicit_absence"] = True
        else:
            raise EvidenceError(f"无法解析证据分句：{clause!r}（{text}）")
    return Criteria(**kwargs)
