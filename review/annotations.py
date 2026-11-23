"""原话解读层：复核后的结构化摘记。

解读（哪句话指哪圈、观察覆盖到哪、属于哪种证据等级）是复核员的
确认行为，登记在 data/annotations.json；引擎只机械使用本层结论，
不再回读自然语言。更正类手记（如确认同圈、更正路段、确认“它”
所指）通过 resolved_by 挂到被更正的摘记上，保留完整更正链。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

DIRECT = "direct"    # 直接观察
HEARSAY = "hearsay"  # 转述：仅备案，不作直接证据

ABSENCE = "absence"          # 未出现类说法（只适用于确有经过且能观察的范围）
OCCURRENCE = "occurrence"    # 出现类说法
COMPARATIVE = "comparative"  # 相对说法：必须绑定对照车程（target）
UNOBSERVED = "unobserved"    # 明确未观察：覆盖标记，不是证据

FORMS = {ABSENCE, OCCURRENCE, COMPARATIVE, UNOBSERVED}


@dataclass(frozen=True)
class Statement:
    id: str
    note: str           # 来源手记
    quote: str          # 原话引文
    runs: tuple         # 复核确认归属的车程
    coverage: str       # full / partial:<段> / unobserved:<段> / unknown
    mode: str | None    # 该句所述时刻的模式（可与车次登记不同，如接管后）
    phenomenon: str | None
    form: str
    evidence: str
    count: int | None = None      # occurrence 的次数
    direction: str | None = None  # comparative 的方向（lighter）
    target: tuple = ()            # comparative 绑定的对照车程
    post_takeover: bool = False   # 接管之后的感受
    resolved_by: tuple = ()       # 支持本解读的更正类手记
    remark: str = ""

    @property
    def coverage_kind(self) -> str:
        return self.coverage.split(":", 1)[0]

    @property
    def coverage_detail(self) -> str:
        return self.coverage.split(":", 1)[1] if ":" in self.coverage else ""


def load_statements(path, ledger) -> list:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    statements = [
        Statement(
            id=s["id"], note=s["note"], quote=s["quote"],
            runs=tuple(s.get("runs", ())), coverage=s["coverage"],
            mode=s.get("mode"), phenomenon=s.get("phenomenon"),
            form=s["form"], evidence=s.get("evidence", DIRECT),
            count=s.get("count"), direction=s.get("direction"),
            target=tuple(s.get("target", ())),
            post_takeover=s.get("post_takeover", False),
            resolved_by=tuple(s.get("resolved_by", ())),
            remark=s.get("remark", ""),
        )
        for s in raw["statements"]
    ]
    validate(statements, ledger)
    return statements


def validate(statements, ledger) -> None:
    """解读层完整性：引用存在、相对说法有对照、每条手记都被处理。"""
    problems = []
    ids = set()
    for s in statements:
        if s.id in ids:
            problems.append(f"摘记 id 重复：{s.id}")
        ids.add(s.id)
        if s.note not in ledger.notes:
            problems.append(f"{s.id}：手记 {s.note} 不存在")
        for r in s.runs + s.target:
            if r not in ledger.runs:
                problems.append(f"{s.id}：车程 {r} 不存在")
        for n in s.resolved_by:
            if n not in ledger.notes:
                problems.append(f"{s.id}：更正手记 {n} 不存在")
        if s.form not in FORMS:
            problems.append(f"{s.id}：未知形式 {s.form}")
        if s.form == COMPARATIVE and not s.target:
            problems.append(f"{s.id}：相对说法必须绑定对照车程")
        if s.mode and s.mode not in {"auto", "manual"}:
            problems.append(f"{s.id}：未知模式 {s.mode}")
        for r in s.runs:
            run = ledger.runs.get(r)
            if run and s.mode and s.mode != run.mode:
                problems.append(f"{s.id}：所述模式 {s.mode} 与 {r} 登记 {run.mode} 不一致")
    covered = {s.note for s in statements} | {n for s in statements for n in s.resolved_by}
    for note_id in ledger.notes:
        if note_id not in covered:
            problems.append(f"{note_id}：没有任何解读或更正引用")
    if problems:
        raise ValueError("解读层校验未通过：\n" + "\n".join(problems))
