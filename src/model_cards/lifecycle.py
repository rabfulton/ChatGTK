"""Documented model deprecations, reviewed November 10, 2026.

This is presentation metadata, not an availability filter or a replacement
policy. Exact IDs keep unrelated models and custom endpoints unaffected.
Source: https://developers.openai.com/api/docs/deprecations
"""

from .loader import get_card

OPENAI_DEPRECATION_SOURCE = "https://developers.openai.com/api/docs/deprecations"

# (shutdown date, documented replacement, exact model IDs)
_OPENAI_GROUPS = (
    (
        "2027-01-06",
        "gpt-realtime-2.1-mini",
        (
            "tts-1",
            "tts-1-1106",
            "tts-1-hd",
            "tts-1-hd-1106",
            "gpt-4o-mini-tts",
            "gpt-4o-mini-tts-2025-03-20",
            "gpt-4o-mini-tts-2025-12-15",
        ),
    ),
    (
        "2027-01-14",
        "gpt-6-luna",
        (
            "gpt-4o",
            "gpt-4o-2024-08-06",
            "gpt-4o-2024-11-20",
            "gpt-4o-mini",
            "gpt-4o-mini-2024-07-18",
            "gpt-4.1",
            "gpt-4.1-2025-04-14",
            "gpt-4.1-mini",
            "gpt-4.1-mini-2025-04-14",
        ),
    ),
    (
        "2027-01-20",
        "gpt-realtime-2.1",
        (
            "gpt-realtime",
            "gpt-realtime-2025-08-28",
            "gpt-4o-realtime",
        ),
    ),
    (
        "2027-01-20",
        "gpt-realtime-2.1-mini",
        (
            "gpt-realtime-mini",
            "gpt-realtime-mini-2025-12-15",
            "gpt-4o-mini-realtime",
        ),
    ),
    (
        "2027-01-20",
        "gpt-audio-1.5",
        (
            "gpt-audio",
            "gpt-audio-2025-08-28",
            "gpt-4o-audio",
            "gpt-audio-mini",
            "gpt-audio-mini-2025-12-15",
            "gpt-4o-mini-audio",
        ),
    ),
    (
        "2027-01-20",
        "gpt-4o-mini-transcribe-2025-12-15",
        ("gpt-4o-mini-transcribe-2025-03-20",),
    ),
    (
        "2027-02-26",
        "gpt-live-transcribe or gpt-transcribe",
        (
            "whisper-1",
            "gpt-4o-transcribe",
            "gpt-4o-mini-transcribe",
            "gpt-4o-mini-transcribe-2025-12-15",
            "gpt-4o-transcribe-diarize",
        ),
    ),
    (
        "2027-04-01",
        "gpt-6-sol",
        (
            "gpt-5.3-codex",
            "gpt-5.1",
            "gpt-5.1-2025-11-13",
        ),
    ),
    ("2027-04-01", "gpt-6-luna", ("gpt-5.4-nano", "gpt-5.4-nano-2026-03-17")),
    (
        "2026-12-11",
        "gpt-5.6-sol",
        (
            "gpt-5",
            "gpt-5-2025-08-07",
            "o3",
            "o3-2025-04-16",
        ),
    ),
    (
        "2026-12-11",
        "gpt-5.6-sol (pro reasoning)",
        (
            "gpt-5-pro",
            "gpt-5-pro-2025-10-06",
            "o3-pro",
            "o3-pro-2025-06-10",
        ),
    ),
    ("2026-12-11", "gpt-5.6-terra", ("gpt-5-mini", "gpt-5-mini-2025-08-07")),
    ("2026-12-11", "gpt-5.6-luna", ("gpt-5-nano", "gpt-5-nano-2025-08-07")),
    (
        "2026-12-01",
        "gpt-image-2.6-sunburst or gpt-image-2.6-flare",
        (
            "gpt-image-1-mini",
            "gpt-image-1.5",
            "gpt-image-1.5-2025-12-16",
            "chatgpt-image-latest",
        ),
    ),
    (
        "2027-02-10",
        "gpt-image-2.6-sunburst or gpt-image-2.6-flare",
        (
            "gpt-image-2",
            "gpt-image-2-2026-04-21",
        ),
    ),
    # Past retirements still matter when opening a stale cache or whitelist.
    (
        "2026-10-23",
        "gpt-5.6-sol",
        (
            "gpt-4",
            "gpt-4-0613",
            "gpt-4-1106-preview",
            "gpt-4-turbo",
            "gpt-4-turbo-2024-04-09",
            "gpt-4o-2024-05-13",
            "o1",
            "o1-2024-12-17",
            "o3-mini",
            "o3-mini-2025-01-31",
        ),
    ),
    ("2026-10-23", "gpt-5.6-sol (pro reasoning)", ("o1-pro", "o1-pro-2025-03-19")),
    ("2026-10-23", "gpt-5.6-luna", ("gpt-4.1-nano", "gpt-4.1-nano-2025-04-14")),
    (
        "2026-10-23",
        "gpt-5.6-terra",
        (
            "gpt-3.5-turbo",
            "gpt-3.5-turbo-0125",
            "o4-mini",
            "o4-mini-2025-04-16",
        ),
    ),
    ("2026-10-23", "gpt-image-2.5-sunburst or gpt-image-2.5-flare", ("gpt-image-1",)),
    ("2026-08-10", "gpt-5.6-sol", ("gpt-5.2-chat-latest", "gpt-5.3-chat-latest")),
    (
        "2026-07-23",
        "gpt-5.6-sol",
        (
            "gpt-5-chat-latest",
            "gpt-5-codex",
            "gpt-5.1-chat-latest",
            "gpt-5.1-codex",
            "gpt-5.1-codex-max",
            "gpt-5.2-codex",
            "o3-deep-research",
            "o3-deep-research-2025-06-26",
            "o4-mini-deep-research",
            "o4-mini-deep-research-2025-06-26",
        ),
    ),
    (
        "2026-07-23",
        "gpt-5.6-terra",
        (
            "gpt-5.1-codex-mini",
            "computer-use-preview",
            "computer-use-preview-2025-03-11",
            "gpt-4o-mini-search-preview-2025-03-11",
            "gpt-4o-search-preview-2025-03-11",
        ),
    ),
    ("2026-07-23", "gpt-audio-1.5", ("gpt-audio-mini-2025-10-06",)),
    ("2026-07-23", "gpt-realtime-2.1-mini", ("gpt-realtime-mini-2025-10-06",)),
    (
        "2026-05-12",
        "gpt-image-2, gpt-image-1 or gpt-image-1-mini",
        ("dall-e-2", "dall-e-3"),
    ),
    (
        "2026-05-07",
        "gpt-realtime-1.5",
        (
            "gpt-4o-realtime-preview",
            "gpt-4o-realtime-preview-2025-06-03",
            "gpt-4o-realtime-preview-2024-12-17",
        ),
    ),
    ("2026-05-07", "gpt-realtime-mini", ("gpt-4o-mini-realtime-preview",)),
    ("2026-05-07", "gpt-audio-1.5", ("gpt-4o-audio-preview",)),
    ("2026-05-07", "gpt-audio-mini", ("gpt-4o-mini-audio-preview",)),
    ("2026-03-26", "gpt-5 or gpt-4.1", ("gpt-4-0125-preview", "gpt-4-turbo-preview")),
    ("2026-02-17", "gpt-5.1-chat-latest", ("chatgpt-4o-latest",)),
    ("2026-02-12", "gpt-5-codex-mini", ("codex-mini-latest",)),
    ("2025-10-27", "o4-mini", ("o1-mini",)),
    ("2025-07-28", "o3", ("o1-preview",)),
    ("2026-09-28", "gpt-5.6-terra", ("gpt-3.5-turbo-instruct", "gpt-3.5-turbo-1106")),
)

OPENAI_DEPRECATIONS = {
    model_id: {
        "shutdown_date": shutdown,
        "replacement_model": replacement,
        "source": OPENAI_DEPRECATION_SOURCE,
    }
    for shutdown, replacement, models in _OPENAI_GROUPS
    for model_id in models
}


def get_model_deprecation(model_id, provider, custom_models=None):
    """Return documented deprecation details for this provider's model, if known.

    Existing model-card deprecation flags and explicit overrides are respected.
    Missing lifecycle data does not imply a model is active or available.
    """
    card = get_card(model_id, custom_models)
    if card and card.provider != provider:
        return None
    known = OPENAI_DEPRECATIONS.get(model_id) if provider == "openai" else None
    if card and "deprecated" in card.quirks:
        if not card.quirks["deprecated"]:
            return None
        return {
            "deprecated": True,
            **(known or {}),
            **{
                key: card.quirks[key]
                for key in ("shutdown_date", "replacement_model")
                if key in card.quirks
            },
        }
    return {"deprecated": True, **known} if known else None
