from seguro.checks.backlinks import spam_anchor_ratio


def test_spam_anchor_ratio():
    anchors = [("sport news", 80), ("buy viagra", 10), ("日本語のテキスト", 10)]
    assert spam_anchor_ratio(anchors) == 0.2
    assert spam_anchor_ratio([]) == 0.0
