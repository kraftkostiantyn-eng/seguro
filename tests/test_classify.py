from seguro.classify import classify_html

FILLER = " ".join(["lorem"] * 40)


def test_parking():
    page = classify_html(f"<title>x</title><body>This domain is for sale! {FILLER}</body>")
    assert page.is_parking and not page.is_clean_content


def test_sport_ukrainian():
    text = ("Новини футболу та спорту. Матч ліги завершився, і це було цікаво для вболівальників. "
            "Футбол, матч, спорт — усе що потрібно знати, як і де дивитись. ") * 3
    page = classify_html(f"<html><title>Спорт</title><body>{text}</body></html>")
    assert page.language == "uk"
    assert "sport" in page.topics
    assert page.is_clean_content


def test_pharma_and_cjk():
    assert "pharma" in classify_html(f"<p>{'buy viagra cialis pharmacy ' * 3}{FILLER}</p>").spam_categories
    cjk = classify_html(f"<p>{'日本語のテキストです' * 20} {FILLER}</p>")
    assert "doorway_cjk" in cjk.spam_categories


def test_gambling_is_not_spam():
    page = classify_html(f"<p>{'casino slots betting ' * 3}{FILLER}</p>")
    assert "gambling" in page.categories
    assert page.is_clean_content
