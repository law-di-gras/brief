from backend.pipeline.edition import lexically_supported


def test_new_subject_matter_is_rejected():
    assert not lexically_supported("The case is ready for trial.", ["The client called the office yesterday."])


def test_restating_the_fact_passes():
    assert lexically_supported("The client called the office.", ["The client called the office yesterday."])


def test_summary_of_a_longer_fact_passes():
    fact = "The firm has made three written requests to McCulloch Orthopaedic for updated office notes and a right shoulder arthroscopy date, with no date given."
    assert lexically_supported("The firm has asked McCulloch Orthopaedic three times for an arthroscopy date.", [fact])
