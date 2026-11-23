"""把引擎核定结果渲染为复核报告（中文文本）。"""
from __future__ import annotations

from .annotations import ABSENCE, COMPARATIVE, OCCURRENCE, UNOBSERVED
from .engine import MODE_CN, PHASE_CN

FORM_CN = {ABSENCE: "未出现", OCCURRENCE: "出现", COMPARATIVE: "相对说法",
           UNOBSERVED: "未观察"}
EVIDENCE_CN = {"direct": "直接观察", "hearsay": "转述"}
DIRECTION_CN = {"lighter": "较轻", "none": "无差异", "counter": "反向",
                "unknown": "无观察"}


def _note_sort(note_id):
    return int("".join(ch for ch in note_id if ch.isdigit()))


def _run_label(ledger, run_id):
    r = ledger.runs[run_id]
    car = ledger.cars[r.car]
    return (f"{run_id}（{car.series}{car.build}·{r.road}·{PHASE_CN[r.phase]}·"
            f"{MODE_CN[r.mode]}·{r.temp}°C·{r.speed[0]}–{r.speed[1]} km/h·"
            f"{r.duration} 分钟）")


def render(ledger, statements, result) -> str:
    by_id = {s.id: s for s in statements}
    out = []
    add = out.append

    add("寒区文字试车记录复核报告")
    add("=" * 30)
    add(f"数据：{len(ledger.cars)} 车 / {len(ledger.runs)} 段车程 / "
        f"{len(ledger.notes)} 条手记 / {len(ledger.claims)} 项主张 / "
        f"{len(ledger.signoffs)} 项签认 / {len(ledger.copy)} 段文案")
    add(f"解读层：{len(statements)} 条结构化摘记")
    add("现象归类：颤动类＝{抖、连颤}；“顿”单列，不并入颤动类结论。")
    add("证据分级：直接观察可用；转述仅备案；明确未观察不计入覆盖；"
        "接管后手感归入手控工况。")
    add("")

    # 一、原话解读
    add("一、原话解读与归属")
    add("-" * 30)
    stmts_by_note = {}
    for s in statements:
        stmts_by_note.setdefault(s.note, []).append(s)
    corrections_for = {}
    for s in statements:
        for n in s.resolved_by:
            corrections_for.setdefault(n, []).append(s.id)
    for note_id in sorted(ledger.notes, key=_note_sort):
        note = ledger.notes[note_id]
        add(f"{note_id}（{note.observer}，登记范围 {'/'.join(note.run_hint)}）："
            f"「{note.text}」")
        mine = stmts_by_note.get(note_id, [])
        for s in mine:
            add("  " + _statement_line(ledger, s))
        if not mine and note_id in corrections_for:
            add(f"  更正类手记：作用于 {', '.join(corrections_for[note_id])}，"
                f"不产生独立观察。")
        add("")

    # 二、主张核定
    add("二、主张核定")
    add("-" * 30)
    for claim_id in sorted(ledger.claims, key=_note_sort):
        claim = ledger.claims[claim_id]
        verdict = result.verdicts[claim_id]
        add(f"{claim_id} {claim.scope}·{claim.type}"
            f"（独立证据下限 {claim.required}）→ {verdict.status}")
        if not verdict.segments:
            add(f"  {verdict.summary}")
        if verdict.pairs:
            add("  配对核对：")
            for p in verdict.pairs:
                direction = DIRECTION_CN[p.direction]
                if p.direct:
                    direction += "（直接比较）"
                elif p.direction == "lighter":
                    direction += "（配对导出）"
                head = f"    {p.new_run}↔{p.old_run}  {direction}  "
                head += "可比" if p.comparable else "不可比"
                if p.unmet:
                    head += "  门槛未达"
                add(head)
                for c in p.checks:
                    add(f"      {c}")
                for u in p.unmet:
                    add(f"      缺口：{u}")
        if verdict.independent:
            used = "、".join(f"{p.new_run}↔{p.old_run}" for p in verdict.independent)
            add(f"  计入的独立配对：{used}")
        for line in verdict.counters:
            add(f"  反证：{line}")
        for line in verdict.disclosures:
            add(f"  披露：{line}")
        for line in verdict.sensitivities:
            add(f"  配对敏感性：{line}")
        for seg in verdict.segments:
            add(f"  {seg.road}段：{seg.status}（{seg.detail}）")
            for run, basis in seg.counters:
                quotes = "；".join(f"{b}「{by_id[b].quote}」" for b in basis)
                add(f"    反例 {run}：{quotes}")
            for run, why in seg.bounded:
                add(f"    有界未出现 {run}：{why}")
        if verdict.boundary:
            add(f"  {verdict.boundary}")
        for line in verdict.gaps:
            add(f"  缺口：{line}")
        add("")

    # 三、签认复核
    add("三、已签认复核")
    add("-" * 30)
    for sid in sorted(ledger.signoffs, key=_note_sort):
        signoff = ledger.signoffs[sid]
        check = result.signoffs[sid]
        add(f"{sid}（{signoff.claim}，{signoff.author}）「{signoff.text}」")
        add(f"  → {check.status}")
        for d in check.detail:
            add(f"  {d}")
        if check.boundary:
            b = check.boundary
            add(f"  签认边界：{'、'.join(b.roads) or '未限定'}·"
                f"{PHASE_CN.get(b.phase, '未限定')}·{MODE_CN.get(b.mode, '未限定')}·"
                f"{b.new_car} 对 {b.old_car}·强度 {b.strength}"
                + (f"·{b.speed[0]}–{b.speed[1]} km/h" if b.speed else "")
                + ("·限已观察区间" if b.observed_bounded else ""))
        add("")

    # 四、文案核对
    add("四、面向车主文字核对")
    add("-" * 30)
    for kid in sorted(ledger.copy, key=_note_sort):
        item = ledger.copy[kid]
        check = result.copy[kid]
        add(f"{kid}（{item.state}，引用 {'/'.join(item.refs)}）「{item.text}」")
        add(f"  → {check.verdict}")
        for r in check.reasons:
            add(f"  理由：{r}")
        for c in check.caveats:
            add(f"  附注：{c}")
        add("")

    # 五、可追溯明细
    add("五、可追溯明细")
    add("-" * 30)
    add("已签说法 → 车程 / 配对工况 / 原话：")
    for sid in sorted(ledger.signoffs, key=_note_sort):
        check = result.signoffs[sid]
        if not (check.consistent and check.boundary):
            continue
        b = check.boundary
        for pair in b.basis_pairs:
            new_run, old_run = pair.split("↔")
            add(f"  {sid} 配对 {pair}：")
            add(f"    新侧 {_run_label(ledger, new_run)}")
            add(f"    旧侧 {_run_label(ledger, old_run)}")
        for stmt_id in b.basis_statements:
            s = by_id[stmt_id]
            add(f"    原话 {stmt_id}（{s.note}，{ledger.notes[s.note].observer}）："
                f"「{s.quote}」")
    add("")
    add("被挡住的更广主张 → 证据缺口：")
    for claim_id in sorted(ledger.claims, key=_note_sort):
        verdict = result.verdicts[claim_id]
        if verdict.status == "可签认":
            continue
        add(f"  {claim_id}（{ledger.claims[claim_id].scope}·"
            f"{ledger.claims[claim_id].type}）：{verdict.status}")
        for line in verdict.gaps:
            add(f"    {line}")
    return "\n".join(out)


def _statement_line(ledger, s) -> str:
    parts = [s.id]
    if s.runs:
        parts.append("→ " + "、".join(s.runs))
    if s.form == UNOBSERVED:
        parts.append(f"{s.coverage_detail}未观察〔覆盖标记〕")
    elif s.form == COMPARATIVE:
        parts.append(f"比 {'、'.join(s.target)} 轻〔{EVIDENCE_CN[s.evidence]}〕")
    else:
        coverage = {"full": "全程", "partial": s.coverage_detail,
                    "unknown": "范围不明"}.get(s.coverage_kind, s.coverage)
        desc = f"{coverage}·{s.phenomenon}·{FORM_CN[s.form]}"
        if s.count:
            desc += f"×{s.count}"
        parts.append(f"{desc}〔{EVIDENCE_CN[s.evidence]}〕")
    if s.post_takeover:
        parts.append("（接管后，归手控工况）")
    if s.mode and s.runs:
        run = ledger.runs[s.runs[0]]
        parts.append(f"（{run.road}·{PHASE_CN[run.phase]}·{MODE_CN[s.mode]}）")
    if s.remark:
        parts.append(f"——{s.remark}")
    return " ".join(parts)
