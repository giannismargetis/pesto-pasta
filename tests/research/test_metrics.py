import pytest

from research import metrics


def test_edit_distance_basic():
    assert metrics.edit_distance("kitten", "sitting") == 3
    assert metrics.edit_distance([], ["a"]) == 1
    assert metrics.edit_distance(["a", "b"], ["a", "b"]) == 0


def test_normalize_greek_case_punct_final_sigma():
    assert metrics.normalize("Καλησπέρα, πώς είσαι;") == "καλησπέρα πώσ είσαι"
    assert metrics.normalize("ΠΏΣ") == metrics.normalize("πώς")
    # Greek question mark (U+037E) and ano teleia are punctuation
    assert metrics.normalize("Τι;; Ναι· όχι") == "τι ναι όχι"


def test_normalize_accents_view():
    assert metrics.normalize("Είναι ωραία", accents=False) == "ειναι ωραια"
    assert metrics.normalize("Ναΐσκος", accents=False) == "ναισκοσ"


def test_apostrophes_are_deleted_not_split():
    assert metrics.normalize("Don't stop") == "dont stop"


def test_score_perfect_and_formatting_only_errors():
    s = metrics.score("Hello, world.", "hello world")
    assert s.word_edits == 0 and s.char_edits == 0
    # case + two punctuation tokens differ in the formatted view
    assert s.fmt_edits == 3


def test_corpus_rates_are_pooled_not_averaged():
    a = metrics.score("one two three four", "one two three four")  # 0/4
    b = metrics.score("five", "six")  # 1/1
    rates = metrics.corpus_rates([a, b])
    assert rates["wer"] == pytest.approx(1 / 5)  # pooled, not mean(0, 1) = 0.5


def test_bootstrap_ci_contains_point_and_is_deterministic():
    scores = [metrics.score("a b c d", "a b x d"), metrics.score("e f", "e f"), metrics.score("g h i", "g")] * 10
    point = metrics.corpus_rates(scores)["wer"]
    ci1 = metrics.bootstrap_ci(scores, n_boot=500)["wer"]
    ci2 = metrics.bootstrap_ci(scores, n_boot=500)["wer"]
    assert ci1 == ci2
    assert ci1[0] <= point <= ci1[1]


def test_paired_delta_sign():
    ref = ["a b c d"] * 20
    good = [metrics.score(r, r) for r in ref]
    bad = [metrics.score(r, "a b") for r in ref]
    d = metrics.paired_bootstrap_delta(good, bad, n_boot=200)
    assert d["delta"] == pytest.approx(0.5)
    assert d["p_b_worse"] == 1.0


def test_latency_summary_percentiles():
    s = metrics.latency_summary(list(range(1, 101)))
    assert s["n"] == 100 and s["p50"] == pytest.approx(50.5) and s["max"] == 100
