from __future__ import annotations

from local_presence_miner.services.prompt_parser import parse_prompt_answer, parsed_summary_text


def test_prompt_answer_parser_groups_common_sections() -> None:
    text = """
    ## Strengths
    - Clear phone CTA
    - Good service pages

    ## Weaknesses
    - No review proof above the fold

    ## Recommendations
    - Add a quote path

    ## Warnings
    - Do not guarantee rankings
    """
    parsed = parse_prompt_answer(text)
    assert "Clear phone CTA" in parsed.strengths
    assert "No review proof above the fold" in parsed.weaknesses
    assert "Add a quote path" in parsed.recommendations
    assert "Do not guarantee rankings" in parsed.warnings
    assert "Recommendations" in parsed_summary_text(text)
