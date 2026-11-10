"""Manual response observations, never an AI ranking or business-fact engine."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from local_presence_miner.domain.prospect_findings import bounded_text, utc_text

AI_SOURCE_KIND = 'manual_ai_response.v1'
AI_MENTION_STATES = ('UNCLEAR', 'MENTIONED', 'NOT_MENTIONED')
AI_TOOL_STATES = ('UNKNOWN', 'YES', 'NO')
AI_PROVIDERS = ('ChatGPT', 'Claude')
AI_DISCLOSURE_VERSION = 2


def ai_snapshot(lead_id: int, *, business: dict, provider: str, prompt: str, response: str,
                model: str = 'UNKNOWN', model_version: str = 'UNKNOWN', captured_at: str | None = None,
                test_context: str = 'UNKNOWN', browsing_available: str = 'UNKNOWN', browsing_used: str = 'UNKNOWN',
                prospect_mention: str = 'UNCLEAR', mentioned_businesses: list | None = None,
                prospect_aliases: list | None = None,
                omitted_businesses: list | None = None, competitor_mentions: list | None = None,
                citations: list | None = None, source_refs: list | None = None, repeat_group: str = '',
                variability_notes: str = '', observed_inaccuracies: list | None = None) -> dict:
    if provider not in AI_PROVIDERS or prospect_mention not in AI_MENTION_STATES:
        raise ValueError('Choose a supported provider and explicit mention annotation.')
    if browsing_available not in AI_TOOL_STATES or browsing_used not in AI_TOOL_STATES:
        raise ValueError('Record search/browsing availability and use separately; UNKNOWN is allowed.')
    if browsing_available == 'NO' and browsing_used == 'YES':
        raise ValueError('Search cannot be both unavailable and used; clarify the test context.')
    if not isinstance(business, dict) or set(business) != {'name', 'place_id', 'website'}:
        raise ValueError('AI response requires its recorded business identity.')
    for key, value in business.items():
        bounded_text(value, f'Business {key}', required=key == 'name', maximum=2000)
    bounded_text(prompt, 'Exact prompt', maximum=16000)
    bounded_text(response, 'Exact response', maximum=128000)
    if captured_at is not None:
        bounded_text(captured_at, 'Original test timestamp', maximum=80)
        parsed = datetime.fromisoformat(captured_at)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError('Record the test timestamp with timezone, or leave it unknown.')
        stamp = utc_text(parsed)
    else:
        stamp = None

    def values(items, label):
        if items is None:
            return []
        if not isinstance(items, list) or len(items) > 100:
            raise ValueError(f'{label} requires at most 100 manually recorded entries.')
        return [bounded_text(item, label, maximum=2000) for item in items]

    payload: dict[str, Any] = {
        'business': business, 'provider': provider, 'model': bounded_text(model, 'Model', maximum=160),
        'model_version': bounded_text(model_version, 'Model/version', maximum=160),
        'prompt': prompt, 'response': response, 'captured_at': captured_at,
        'test_context': bounded_text(test_context, 'Test context'),
        'browsing_available': browsing_available, 'browsing_used': browsing_used, 'prospect_mention': prospect_mention,
        'mentioned_businesses': values(mentioned_businesses, 'Mentioned businesses'),
        'prospect_aliases': values(prospect_aliases, 'Recorded prospect names/aliases'),
        'omitted_businesses': values(omitted_businesses, 'Omitted businesses'),
        'competitor_mentions': values(competitor_mentions, 'Competitor mentions'),
        'citations': values(citations, 'Citations'), 'source_refs': values(source_refs, 'Source references'),
        'repeat_group': bounded_text(repeat_group, 'Related test group', required=False, maximum=160),
        'variability_notes': bounded_text(variability_notes, 'Variability notes', required=False),
        'observed_inaccuracies': values(observed_inaccuracies, 'Operator-noted inaccuracies'),
    }
    mentioned = {name.casefold() for name in payload['mentioned_businesses']}
    omitted = {name.casefold() for name in payload['omitted_businesses']}
    if mentioned & omitted or (prospect_mention == 'NOT_MENTIONED' and business['name'].casefold() in mentioned
                              or prospect_mention == 'MENTIONED' and business['name'].casefold() in omitted):
        raise ValueError('Mention/omission annotations conflict; keep ambiguous cases UNCLEAR.')
    names = [business['name'], *payload['prospect_aliases']]
    literal_mention = any(re.search(r'(?<!\w)' + r'\s+'.join(re.escape(word) for word in name.split()) + r'(?!\w)',
                                   response, re.IGNORECASE) for name in names)
    if prospect_mention == 'NOT_MENTIONED' and literal_mention:
        raise ValueError('The exact business name appears in the response; it cannot be recorded as not mentioned.')
    if prospect_mention == 'MENTIONED' and not literal_mention:
        raise ValueError('Record the actual mentioned business alias, or keep the mention status UNCLEAR.')
    return {'schema_version': 1, 'source_kind': AI_SOURCE_KIND, 'subject': {'lead_id': lead_id},
            'observed_at': stamp, 'payload': payload}


def ai_claim(snapshot: dict) -> str:
    data = snapshot['payload']
    state = data['prospect_mention']
    action = {'MENTIONED': 'was mentioned', 'NOT_MENTIONED': 'was not mentioned', 'UNCLEAR': 'has an unclear mention status'}[state]
    return (f"In this single manually captured {data['provider']} response, {data['business']['name']} {action}. "
            'This describes only the recorded test, not overall AI visibility, search ranking, demand or a business fact.')


def ai_disclosure(snapshot: dict) -> str:
    """Complete external text: shared by the approval preview and proposal.

    Raw prompts, responses, context, citations and internal references are
    deliberately absent. They remain in the immutable internal source.
    """
    data = snapshot['payload']
    return (f"{ai_claim(snapshot)}\nRecorded test time: {data['captured_at'] or 'UNKNOWN'}"
            f"\nRecorded model/version: {data['model']} / {data['model_version']}"
            '\nOne manually recorded response only; independently repeat the test before drawing broader conclusions.')
