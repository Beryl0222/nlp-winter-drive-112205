"""规则引擎：覆盖计算、配对可比性、主张核定、签认与文案核对。

引擎不做自然语言理解：原话归属以解读层（annotations）为准，
本模块只机械套用工况框与证据门槛。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .annotations import ABSENCE, COMPARATIVE, DIRECT, OCCURRENCE, UNOBSERVED
from .criteria import CN_NUMERALS, parse_evidence, parse_scope

# 颤动类现象。“顿”不并入：接管后的顿（N1）与转述的顿（N3）
# 均不计入自动模式颤动结论，但保留在案。
SHIVER_CLASS = frozenset({"抖", "连颤"})

PHASE_CN = {"afterheat": "升温后", "warmup": "暖身"}
MODE_CN = {"auto": "自动", "manual": "手控"}


# ---------------------------------------------------------------- 观察覆盖

@dataclass
class Coverage:
    status: str                 # full / partial / none
    gaps: tuple = ()            # 明确未观察段（“观察者：段”）
    overclaimed: tuple = ()     # 被未观察段限缩的“整圈”说法（statement id）
    full_observers: tuple = ()  # 全程观察有效的观察者


def compute_coverage(run_id, ledger, statements) -> Coverage:
    """按观察者分别计算：同一观察者自报未观察段时，其本人的“整圈”
    说法被限缩；另一观察者的全程观察不受牵连。"""
    by_observer = {}
    for s in statements:
        if run_id in s.runs:
            observer = ledger.notes[s.note].observer
            by_observer.setdefault(observer, []).append(s)
    gaps, overclaimed, full_observers = [], [], []
    any_observation = False
    for observer, ss in by_observer.items():
        own_gaps = [s for s in ss if s.form == UNOBSERVED]
        own_full = [s for s in ss
                    if s.coverage_kind == "full" and s.form != UNOBSERVED]
        if own_gaps:
            gaps.extend(f"{observer}：{s.coverage_detail}" for s in own_gaps)
            overclaimed.extend(s.id for s in own_full)
        elif own_full:
            full_observers.append(observer)
        if any(s.form != UNOBSERVED for s in ss):
            any_observation = True
    if full_observers:
        status = "full"
    elif any_observation or gaps:
        status = "partial"
    else:
        status = "none"
    return Coverage(status, tuple(gaps), tuple(overclaimed), tuple(full_observers))


def index_statements(statements) -> dict:
    by_run = {}
    for s in statements:
        for r in s.runs:
            by_run.setdefault(r, []).append(s)
    return by_run


def phenomenon_observations(run_id, by_run, phenomena=SHIVER_CLASS):
    """该车程颤动类的直接观察：(出现次数, 依据 statement id)；
    无直接观察时次数为 None。未出现类说法记 0 次。"""
    stmts = [s for s in by_run.get(run_id, ())
             if s.evidence == DIRECT and s.phenomenon in phenomena
             and s.form in (ABSENCE, OCCURRENCE)]
    if not stmts:
        return None, ()
    count = sum(s.count or 0 for s in stmts if s.form == OCCURRENCE)
    return count, tuple(s.id for s in stmts)


# ---------------------------------------------------------------- 配对

@dataclass
class PairReport:
    new_run: str
    old_run: str
    comparable: bool
    checks: tuple       # 逐项工况核对（含数值）
    direction: str      # lighter / none / counter / unknown
    direct: bool        # 是否有直接比较说法
    basis: tuple        # 依据的 statement id
    unmet: tuple        # 未满足的证据门槛

    @property
    def usable(self):
        return self.comparable and not self.unmet and self.direction == "lighter"


def evaluate_pair(new_run, old_run, criteria, ledger, coverages, by_run, statements):
    checks, unmet = [], []
    comparable = True
    if criteria.max_temp_diff is not None:
        diff = abs(new_run.temp - old_run.temp)
        ok = diff <= criteria.max_temp_diff
        comparable &= ok
        checks.append(f"起始温差 {diff}°C（容差 ≤{criteria.max_temp_diff}°C）"
                      f"{'✓' if ok else '✗ 超容差'}")
    if criteria.common_speed is not None:
        lo = max(new_run.speed[0], old_run.speed[0])
        hi = min(new_run.speed[1], old_run.speed[1])
        need_lo, need_hi = criteria.common_speed
        ok = lo <= need_lo and hi >= need_hi
        comparable &= ok
        checks.append(f"共同速度暴露 {lo}–{hi} km/h（须覆盖 {need_lo}–{need_hi}）"
                      f"{'✓' if ok else '✗ 不足'}")
    if criteria.min_duration is not None:
        ok = (new_run.duration >= criteria.min_duration
              and old_run.duration >= criteria.min_duration)
        comparable &= ok
        checks.append(f"运行时长 {new_run.duration}/{old_run.duration} 分钟"
                      f"（各 ≥{criteria.min_duration}）{'✓' if ok else '✗'}")
    if criteria.require_observed_interval:
        for run in (new_run, old_run):
            count, _ = phenomenon_observations(run.id, by_run)
            if count is None:
                unmet.append(f"{run.id} 无直接现象观察，不能确认覆盖比较区间")
    if criteria.min_continuous_obs is not None:
        for run in (new_run, old_run):
            cov = coverages[run.id]
            if cov.status == "full" and run.duration >= criteria.min_continuous_obs:
                checks.append(f"{run.id} 连续观察 {run.duration} 分钟 ✓")
            else:
                detail = "；".join(cov.gaps) or "无全程观察"
                unmet.append(f"{run.id} 连续观察 ≥{criteria.min_continuous_obs} 分钟"
                             f"未确认（{detail}）")
    direct_stmts = [s for s in statements
                    if s.form == COMPARATIVE and s.evidence == DIRECT
                    and new_run.id in s.runs and old_run.id in s.target]
    if direct_stmts:
        direction = "lighter" if all(s.direction == "lighter" for s in direct_stmts) else "unknown"
        direct = True
        basis = tuple(s.id for s in direct_stmts)
    else:
        direct = False
        cn, bn = phenomenon_observations(new_run.id, by_run)
        co, bo = phenomenon_observations(old_run.id, by_run)
        basis = tuple(bn) + tuple(bo)
        if cn is None or co is None:
            direction = "unknown"
        elif cn < co:
            direction = "lighter"
        elif cn == co:
            direction = "none"
        else:
            direction = "counter"
    return PairReport(new_run.id, old_run.id, comparable, tuple(checks),
                      direction, direct, basis, tuple(unmet))


def max_independent(pairs):
    """最大独立配对集：同一说法内，同一车程（任一侧）不得配给两次。"""
    best, current, used = [], [], set()

    def backtrack(i):
        nonlocal best
        if len(current) + (len(pairs) - i) <= len(best):
            return
        if i == len(pairs):
            if len(current) > len(best):
                best = list(current)
            return
        p = pairs[i]
        if p.new_run not in used and p.old_run not in used:
            used.update((p.new_run, p.old_run))
            current.append(p)
            backtrack(i + 1)
            current.pop()
            used.discard(p.new_run)
            used.discard(p.old_run)
        backtrack(i + 1)

    backtrack(0)
    return best


# ---------------------------------------------------------------- 主张核定

@dataclass
class SegmentVerdict:
    road: str
    status: str     # 满足 / 证据不足 / 被反例否定
    valid: tuple    # 有效全程未出现观察（run id）
    counters: tuple  # 反例（(run, (statement ids))）
    bounded: tuple  # 有界未出现（(run, 说明)）
    detail: str


@dataclass
class ClaimVerdict:
    claim_id: str
    status: str     # 可签认 / 窄化可签 / 不可签
    summary: str
    pairs: tuple = ()
    independent: tuple = ()
    counters: tuple = ()
    disclosures: tuple = ()
    sensitivities: tuple = ()
    gaps: tuple = ()
    boundary: str | None = None
    segments: tuple = ()


def scope_runs(ledger, scope, build):
    runs = [r for r in ledger.runs.values()
            if ledger.cars[r.car].series == scope.series
            and ledger.cars[r.car].build == build
            and r.road in scope.roads and r.phase == scope.phase
            and r.mode == scope.mode]
    return sorted(runs, key=lambda r: r.started)


def _car_label(ledger, run_id):
    run = ledger.runs[run_id]
    car = ledger.cars[run.car]
    return f"{run.car}（{car.series}{car.build}）"


def _unsupported_new_runs(pairs, new_runs, direction_cn):
    """说明每个未贡献支持配对的新版车程卡在哪里（供补充观察时对照）。"""
    lines = []
    for n in new_runs:
        mine = [p for p in pairs if p.new_run == n.id]
        if any(p.usable for p in mine):
            continue
        whys = []
        for p in mine:
            if not p.comparable:
                failed = "；".join(c for c in p.checks if "✗" in c)
                whys.append(f"对 {p.old_run} 不可比（{failed}）")
            elif p.direction != "lighter":
                whys.append(f"对 {p.old_run} {direction_cn[p.direction]}")
            elif p.unmet:
                whys.append(f"对 {p.old_run} 门槛未达（{'；'.join(p.unmet)}）")
        if whys:
            lines.append(f"{n.id} 未贡献支持配对：" + "；".join(whys))
    return lines


def eval_improvement(claim, scope, criteria, ledger, coverages, by_run, statements):
    new_runs = scope_runs(ledger, scope, "新版")
    old_runs = scope_runs(ledger, scope, "旧版")
    pairs = tuple(evaluate_pair(n, o, criteria, ledger, coverages, by_run, statements)
                  for n in new_runs for o in old_runs)
    solid = [p for p in pairs if p.comparable and p.direction == "lighter" and not p.unmet]
    bounded = [p for p in pairs if p.comparable and p.direction == "lighter" and p.unmet]
    independent = max_independent(solid)

    counters, disclosures, sensitivities, gaps = [], [], [], []
    for p in pairs:
        if p.comparable and p.direction == "counter":
            counters.append(f"{p.new_run}↔{p.old_run}：可比范围内新版反而更重")
        if p.direct and not p.comparable:
            disclosures.append(
                f"{p.new_run}↔{p.old_run}：唯一直接比较说法（{', '.join(p.basis)}）"
                f"落在工况容差之外，不能采用")
        elif p.comparable and p.direction == "none":
            disclosures.append(f"{p.new_run}↔{p.old_run}：可比范围内未见差异")
    # 配对敏感性：同一新版车程在合理配对选择下给出不同结论
    # （合理选择＝可比配对，或虽超容差但存在直接比较说法的配对）
    direction_cn = {"lighter": "较轻", "none": "无差异",
                    "counter": "反向", "unknown": "无观察"}
    for n in new_runs:
        mine = [p for p in pairs
                if p.new_run == n.id and (p.comparable or p.direct)]
        def outcome(p):
            return direction_cn[p.direction] if p.comparable else "直接比较超容差"
        outcomes = {outcome(p) for p in mine}
        if len(outcomes) > 1:
            detail = "；".join(f"对 {p.old_run}：{outcome(p)}" for p in mine)
            sensitivities.append(f"{n.id} 的结论随旧侧配对选择而改变（{detail}）")
    # 新版侧出现记录：不直接否定“较轻”，但阻断同工况“未出现”类结论
    for n in new_runs:
        count, basis = phenomenon_observations(n.id, by_run)
        if count:
            disclosures.append(
                f"{n.id} 新版侧有出现记录（{', '.join(basis)}）：与“较轻”不直接冲突，"
                f"但阻断同工况“未出现”类结论")

    boundary = None
    if len(independent) >= claim.required:
        status = "可签认"
        summary = f"独立配对 {len(independent)} 对，达到下限 {claim.required}。"
    elif solid:
        status = "不可签"
        summary = (f"有支持配对但独立次数不足：最多 {len(independent)} 对 "
                   f"< 要求 {claim.required}。")
        gaps.append(f"独立配对最多 {len(independent)} 对，低于要求的 {claim.required} 次；"
                    f"同一车程不得配给两次")
        gaps.extend(_unsupported_new_runs(pairs, new_runs, direction_cn))
    elif bounded and len(max_independent(bounded)) >= claim.required:
        status = "窄化可签"
        used = max_independent(bounded)
        pair = used[0]
        new_car, old_car = ledger.runs[pair.new_run].car, ledger.runs[pair.old_run].car
        boundary = (f"窄化边界：{'、'.join(scope.roads)}{PHASE_CN[scope.phase]}"
                    f"{MODE_CN[scope.mode]}、已观察区间内，{new_car} 较 {old_car} 轻"
                    f"（配对 {pair.new_run}↔{pair.old_run}，依据 {', '.join(pair.basis)}）")
        summary = "全框未达（观察覆盖缺口），窄化结论可签。"
        gaps.extend(f"{p.new_run}↔{p.old_run}：" + "；".join(p.unmet) for p in used)
    else:
        status = "不可签"
        summary = "可比范围内没有支持“较轻”的配对。"
    return ClaimVerdict(claim.id, status, summary, pairs=pairs,
                        independent=tuple(independent), counters=tuple(counters),
                        disclosures=tuple(disclosures),
                        sensitivities=tuple(sensitivities), gaps=tuple(gaps),
                        boundary=boundary), pairs


def eval_absence(claim, scope, criteria, ledger, coverages, by_run):
    segments = []
    for road in scope.roads:
        seg_scope = type(scope)(scope.series, (road,), scope.phase, scope.mode)
        runs = scope_runs(ledger, seg_scope, "新版")
        valid, counters, bounded = [], [], []
        for run in runs:
            stmts = by_run.get(run.id, ())
            occurrences = [s for s in stmts if s.form == OCCURRENCE
                           and s.evidence == DIRECT and s.phenomenon in SHIVER_CLASS]
            absences = [s for s in stmts if s.form == ABSENCE
                        and s.evidence == DIRECT and s.phenomenon in SHIVER_CLASS]
            cov = coverages[run.id]
            if occurrences:
                counters.append((run.id, tuple(s.id for s in occurrences)))
            elif absences:
                need = criteria.min_continuous_interval or 0
                if cov.status == "full" and run.duration >= need:
                    valid.append(run.id)
                else:
                    reason = "；".join(cov.gaps) or "连续区间未确认"
                    bounded.append((run.id, f"覆盖不足（{reason}），仅已观察区间成立"))
        if counters:
            seg_status = "被反例否定"
        elif len(valid) >= claim.required:
            seg_status = "满足"
        else:
            seg_status = "证据不足"
        detail = (f"有效全程未出现 {len(valid)} 次（要求 ≥{claim.required}），"
                  f"反例 {len(counters)} 起，有界未出现 {len(bounded)} 起")
        segments.append(SegmentVerdict(road, seg_status, tuple(valid),
                                       tuple(counters), tuple(bounded), detail))
    if any(s.status == "被反例否定" for s in segments):
        status = "不可签"
    elif all(s.status == "满足" for s in segments):
        status = "可签认"
    else:
        status = "不可签"
    summary = "；".join(f"{s.road}段{s.status}（{s.detail}）" for s in segments)
    gaps = []
    for s in segments:
        if s.status == "证据不足":
            gaps.append(f"{s.road}段：有效全程未出现观察 {len(s.valid)} 次 "
                        f"< 要求 {claim.required} 次")
        for run, why in s.bounded:
            gaps.append(f"{s.road}段 {run}：{why}")
    return ClaimVerdict(claim.id, status, summary, segments=tuple(segments),
                        gaps=tuple(gaps))


# ---------------------------------------------------------------- 签认复核

@dataclass
class SignedBoundary:
    strength: str         # 改善 / 消失
    roads: tuple
    phase: str | None
    mode: str | None
    new_car: str | None
    old_car: str | None
    speed: tuple | None
    observed_bounded: bool
    basis_pairs: tuple
    basis_statements: tuple


@dataclass
class SignoffCheck:
    signoff_id: str
    claim_id: str
    consistent: bool
    status: str           # 维持有效 / 维持待定 / 与证据不一致
    detail: tuple
    boundary: SignedBoundary | None


def validate_signoff(signoff, ledger, verdicts, pairs_by_claim) -> SignoffCheck:
    text = signoff.text
    verdict = verdicts[signoff.claim]
    if "留待确认" in text or "待确认" in text:
        consistent = verdict.status == "不可签"
        status = "维持待定" if consistent else "与证据不一致：主张已达可签，宜复核"
        return SignoffCheck(signoff.id, signoff.claim, consistent, status,
                            (f"签认暂缓；引擎核定：{verdict.summary}",), None)
    # 已签：从原话提取边界要素
    cars = []
    for token in re.findall(r"([一二三四五六七八九十\d])号", text):
        n = CN_NUMERALS.get(token, int(token) if token.isdigit() else None)
        if n is not None and f"V{n}" in ledger.cars:
            cars.append(f"V{n}")
    roads = tuple(r for r in sorted(ledger.roads()) if r in text)
    phase = "afterheat" if "升温后" in text else None
    mode = "auto" if "自动" in text else None
    observed_bounded = "已观察" in text
    strength = "消失" if re.search(r"不再|未出现|没有", text) else "改善"
    m = re.search(r"(\d+)–(\d+)\s*km/h", text)
    speed = (int(m[1]), int(m[2])) if m else None
    new_car = next((c for c in cars if ledger.cars[c].build == "新版"), None)
    old_car = next((c for c in cars if ledger.cars[c].build == "旧版"), None)

    matched = []
    for p in pairs_by_claim.get(signoff.claim, ()):
        if not (p.comparable and p.direction == "lighter"):
            continue
        pn, po = ledger.runs[p.new_run], ledger.runs[p.old_run]
        if new_car and pn.car != new_car:
            continue
        if old_car and po.car != old_car:
            continue
        if roads and pn.road not in roads:
            continue
        matched.append(p)
    if not matched:
        return SignoffCheck(signoff.id, signoff.claim, False,
                            "与证据不一致：无相符的支撑配对",
                            (f"签认提到的车辆/路段找不到可比且方向为“较轻”的配对。",),
                            None)
    has_gap = any(p.unmet for p in matched)
    if has_gap and not observed_bounded:
        return SignoffCheck(signoff.id, signoff.claim, False,
                            "与证据不一致：签认未标明观察边界",
                            ("支撑配对存在观察覆盖缺口，签认原话未作限缩。",), None)
    basis_statements = tuple(s for p in matched for s in p.basis)
    boundary = SignedBoundary(strength, roads, phase, mode, new_car, old_car,
                              speed, observed_bounded,
                              tuple(f"{p.new_run}↔{p.old_run}" for p in matched),
                              basis_statements)
    detail = [f"支撑配对 {b}" for b in boundary.basis_pairs]
    if observed_bounded and has_gap:
        detail.append("签认已标明“已观察”边界，与配对覆盖缺口一致")
    return SignoffCheck(signoff.id, signoff.claim, True, "维持有效",
                        tuple(detail), boundary)


# ---------------------------------------------------------------- 文案核对

@dataclass
class CopyCheck:
    copy_id: str
    state: str
    verdict: str    # 可采用 / 需窄化 / 需更正
    reasons: tuple
    caveats: tuple


def check_copy(item, ledger, signoff_checks, verdicts) -> CopyCheck:
    text = item.text
    strength = "消失" if re.search(r"不再|未有|没有|并无", text) else "改善"
    roads = tuple(r for r in ("上环", "低坡") if r in text)
    phase = "afterheat" if "升温后" in text else None
    mode = "auto" if "自动" in text else None
    reasons, caveats = [], []
    usable = [s for s in (signoff_checks.get(r) for r in item.refs)
              if s and s.consistent and s.boundary]
    claimed_roads = roads or ("上环", "低坡")

    if strength == "消失" and not any(s.boundary.strength == "消失" for s in usable):
        reasons.append("用词强度为“消失”类，所引签认均为“改善”类；"
                       "两者证据门槛不同，不能互换")
    # 覆盖判断须强度匹配：“消失”类承诺只能用“消失”类签认覆盖
    def covers(boundary):
        return strength == "改善" or boundary.strength == "消失"
    uncovered = []
    for road in claimed_roads:
        if not any(road in s.boundary.roads and covers(s.boundary)
                   and (phase is None or s.boundary.phase == phase)
                   and (mode is None or s.boundary.mode == mode)
                   for s in usable):
            uncovered.append(road)
    if uncovered:
        reasons.append("以下路段无签认覆盖：" + "、".join(uncovered))
    if not roads and phase is None and mode is None:
        reasons.append("承诺未限定路段/阶段/模式（读作寒区全程），超出任何已签边界")

    counters = []
    for v in verdicts.values():
        for seg in v.segments:
            if seg.road in claimed_roads:
                for run, basis in seg.counters:
                    counters.append(f"{run}（{', '.join(basis)}）")
    if counters:
        reasons.append("承诺范围内存在反例：" + "、".join(counters))

    if "旧版" in text:
        for s in usable:
            if s.boundary.old_car:
                caveats.append(
                    f"比较对象以已签配对（{s.boundary.old_car}）为限；"
                    f"泛指“旧版”需补充与其他旧版车的配对观察")
    if any(s.boundary.observed_bounded for s in usable):
        caveats.append("结论限已观察区间，未观察段不得计入")

    if strength == "消失" and reasons or (counters and item.state == "公开"):
        verdict = "需更正"
    elif reasons:
        verdict = "需窄化"
    else:
        verdict = "可采用"
    return CopyCheck(item.id, item.state, verdict, tuple(reasons), tuple(caveats))


# ---------------------------------------------------------------- 总装

@dataclass
class Result:
    coverages: dict
    scopes: dict
    criteria: dict
    verdicts: dict
    pairs: dict
    signoffs: dict
    copy: dict


def evaluate(ledger, statements) -> Result:
    by_run = index_statements(statements)
    coverages = {r.id: compute_coverage(r.id, ledger, statements)
                 for r in ledger.runs.values()}
    verdicts, pairs_map, scopes, criterias = {}, {}, {}, {}
    for claim in ledger.claims.values():
        scope = parse_scope(claim.scope, ledger)
        criteria = parse_evidence(claim.evidence, claim.type, claim.required)
        scopes[claim.id], criterias[claim.id] = scope, criteria
        if claim.type == "较轻":
            verdict, pairs = eval_improvement(
                claim, scope, criteria, ledger, coverages, by_run, statements)
            pairs_map[claim.id] = pairs
        elif claim.type == "未出现":
            verdict = eval_absence(claim, scope, criteria, ledger, coverages, by_run)
            pairs_map[claim.id] = ()
        else:
            raise ValueError(f"未知主张类型：{claim.type}")
        verdicts[claim.id] = verdict
    signoffs = {s.id: validate_signoff(s, ledger, verdicts, pairs_map)
                for s in ledger.signoffs.values()}
    copy = {k.id: check_copy(k, ledger, signoffs, verdicts)
            for k in ledger.copy.values()}
    return Result(coverages, scopes, criterias, verdicts, pairs_map, signoffs, copy)
