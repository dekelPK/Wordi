from wordi.hebrew import candidate_forms, is_hebrew_word, normalize


def test_normalize_strips_niqqud_and_quotes() -> None:
    assert normalize("  כֶּלֶב ") == "כלב"
    assert normalize("ג׳ירפה") == "ג'ירפה"
    assert normalize("דו״ח") == 'דו"ח'
    assert normalize("שלום!") == "שלום"


def test_is_hebrew_word() -> None:
    assert is_hebrew_word("כלב")
    assert is_hebrew_word("צ'יפס")
    assert not is_hebrew_word("dog")
    assert not is_hebrew_word("כלב גדול")
    assert not is_hebrew_word("'כלב")
    assert not is_hebrew_word("")


def test_candidate_forms_strip_prefix_chain() -> None:
    assert list(candidate_forms("וכשהכלב")) == ["וכשהכלב", "כשהכלב", "שהכלב", "הכלב"]
    assert list(candidate_forms("כלב")) == ["כלב", "לב"]
    # stops at the first non-prefix letter and never leaves fewer than two letters
    assert list(candidate_forms("חתול")) == ["חתול"]
    assert list(candidate_forms("הם")) == ["הם"]
