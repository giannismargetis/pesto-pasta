import json
from collections import Counter

import pytest

from pesto import telemetry
from research.study import analysis
from research.study.measures import msd_error_rate, tlx_raw, wpm
from research.study.protocol import Protocol, latin_square


def test_wpm_definition():
    # 26 characters in 10 s -> (26 - 1) / 10 * 60 / 5 = 30 WPM
    assert wpm("abcdefghijklmnopqrstuvwxyz", 10.0) == pytest.approx(30.0)
    assert wpm("", 5) == 0.0


def test_msd_error_rate():
    assert msd_error_rate("the quick brown fox", "the quick brown fox") == 0.0
    assert msd_error_rate("abcd", "abxd") == pytest.approx(25.0)
    assert msd_error_rate("Γεια σου.", "γεια σου", normalized=True) == 0.0
    assert msd_error_rate("Γεια σου.", "γεια σου") > 0


def test_tlx_requires_all_scales():
    answers = dict(mental=10, physical=20, temporal=30, performance=40, effort=50, frustration=60)
    assert tlx_raw(answers) == pytest.approx(35.0)
    with pytest.raises(ValueError):
        tlx_raw({"mental": 1})


@pytest.mark.parametrize("n", [2, 3, 4, 5])
def test_latin_square_is_balanced(n):
    rows = latin_square(n)
    for pos in range(n):  # each condition appears equally often in every position
        assert len(set(Counter(r[pos] for r in rows).values())) == 1
    carry = Counter((r[i], r[i + 1]) for r in rows for i in range(n - 1))
    assert len(carry) == n * (n - 1) and len(set(carry.values())) == 1  # first-order carry-over balanced


@pytest.mark.parametrize("name", ["input_modality", "latency_perception"])
def test_protocol_assignment_is_disjoint_and_reproducible(name):
    p = Protocol.load(name)
    a = p.assign("P01", 0)
    b = p.assign("P01", 0)
    assert a == b
    phrases = [ph for _, prac, trials in a for ph in prac + trials]
    assert len(phrases) == len(set(phrases))
    assert all(len(trials) == p.trials_per_condition for _, _, trials in a)


def test_analysis_refuses_without_data(tmp_path):
    db = tmp_path / "empty.db"
    t = telemetry.Telemetry(db)
    t.close()
    assert analysis.analyze("input_modality", db, tmp_path / "out") == 1


def test_analysis_pipeline_runs_on_complete_data(tmp_path):
    """Synthetic rows only exercise the code path; they are not results."""
    db = tmp_path / "s.db"
    t = telemetry.Telemetry(db)
    for pi in range(5):
        pid = f"T{pi}"
        for ci, cond in enumerate(["keyboard", "voice_ptt", "voice_vad"]):
            for k in range(3):
                t.record_trial({"study": "input_modality", "participant": pid, "condition": cond, "block": ci + 1,
                                "trial": k + 1, "stimulus": "x", "response": "x", "started_at": "", "first_input_ms": 1,
                                "completed_ms": 1, "keystrokes": 1, "backspaces": k, "utterances": 0,
                                "wpm": 30 + 10 * ci + pi + k, "msd_error": 1.0 + ci, "cer": 0.5 + ci,
                                "data_json": json.dumps({"practice": False})})
            t.record_questionnaire({"study": "input_modality", "participant": pid, "condition": cond,
                                    "instrument": "nasa_tlx_raw", "answers_json": "{}", "score": 40 + 5 * ci + pi,
                                    "created_at": ""})
    t.close()
    out = tmp_path / "out"
    assert analysis.analyze("input_modality", db, out) == 0
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["measures"]["wpm"]["tests"]["n"] == 5
    assert "friedman" in summary["measures"]["wpm"]["tests"]
    assert (out / "conditions.png").exists() and (out / "report.md").exists()


def test_holm_correction():
    assert analysis.holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
