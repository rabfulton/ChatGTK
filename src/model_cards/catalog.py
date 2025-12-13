"""
catalog.py – Built-in model cards for known models.

This module contains pre-defined ModelCard instances for popular models from
OpenAI, Gemini, Grok, Claude, and Perplexity. These serve as the default
configuration and can be overridden by user-defined custom models.
"""

from .schema import ModelCard, Capabilities


BUILTIN_CARDS: dict[str, ModelCard] = {
    # ---------------------------------------------------------------------------
    # OpenAI Chat Models
    # ---------------------------------------------------------------------------
    "gpt-4o": ModelCard(
        id="gpt-4o",
        provider="openai",
        display_name="GPT-4o",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
    ),
    "gpt-4o-mini": ModelCard(
        id="gpt-4o-mini",
        provider="openai",
        display_name="GPT-4o Mini",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
    ),
    "chatgpt-4o-latest": ModelCard(
        id="chatgpt-4o-latest",
        provider="openai",
        display_name="ChatGPT-4o Latest",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
    ),
    "gpt-4-turbo": ModelCard(
        id="gpt-4-turbo",
        provider="openai",
        display_name="GPT-4 Turbo",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),
    "gpt-4.1": ModelCard(
        id="gpt-4.1",
        provider="openai",
        display_name="GPT-4.1",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
    ),
    "gpt-3.5-turbo": ModelCard(
        id="gpt-3.5-turbo",
        provider="openai",
        display_name="GPT-3.5 Turbo",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=True),
    ),

    # ---------------------------------------------------------------------------
    # OpenAI GPT-5 Family
    # ---------------------------------------------------------------------------
    "gpt-5.1": ModelCard(
        id="gpt-5.1",
        provider="openai",
        display_name="GPT-5.1",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
        quirks={"no_temperature": True},
    ),
    "gpt-5.1-chat-latest": ModelCard(
        id="gpt-5.1-chat-latest",
        provider="openai",
        display_name="GPT-5.1 Chat Latest",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
        quirks={"no_temperature": True},
    ),
    "gpt-5-pro": ModelCard(
        id="gpt-5-pro",
        provider="openai",
        display_name="GPT-5 Pro",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
        quirks={"no_temperature": True},
    ),

    # ---------------------------------------------------------------------------
    # OpenAI Reasoning Models (o1, o3 series)
    # ---------------------------------------------------------------------------
    "o1-mini": ModelCard(
        id="o1-mini",
        provider="openai",
        display_name="o1-mini",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=False),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "o1-preview": ModelCard(
        id="o1-preview",
        provider="openai",
        display_name="o1-preview",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=False),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "o3": ModelCard(
        id="o3",
        provider="openai",
        display_name="o3",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=False),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "o3-mini": ModelCard(
        id="o3-mini",
        provider="openai",
        display_name="o3-mini",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=False),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),

    # ---------------------------------------------------------------------------
    # OpenAI Audio Models
    # ---------------------------------------------------------------------------
    "gpt-4o-audio-preview": ModelCard(
        id="gpt-4o-audio-preview",
        provider="openai",
        display_name="GPT-4o Audio Preview",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, audio_in=True, audio_out=True),
        quirks={"requires_audio_modality": True},
    ),
    "gpt-4o-mini-audio-preview": ModelCard(
        id="gpt-4o-mini-audio-preview",
        provider="openai",
        display_name="GPT-4o Mini Audio Preview",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, audio_in=True, audio_out=True),
        quirks={"requires_audio_modality": True},
    ),

    # ---------------------------------------------------------------------------
    # OpenAI Realtime Models
    # ---------------------------------------------------------------------------
    "gpt-4o-realtime-preview": ModelCard(
        id="gpt-4o-realtime-preview",
        provider="openai",
        display_name="GPT-4o Realtime Preview",
        api_family="realtime",
        capabilities=Capabilities(text=True, audio_in=True, audio_out=True),
        quirks={"realtime_websocket": True},
    ),
    "gpt-4o-mini-realtime-preview": ModelCard(
        id="gpt-4o-mini-realtime-preview",
        provider="openai",
        display_name="GPT-4o Mini Realtime Preview",
        api_family="realtime",
        capabilities=Capabilities(text=True, audio_in=True, audio_out=True),
        quirks={"realtime_websocket": True},
    ),

    # ---------------------------------------------------------------------------
    # OpenAI Image Models
    # ---------------------------------------------------------------------------
    "dall-e-3": ModelCard(
        id="dall-e-3",
        provider="openai",
        display_name="DALL-E 3",
        api_family="images",
        capabilities=Capabilities(text=False, image_gen=True),
        image_sizes={"1024x1024", "1792x1024", "1024x1792"},
    ),
    "gpt-image-1": ModelCard(
        id="gpt-image-1",
        provider="openai",
        display_name="GPT Image",
        api_family="images",
        capabilities=Capabilities(text=False, image_gen=True, image_edit=True),
    ),
    "gpt-image-1-mini": ModelCard(
        id="gpt-image-1-mini",
        provider="openai",
        display_name="GPT Image Mini",
        api_family="images",
        capabilities=Capabilities(text=False, image_gen=True, image_edit=True),
    ),

    # ---------------------------------------------------------------------------
    # Gemini Models
    # ---------------------------------------------------------------------------
    "gemini-2.5-flash": ModelCard(
        id="gemini-2.5-flash",
        provider="gemini",
        display_name="Gemini 2.5 Flash",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),
    "gemini-2.5-pro": ModelCard(
        id="gemini-2.5-pro",
        provider="gemini",
        display_name="Gemini 2.5 Pro",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),
    "gemini-3-pro-preview": ModelCard(
        id="gemini-3-pro-preview",
        provider="gemini",
        display_name="Gemini 3 Pro Preview",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),
    "gemini-pro": ModelCard(
        id="gemini-pro",
        provider="gemini",
        display_name="Gemini Pro",
        capabilities=Capabilities(text=True, vision=True, tool_use=True),
    ),
    "gemini-pro-vision": ModelCard(
        id="gemini-pro-vision",
        provider="gemini",
        display_name="Gemini Pro Vision",
        capabilities=Capabilities(text=True, vision=True),
    ),
    "gemini-1.5-flash": ModelCard(
        id="gemini-1.5-flash",
        provider="gemini",
        display_name="Gemini 1.5 Flash",
        capabilities=Capabilities(text=True, vision=True, tool_use=True),
    ),
    "gemini-1.5-pro": ModelCard(
        id="gemini-1.5-pro",
        provider="gemini",
        display_name="Gemini 1.5 Pro",
        capabilities=Capabilities(text=True, vision=True, tool_use=True),
    ),

    # Gemini Image Models
    "gemini-2.5-flash-image": ModelCard(
        id="gemini-2.5-flash-image",
        provider="gemini",
        display_name="Gemini 2.5 Flash Image",
        capabilities=Capabilities(text=True, image_gen=True),
        quirks={"multimodal_image_gen": True},
    ),
    "gemini-3-pro-image-preview": ModelCard(
        id="gemini-3-pro-image-preview",
        provider="gemini",
        display_name="Gemini 3 Pro Image Preview",
        capabilities=Capabilities(text=True, image_gen=True),
        quirks={"multimodal_image_gen": True},
    ),

    # ---------------------------------------------------------------------------
    # Grok Models
    # ---------------------------------------------------------------------------
    "grok-2": ModelCard(
        id="grok-2",
        provider="grok",
        display_name="Grok-2",
        capabilities=Capabilities(text=True, vision=True, tool_use=True, web_search=True),
    ),
    "grok-2-mini": ModelCard(
        id="grok-2-mini",
        provider="grok",
        display_name="Grok-2 Mini",
        capabilities=Capabilities(text=True, vision=True, tool_use=True, web_search=True),
    ),
    "grok-2-1212": ModelCard(
        id="grok-2-1212",
        provider="grok",
        display_name="Grok-2 (1212)",
        capabilities=Capabilities(text=True, vision=True, tool_use=True, web_search=True),
    ),
    "grok-2-vision-1212": ModelCard(
        id="grok-2-vision-1212",
        provider="grok",
        display_name="Grok-2 Vision (1212)",
        capabilities=Capabilities(text=True, vision=True, tool_use=True, web_search=True),
    ),
    "grok-3": ModelCard(
        id="grok-3",
        provider="grok",
        display_name="Grok-3",
        capabilities=Capabilities(text=True, vision=True, tool_use=True, web_search=True),
    ),
    "grok-3-mini": ModelCard(
        id="grok-3-mini",
        provider="grok",
        display_name="Grok-3 Mini",
        capabilities=Capabilities(text=True, vision=True, tool_use=True, web_search=True),
    ),
    "grok-4-1-fast-non-reasoning": ModelCard(
        id="grok-4-1-fast-non-reasoning",
        provider="grok",
        display_name="Grok-4.1 Fast",
        capabilities=Capabilities(text=True, vision=True, tool_use=True, web_search=True),
    ),
    "grok-4-1-fast-reasoning": ModelCard(
        id="grok-4-1-fast-reasoning",
        provider="grok",
        display_name="Grok-4.1 Fast Reasoning",
        capabilities=Capabilities(text=True, vision=True, tool_use=True, web_search=True),
    ),
    "grok-4-fast-non-reasoning": ModelCard(
        id="grok-4-fast-non-reasoning",
        provider="grok",
        display_name="Grok-4 Fast",
        capabilities=Capabilities(text=True, vision=True, tool_use=True, web_search=True),
    ),
    "grok-4-fast-reasoning": ModelCard(
        id="grok-4-fast-reasoning",
        provider="grok",
        display_name="Grok-4 Fast Reasoning",
        capabilities=Capabilities(text=True, vision=True, tool_use=True, web_search=True),
    ),

    # Grok Image Model
    "grok-2-image-1212": ModelCard(
        id="grok-2-image-1212",
        provider="grok",
        display_name="Grok-2 Image (1212)",
        api_family="images",
        capabilities=Capabilities(text=False, image_gen=True),
    ),

    # ---------------------------------------------------------------------------
    # Claude Models
    # ---------------------------------------------------------------------------
    "claude-sonnet-4-5": ModelCard(
        id="claude-sonnet-4-5",
        provider="claude",
        display_name="Claude Sonnet 4.5",
        capabilities=Capabilities(text=True, vision=True, tool_use=True),
    ),
    "claude-haiku-4-5": ModelCard(
        id="claude-haiku-4-5",
        provider="claude",
        display_name="Claude Haiku 4.5",
        capabilities=Capabilities(text=True, vision=True, tool_use=True),
    ),
    "claude-opus-4-5": ModelCard(
        id="claude-opus-4-5",
        provider="claude",
        display_name="Claude Opus 4.5",
        capabilities=Capabilities(text=True, vision=True, tool_use=True),
    ),
    "claude-3-5-sonnet-latest": ModelCard(
        id="claude-3-5-sonnet-latest",
        provider="claude",
        display_name="Claude 3.5 Sonnet",
        capabilities=Capabilities(text=True, vision=True, tool_use=True),
    ),
    "claude-3-5-haiku-latest": ModelCard(
        id="claude-3-5-haiku-latest",
        provider="claude",
        display_name="Claude 3.5 Haiku",
        capabilities=Capabilities(text=True, vision=True, tool_use=True),
    ),

    # ---------------------------------------------------------------------------
    # Perplexity Models
    # ---------------------------------------------------------------------------
    "sonar": ModelCard(
        id="sonar",
        provider="perplexity",
        display_name="Sonar",
        capabilities=Capabilities(text=True, web_search=True),
        quirks={"always_web_search": True},
    ),
    "sonar-pro": ModelCard(
        id="sonar-pro",
        provider="perplexity",
        display_name="Sonar Pro",
        capabilities=Capabilities(text=True, web_search=True),
        quirks={"always_web_search": True},
    ),
    "sonar-reasoning": ModelCard(
        id="sonar-reasoning",
        provider="perplexity",
        display_name="Sonar Reasoning",
        capabilities=Capabilities(text=True, web_search=True),
        quirks={"always_web_search": True},
    ),
}
