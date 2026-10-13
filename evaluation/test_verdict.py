"""Check data-derived benchmark verdicts and feasible-front hypervolume reporting."""

from __future__ import annotations

from evaluation.q_benchmark import (
    _recommendation,
    _summary_table,
    verdict_from_headline,
)


def _row(method: str, hv: float, violations: int = 0, guaranteed: str = "1") -> dict:
    return {
        "phase": "main",
        "envelope": "env_x",
        "method": method,
        "hypervolume": str(hv),
        "violation_count": str(violations),
        "runtime_ms": "100.0",
        "guaranteed": guaranteed,
    }


def _headline_entry(method: str, hv: float, violation_rate: float) -> dict:
    return {
        "method": method,
        "guarantee": "yes" if violation_rate == 0.0 else "no",
        "runs": 5,
        "mean_hv": hv,
        "hv_std": 0.0,
        "violation_rate": violation_rate,
        "mean_runtime_ms": 100.0,
    }


def test_summary_table_includes_every_method_in_the_artefact():
    rows = [
        _row("nsga2", 0.5220),
        _row("sms", 0.6459),
        _row("moead", 0.0235),
        _row("ga", 0.3715, guaranteed="0"),
        _row("greedy", 0.1700, guaranteed="0"),
        _row("random", 0.2367, guaranteed="0"),
    ]
    table = _summary_table(rows)
    assert [m["method"] for m in table] == ["ga", "greedy", "moead", "nsga2",
                                            "random", "sms"]
    by_method = {m["method"]: m for m in table}
    assert by_method["sms"]["mean_hv"] == 0.6459
    assert by_method["ga"]["guarantee"] == "no"
    assert by_method["nsga2"]["guarantee"] == "yes"


def test_verdict_names_actual_hv_winner_not_nsga2():
    headline = [
        _headline_entry("nsga2", 0.5220, 0.0),
        _headline_entry("age", 0.5944, 0.0),
        _headline_entry("sms", 0.6459, 0.0),
        _headline_entry("ga", 0.3715, 0.0),
    ]
    verdict, note = verdict_from_headline(headline)
    assert verdict == "PASS"
    # sms has the higher HV — the note must name it, not NSGA-II
    assert "sms leads the benchmark on mean hypervolume" in note
    assert "0.6459" in note
    assert "nsga2" not in note.split(".")[0]
    assert "record search counts" in note


def test_verdict_fails_when_hv_winner_violates_constraints():
    headline = [
        _headline_entry("nsga2", 0.5220, 0.0),
        _headline_entry("sms-raw", 0.7000, 0.45),
    ]
    verdict, note = verdict_from_headline(headline)
    assert verdict == "FAIL"
    assert "sms-raw leads the benchmark on mean hypervolume" in note


def test_summary_table_violation_rate_is_exact_not_rounded():
    """One violation in 2001 runs must fail even though its rounded rate is zero."""
    rows = [_row("tiny", 0.5, violations=0) for _ in range(2000)]
    rows.append(_row("tiny", 0.5, violations=1))
    table = _summary_table(rows)
    tiny = table[0]
    assert tiny["runs"] == 2001
    assert tiny["violation_rate"] != 0.0
    assert tiny["violation_rate"] == 1 / 2001

    # decision path: a nonzero exact rate must FAIL even though a rounded
    # presentation would print 0%; the note keeps visible precision
    verdict, note = verdict_from_headline(table)
    assert verdict == "FAIL"
    assert "0.050% hard-constraint violation rate" in note

    # zero violations stays an exact 0.0 and PASSes
    clean_rows = [_row("clean", 0.9, violations=0) for _ in range(5)]
    verdict, _note = verdict_from_headline(_summary_table(clean_rows))
    assert verdict == "PASS"


def test_verdict_handles_empty_headline():
    verdict, note = verdict_from_headline([])
    assert verdict == "FAIL"
    assert "No main-phase benchmark rows" in note


def test_recommendation_does_not_claim_infeasible_members_inflate_hv():
    recommendation = _recommendation()
    assert "inflates HV" not in recommendation
    assert "infeasible front members are filtered out before the HV calculation" in recommendation
