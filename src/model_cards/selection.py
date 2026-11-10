"""Feature selectors combine provider availability with implemented adapters."""

from .loader import get_card, register_discovered_models


def get_feature_models(model_lists, custom_models, feature):
    """Return available model IDs and labels supported by a feature's adapter.

    Provider lists are unfiltered discovery results, not conversation whitelists.
    Explicit custom endpoints remain available independently of remote discovery.
    """
    if feature not in ("image", "tts", "stt"):
        raise ValueError(f"Unknown model feature: {feature}")
    options = {}
    for provider, model_ids in model_lists.items():
        if provider == "custom":
            continue
        register_discovered_models(provider, model_ids)
        for model_id in model_ids:
            card = get_card(model_id, custom_models)
            if not card or card.provider != provider:
                continue
            if feature == "image":
                supported = card.capabilities.image_gen and (
                    card.api_family == "images"
                    or card.quirks.get("multimodal_image_gen")
                )
            elif feature == "tts":
                supported = (
                    card.capabilities.audio_out
                    and not card.is_realtime_model()
                    and (
                        card.api_family == "tts"
                        and provider in ("openai", "gemini")
                        or provider == "openai"
                        and card.quirks.get("requires_audio_modality")
                    )
                )
            else:
                supported = (
                    provider == "openai"
                    and card.capabilities.audio_in
                    and (
                        card.api_family
                        in ("transcription", "stt", "audio.transcriptions")
                    )
                )
            if supported:
                options[model_id] = card.get_display_name()

    custom_api_types = {
        "image": {"images"},
        "tts": {"tts"},
        "stt": {"stt", "audio.transcriptions"},
    }
    for model_id, config in custom_models.items():
        if (config.get("api_type") or "").lower() in custom_api_types[feature]:
            card = get_card(model_id, custom_models)
            capability = {"image": "image_gen", "tts": "audio_out", "stt": "audio_in"}[
                feature
            ]
            if card and not getattr(card.capabilities, capability):
                continue
            options[model_id] = config.get("display_name") or model_id
    return dict(sorted(options.items()))
