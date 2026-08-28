"""Eval harness tests: the metric definitions are the product here."""

from __future__ import annotations

from scribe.stages.evaluate import (
    FieldScore,
    pair_id_for_source,
    values_match,
)


class TestPairId:
    def test_amr(self):
        assert pair_id_for_source("/x/AMR_004_HTR.png") == "AMR_004"

    def test_syn(self):
        assert pair_id_for_source("SYN_001.png") == "SYN_001"

    def test_unrelated(self):
        assert pair_id_for_source("random_scan.png") is None


class TestValuesMatch:
    def test_nulls(self):
        assert values_match(None, None)
        assert not values_match("x", None)
        assert not values_match(None, "x")

    def test_string_normalisation(self):
        assert values_match("Dr  Joan Riz", "dr joan riz")
        assert values_match("Patient’s note", "patient's note")
        assert values_match("× 3/7", "x 3/7")

    def test_initials_spacing_and_separators_do_not_count(self):
        assert values_match("E. J", "E.J")
        assert values_match("Miss J. I.", "Miss J.I")
        assert values_match("F.O", "F. O")
        assert values_match("J-D", "J.D")
        # but actual letters still count
        assert not values_match("Emelia Sam", "Emeka Sani")
        assert not values_match("Amike Bello", "Amina Bello")

    def test_numbers(self):
        assert values_match(38.2, 38.2)
        assert values_match(38, 38.0)
        assert not values_match(38.2, 38.3)

    def test_tables(self):
        a = [{"t": 38.2, "p": None}]
        assert values_match(a, [{"t": 38.2, "p": None}])
        assert not values_match(a, [{"t": 38.2, "p": 90}])
        assert not values_match(a, [])          # row count matters

    def test_bool_is_not_number(self):
        assert not values_match(True, 1)


class TestFieldScoreSemantics:
    """Pin the metric definitions so a refactor cannot quietly change them."""

    def test_false_negative_is_unflagged_and_wrong(self):
        s = FieldScore(n=2, correct=1, flagged=0,
                       auto_accepted=2, auto_accepted_correct=1,
                       false_negative_flags=1)
        # 1 of 2 auto-accepted was wrong -> FN rate 50%
        assert s.false_negative_flags / s.auto_accepted == 0.5

    def test_escaped_hallucination_is_a_subset(self):
        s = FieldScore(halluc_opportunities=4, hallucinations=3,
                       hallucinations_escaped=1)
        # 3 inventions, 2 caught by flags, 1 reached the record
        assert s.hallucinations_escaped <= s.hallucinations

    def test_merge_adds_counters(self):
        a = FieldScore(n=1, correct=1)
        b = FieldScore(n=2, correct=0, flagged=2)
        m = a.merged_with(b)
        assert (m.n, m.correct, m.flagged) == (3, 1, 2)
