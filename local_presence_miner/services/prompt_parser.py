from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedPromptAnswer:
    summary: str
    strengths: list[str]
    weaknesses: list[str]
    recommendations: list[str]
    warnings: list[str]


SECTION_ALIASES = {
    "strength": "strengths",
    "strengths": "strengths",
    "what works": "strengths",
    "weakness": "weaknesses",
    "weaknesses": "weaknesses",
    "gaps": "weaknesses",
    "recommendation": "recommendations",
    "recommendations": "recommendations",
    "next steps": "recommendations",
    "warning": "warnings",
    "warnings": "warnings",
    "risks": "warnings",
}


def parse_prompt_answer(text: str) -> ParsedPromptAnswer:
    sections: dict[str, list[str]] = {
        "strengths": [],
        "weaknesses": [],
        "recommendations": [],
        "warnings": [],
    }
    current = "recommendations"
    summary_lines: list[str] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading = normalize_heading(line)
        if heading:
            current = heading
            continue
        item = cleanup_bullet(line)
        if current in sections:
            sections[current].append(item)
        elif len(summary_lines) < 4:
            summary_lines.append(item)

    if not summary_lines:
        for key in ["recommendations", "weaknesses", "strengths", "warnings"]:
            summary_lines.extend(sections[key][:2])
            if len(summary_lines) >= 4:
                break

    return ParsedPromptAnswer(
        summary=" ".join(summary_lines[:4]).strip(),
        strengths=sections["strengths"],
        weaknesses=sections["weaknesses"],
        recommendations=sections["recommendations"],
        warnings=sections["warnings"],
    )


def parsed_summary_text(text: str) -> str:
    parsed = parse_prompt_answer(text)
    parts = [f"Summary: {parsed.summary or 'No summary detected.'}"]
    for label, values in [
        ("Strengths", parsed.strengths),
        ("Weaknesses", parsed.weaknesses),
        ("Recommendations", parsed.recommendations),
        ("Warnings", parsed.warnings),
    ]:
        if values:
            parts.append(f"\n{label}:")
            parts.extend(f"- {value}" for value in values[:8])
    return "\n".join(parts)


def normalize_heading(line: str) -> str:
    cleaned = re.sub(r"^[#*\-\d.\s]+", "", line).strip(" :").lower()
    return SECTION_ALIASES.get(cleaned, "")


def cleanup_bullet(line: str) -> str:
    return re.sub(r"^[*\-\d.)\s]+", "", line).strip()
