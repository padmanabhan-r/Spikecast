"""The rule check: only cells in the event, only numbers that were measured."""

from spikecast.narrate.grounding import check_line, glossary_for

FACTS = {"ppl1_rate_hz": 136, "ppl1_rate_before_hz": 6, "smell_present": "A"}


def ok(line, cells=("ppl1",), facts=FACTS, **kw):
    return check_line(line, list(cells), facts, **kw)


def test_a_plain_supported_line_passes():
    assert ok("The shock lands and PPL1 dopamine neurons fire 136 times a second.").ok


def test_a_cell_type_outside_the_event_is_rejected():
    verdict = ok("PAM dopamine neurons fire as the shock lands.")
    assert not verdict.ok and "pam" in verdict.reason.lower()


def test_an_invented_cell_type_is_rejected():
    verdict = ok("The shock reaches DNa02 and the fly flinches.")
    assert not verdict.ok and "DNa02" in verdict.reason


def test_an_unmeasured_number_is_rejected():
    verdict = ok("PPL1 dopamine neurons fire 300 times a second.")
    assert not verdict.ok and "300" in verdict.reason


def test_a_rounded_measured_number_is_accepted():
    assert ok("PPL1 dopamine neurons fire about 140 times a second.").ok


def test_number_words_need_a_measurement_too():
    assert not ok("PPL1 dopamine neurons double their firing.").ok
    assert ok("The fly weakens its synapses by half.", cells=["kc"], facts={"percent": 50}).ok


def test_the_word_limit_is_enforced():
    long = " ".join(["word"] * 17)
    assert not ok(long, max_words=16).ok


def test_a_shared_alias_passes_when_any_owner_is_in_the_event():
    line = "The output neurons that favour approach go quiet."
    assert ok(line, cells=["mbon_approach"], facts={}).ok
    assert not ok(line, cells=["ppl1"], facts={}).ok


def test_the_glossary_subset_is_only_the_cells_in_the_event():
    names = [entry["name"] for entry in glossary_for(["ppl1", "kc"])]
    assert names == ["PPL1 dopamine neurons", "Kenyon cells"]
