"""复核工具的单元与端到端测试。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from review.annotations import Statement, load_statements, validate
from review.criteria import EvidenceError, parse_evidence, parse_scope
from review.engine import evaluate, phenomenon_observations, index_statements
from review.model import Ledger, Note

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT / "data" / "records.json"
ANNOTATIONS = ROOT / "data" / "annotations.json"


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger = Ledger.load(RECORDS)
        cls.statements = load_statements(ANNOTATIONS, cls.ledger)
        cls.result = evaluate(cls.ledger, cls.statements)


class CriteriaParsing(Base):
    def test_scope_parsing(self):
        c1 = parse_scope(self.ledger.claims["C1"].scope, self.ledger)
        self.assertEqual((c1.series, c1.roads, c1.phase, c1.mode),
                         ("岚甲", ("上环",), "afterheat", "auto"))
        c3 = parse_scope(self.ledger.claims["C3"].scope, self.ledger)
        self.assertEqual(c3.roads, ("上环", "低坡"))

    def test_evidence_parsing(self):
        c1 = parse_evidence(self.ledger.claims["C1"].evidence, "较轻", 2)
        self.assertEqual((c1.max_temp_diff, c1.common_speed, c1.min_duration),
                         (2, (12, 24), 7))
        self.assertTrue(c1.require_observed_interval)
        c2 = parse_evidence(self.ledger.claims["C2"].evidence, "较轻", 1)
        self.assertEqual(c2.min_continuous_obs, 8)
        c3 = parse_evidence(self.ledger.claims["C3"].evidence, "未出现", 2)
        self.assertTrue(c3.per_segment and c3.explicit_absence)
        self.assertEqual(c3.min_continuous_interval, 7)

    def test_unknown_clause_is_rejected(self):
        with self.assertRaises(EvidenceError):
            parse_evidence("温差至多2度，随便看看就行。", "较轻", 1)


class CoverageRules(Base):
    def test_driver_full_course_stands_despite_passenger_gap(self):
        # R2：周安全程观察有效；俞礼前半段未观察只影响俞礼自己
        self.assertEqual(self.result.coverages["R2"].status, "full")
        self.assertEqual(self.result.coverages["R2"].full_observers, ("周安",))

    def test_own_gap_retracts_own_full_course_claim(self):
        # R12：周安自报中段未观察，其“整圈”说法被限缩
        cov = self.result.coverages["R12"]
        self.assertEqual(cov.status, "partial")
        self.assertEqual(set(cov.overclaimed), {"A14", "A15"})

    def test_unobserved_run(self):
        self.assertEqual(self.result.coverages["R5"].status, "none")

    def test_post_takeover_jerk_stays_out_of_auto_shiver_counts(self):
        # A2 的“顿”在接管后，不并入颤动类，不进自动模式统计
        by_run = index_statements(self.statements)
        count, _ = phenomenon_observations("R3", by_run)
        self.assertIsNone(count)
        a2 = next(s for s in self.statements if s.id == "A2")
        self.assertTrue(a2.post_takeover)
        self.assertEqual(a2.mode, "manual")


class PairingRules(Base):
    def pair(self, claim_id, new_run, old_run):
        return next(p for p in self.result.pairs[claim_id]
                    if p.new_run == new_run and p.old_run == old_run)

    def test_temp_tolerance(self):
        self.assertFalse(self.pair("C1", "R10", "R8").comparable)  # 温差 3°C
        self.assertTrue(self.pair("C1", "R10", "R9").comparable)   # 温差 1°C

    def test_common_speed_exposure(self):
        self.assertFalse(self.pair("C1", "R7", "R8").comparable)   # 12–23 不达 12–24
        self.assertTrue(self.pair("C1", "R2", "R8").comparable)

    def test_min_duration(self):
        pair = self.pair("C1", "R2", "R5")                          # R5 仅 5 分钟
        self.assertFalse(pair.comparable)

    def test_direct_comparative_out_of_tolerance_is_flagged(self):
        pair = self.pair("C1", "R10", "R8")
        self.assertTrue(pair.direct)
        self.assertEqual(pair.direction, "lighter")
        self.assertFalse(pair.usable)


class ClaimVerdicts(Base):
    def test_c1_not_signable_for_independence(self):
        verdict = self.result.verdicts["C1"]
        self.assertEqual(verdict.status, "不可签")
        self.assertEqual(len(verdict.independent), 1)
        self.assertLess(len(verdict.independent), self.ledger.claims["C1"].required)

    def test_c1_pairing_sensitivity_disclosed(self):
        verdict = self.result.verdicts["C1"]
        self.assertTrue(any("R10" in s for s in verdict.sensitivities))

    def test_c2_signable_only_narrowed(self):
        verdict = self.result.verdicts["C2"]
        self.assertEqual(verdict.status, "窄化可签")
        self.assertIn("已观察区间", verdict.boundary)
        self.assertTrue(any("R12" in g for g in verdict.gaps))

    def test_c3_segmented_outcome(self):
        verdict = self.result.verdicts["C3"]
        self.assertEqual(verdict.status, "不可签")
        segments = {s.road: s for s in verdict.segments}
        self.assertEqual(segments["上环"].status, "被反例否定")
        self.assertEqual({r for r, _ in segments["上环"].counters}, {"R7", "R10"})
        self.assertEqual(segments["低坡"].status, "证据不足")
        # 上环的反例不波及低坡段核定
        self.assertEqual(segments["低坡"].counters, ())


class SignoffAndCopy(Base):
    def test_s1_stays_valid_with_its_boundary(self):
        check = self.result.signoffs["S1"]
        self.assertTrue(check.consistent)
        self.assertEqual(check.status, "维持有效")
        self.assertEqual(check.boundary.basis_pairs, ("R12↔R11",))
        self.assertTrue(check.boundary.observed_bounded)

    def test_s2_stays_pending(self):
        check = self.result.signoffs["S2"]
        self.assertTrue(check.consistent)
        self.assertEqual(check.status, "维持待定")

    def test_copy_verdicts(self):
        self.assertEqual(self.result.copy["K1"].verdict, "需更正")
        self.assertEqual(self.result.copy["K2"].verdict, "需窄化")
        self.assertEqual(self.result.copy["K3"].verdict, "可采用")

    def test_k1_strength_and_counterexample_reasons(self):
        reasons = "；".join(self.result.copy["K1"].reasons)
        self.assertIn("不能互换", reasons)   # 改善≠消失
        self.assertIn("R7", reasons)          # 承诺范围内的反例


class AnnotationIntegrity(Base):
    def test_every_note_is_interpreted_or_a_correction(self):
        covered = ({s.note for s in self.statements}
                   | {n for s in self.statements for n in s.resolved_by})
        self.assertEqual(covered, set(self.ledger.notes))

    def test_comparative_must_bind_target(self):
        bad = Statement(id="X0", note="N1", quote="比它轻", runs=("R10",),
                        coverage="full", mode="auto", phenomenon="连颤",
                        form="comparative", evidence="direct")
        with self.assertRaises(ValueError):
            validate([bad], self.ledger)


class DeltaAfterNewObservation(Base):
    """工程师提交新的对照观察后：可签结论随之更新，
    但别处的局部反例不被新好评抵消。"""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        ledger = Ledger.load(RECORDS)
        notes = dict(ledger.notes)
        notes["N99"] = Note("N99", "俞礼", ("R12",),
                            "补充：中段我盯着，整圈未见连颤。")
        cls.ledger2 = Ledger(ledger.cars, ledger.runs, notes,
                             ledger.claims, ledger.signoffs, ledger.copy)
        extra = Statement(id="X1", note="N99", quote="整圈未见连颤",
                          runs=("R12",), coverage="full", mode="auto",
                          phenomenon="连颤", form="absence", evidence="direct")
        cls.statements2 = cls.statements + [extra]
        cls.result2 = evaluate(cls.ledger2, cls.statements2)

    def test_c2_full_frame_becomes_signable(self):
        self.assertEqual(self.result2.coverages["R12"].status, "full")
        self.assertEqual(self.result2.verdicts["C2"].status, "可签认")

    def test_k1_still_rejected(self):
        # R7/R10 的反例不被低坡的新好评抵消
        self.assertEqual(self.result2.copy["K1"].verdict, "需更正")

    def test_s1_still_valid(self):
        self.assertEqual(self.result2.signoffs["S1"].status, "维持有效")


if __name__ == "__main__":
    unittest.main()
