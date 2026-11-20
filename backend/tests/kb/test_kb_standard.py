"""An accounting standard's numbered paragraphs read under their sections (FRS 102 into the law base)."""
from backend.app.services.kb.standard import paragraphs

PAGES = ["Financial Reporting Council 177\nSection 17\nProperty, Plant and Equipment\nScope of this section\n"
         "17.1 This section applies to:\n(a) property, plant and equipment;\n17.2 [Deleted]",
         "178 FRS 102 (September 2024)\n17.31 An entity shall disclose\nthe depreciation methods used.\n"
         "1AC.30 An indication of the nature of any security."]


def test_paragraphs_under_their_sections_without_page_headers():
    titles, paras = paragraphs(PAGES)
    assert titles == {"17": "Property, Plant and Equipment"}
    assert [(s, n) for s, n, _t in paras] == [("17", "17.1"), ("17", "17.2"), ("17", "17.31"), ("1AC", "1AC.30")]
    assert paras[0][2] == "This section applies to: (a) property, plant and equipment;"
    assert "Financial Reporting Council" not in " ".join(t for *_x, t in paras)


def test_a_paragraph_number_seen_again_in_its_section_is_text_not_a_new_paragraph():
    _titles, paras = paragraphs(["Section 17\nProperty\n17.1 First.\n17.8 Eighth.\n17.9 Ninth,\n17.8 as above."])
    assert [n for _s, n, _t in paras] == ["17.1", "17.8", "17.9"]
    assert paras[-1][2] == "Ninth, 17.8 as above."


def test_every_page_of_a_section_has_its_own_address(monkeypatch):
    import backend.app.services.kb.standard as st
    lines = "\n".join(f"17.{i} Paragraph {i}." for i in range(1, 30))
    monkeypatch.setattr(st, "PdfReader", lambda _f: type("R", (), {"pages": [type("P", (), {
        "extract_text": lambda self: "Section 17\nProperty\n" + lines})()]})())
    pages = st.standard_pages(st.StandardSource("x.pdf", "FRS 102", "FRS 102", "https://frc/frs-102/", "ACCOUNTS"))
    assert [p[2] for p in pages] == ["https://frc/frs-102/#section-17", "https://frc/frs-102/#section-17-2",
                                     "https://frc/frs-102/#section-17-3"]
    assert [p[0] for p in pages] == ["FRS 102 17.1-17.12", "FRS 102 17.13-17.24", "FRS 102 17.25-17.29"]
