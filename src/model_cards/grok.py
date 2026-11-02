"""Grok defaults and documented retirements, reviewed November 2, 2026.

The authenticated models API remains the authority for account availability.
Sources: https://docs.x.ai/developers/models
https://docs.x.ai/developers/migration/may-15-retirement
https://docs.x.ai/developers/migration/imagine-image-quality-nov-2
"""

GROK_CHAT_MODELS = (
    "grok-latest",
    "grok-4.7",
    "grok-4.6",
    "grok-4.5",
    "grok-4.5-latest",
    "grok-4.3",
    "grok-4.3-latest",
    "grok-4.20-0309-reasoning",
    "grok-4.20-0309-non-reasoning",
)

GROK_IMAGE_MODELS = ("grok-imagine-image", "grok-imagine-image-2.0")

# These endpoints need a video workflow, which ChatGTK does not implement.
GROK_UNSUPPORTED_MODEL_PREFIXES = ("grok-imagine-video",)

GROK_DEFAULT_MODELS = (
    "grok-latest",
    "grok-4.7",
    "grok-4.6",
    "grok-4.5",
    "grok-4.3",
    *GROK_IMAGE_MODELS,
    "grok-realtime",
)

# Keep these identifiers for saved conversations, without advertising them
# as independently available models in the defaults or discovery fallback.
GROK_RETIRED_MODELS = {
    "grok-3": "grok-4.3",
    "grok-4-0709": "grok-4.3",
    "grok-4-1-fast-reasoning": "grok-4.3",
    "grok-4-1-fast-non-reasoning": "grok-4.3",
    "grok-4-fast-reasoning": "grok-4.3",
    "grok-4-fast-non-reasoning": "grok-4.3",
    "grok-code-fast-1": "grok-build-0.1",
    "grok-imagine-image-pro": "grok-imagine-image-2.0",
    "grok-imagine-image-quality": "grok-imagine-image-2.0",
}

LEGACY_GROK_MODEL_WHITELIST = (
    "grok-realtime,grok-2-1212,grok-2-vision-1212,grok-2-image-1212,"
    "grok-3,grok-3-mini,grok-4-1-fast-non-reasoning,"
    "grok-4-1-fast-reasoning,grok-4-fast-non-reasoning,grok-4-fast-reasoning"
)


def register_grok_model_aliases(metadata: dict) -> None:
    """Give API-advertised aliases the capabilities of their known base model."""
    from dataclasses import replace
    from .loader import get_card, list_cards, register_card

    known = list_cards()
    for model in metadata.get("models", []):
        base = get_card(model.get("id", ""))
        if base is None or base.provider != "grok":
            continue
        for alias in model.get("aliases") or []:
            if not isinstance(alias, str) or not alias.startswith("grok-"):
                continue
            if alias in known:
                continue
            card = replace(
                base,
                id=alias,
                display_name=alias,
                capabilities=replace(base.capabilities),
                quirks={**base.quirks, "alias_of": base.id},
            )
            register_card(card)
            known[alias] = card
