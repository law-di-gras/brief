from backend.pipeline import validate as v

SRC = {
    "note:1": {"text": "Medicaid lien of $22,180.00 as of 5 October 2011. Three written requests,\nno date given.",
               "item_date": "2026-09-01"},
    "task:2": {"text": "Task: Get records\nDue: 2026-08-25\n\nAsk the office for the surgery date.", "item_date": "2026-08-25"},
}
ROSTER = {"contact:9"}


def fact(**kw):
    base = {"text": "The lien is $22,180.", "category": "lien", "source_ids": ["note:1"],
            "evidence": "Medicaid lien of $22,180.00", "audience": "internal", "importance": 4}
    base.update(kw)
    return base


def test_number_normalization():
    dates, nums = v.extract_numbers("$22,180.00 on 5 October 2011, Sep 30, 2026, 10/02/2026, twenty-two, $100k")
    assert {"2011-10-05", "2026-09-30", "2026-10-02"} <= dates
    assert {"22180", "22", "100000"} <= nums


def test_keeps_good_fact():
    kept, drops = v.validate_facts([fact()], SRC, ROSTER)
    assert len(kept) == 1 and not drops


def test_rule1_fake_source():
    kept, drops = v.validate_facts([fact(source_ids=["note:99"])], SRC, ROSTER)
    assert not kept and drops["fake_source"] == 1


def test_rule2_evidence_must_be_verbatim():
    kept, drops = v.validate_facts([fact(evidence="Medicaid lien totals 22180")], SRC, ROSTER)
    assert not kept and drops["evidence_not_verbatim"] == 1


def test_rule2_tolerates_whitespace_and_quotes():
    kept, _ = v.validate_facts([fact(text="Three requests went unanswered.",
                                     evidence="“Three written requests, no date given”")], SRC, ROSTER)
    assert kept


def test_rule3_unsourced_number():
    kept, drops = v.validate_facts([fact(text="The lien is $25,000.")], SRC, ROSTER)
    assert not kept and drops["unsourced_number"] == 1


def test_rule3_number_words_and_dates_match_digits():
    kept, _ = v.validate_facts([fact(text="3 requests since 2011-10-05.", evidence="Three written requests")],
                               SRC, ROSTER)
    assert kept


def test_event_date_cleared_not_dropped():
    kept, drops = v.validate_facts([fact(event_date="2020-01-01")], SRC, ROSTER)
    assert kept and kept[0]["event_date"] is None and drops["event_date_cleared"] == 1


def test_event_date_from_item_date():
    kept, _ = v.validate_facts([fact(source_ids=["task:2"], text="Records were requested.",
                                     evidence="Ask the office for the surgery date", event_date="2026-08-25")],
                               SRC, ROSTER)
    assert kept[0]["event_date"] == "2026-08-25"


def test_unknown_entities_removed():
    kept, _ = v.validate_facts([fact(entities=["contact:9", "contact:404"])], SRC, ROSTER)
    assert kept[0]["entities"] == ["contact:9"]


def test_dependency_holder_must_be_known():
    deps, _ = v.validate_dependencies([{"blocked": "a", "waiting_on": "b", "holder": "contact:404",
                                        "source_ids": ["task:2"], "evidence": "Ask the office for the surgery date"}],
                                      SRC, ROSTER)
    assert deps[0]["holder"] == "unknown"


def test_check_sentence():
    assert v.check_sentence("The lien is $22,180.", [SRC["note:1"]["text"]])
    assert not v.check_sentence("The lien is $30,000.", [SRC["note:1"]["text"]])
