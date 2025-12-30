"""
catalog.py – Built-in model cards for known models.

This module contains pre-defined ModelCard instances for popular models from
OpenAI, Gemini, Grok, Claude, and Perplexity. These serve as the default
configuration and can be overridden by user-defined custom models.
"""

from .schema import ModelCard, Capabilities


BUILTIN_CARDS: dict[str, ModelCard] = {
    # ===========================================================================
    # OpenAI Models
    # ===========================================================================

    # ---------------------------------------------------------------------------
    # OpenAI GPT-4o Family
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
    "gpt-4o-2024-05-13": ModelCard(
        id="gpt-4o-2024-05-13",
        provider="openai",
        display_name="GPT-4o (2024-05-13)",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
    ),
    "gpt-4o-2024-08-06": ModelCard(
        id="gpt-4o-2024-08-06",
        provider="openai",
        display_name="GPT-4o (2024-08-06)",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
    ),
    "gpt-4o-2024-11-20": ModelCard(
        id="gpt-4o-2024-11-20",
        provider="openai",
        display_name="GPT-4o (2024-11-20)",
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
    "gpt-4o-mini-2024-07-18": ModelCard(
        id="gpt-4o-mini-2024-07-18",
        provider="openai",
        display_name="GPT-4o Mini (2024-07-18)",
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

    # ---------------------------------------------------------------------------
    # OpenAI GPT-4o Search Models
    # ---------------------------------------------------------------------------
    "gpt-4o-search-preview": ModelCard(
        id="gpt-4o-search-preview",
        provider="openai",
        display_name="GPT-4o Search Preview",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
        quirks={"search_optimized": True},
    ),
    "gpt-4o-search-preview-2025-03-11": ModelCard(
        id="gpt-4o-search-preview-2025-03-11",
        provider="openai",
        display_name="GPT-4o Search Preview (2025-03-11)",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
        quirks={"search_optimized": True},
    ),
    "gpt-4o-mini-search-preview": ModelCard(
        id="gpt-4o-mini-search-preview",
        provider="openai",
        display_name="GPT-4o Mini Search Preview",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
        quirks={"search_optimized": True},
    ),
    "gpt-4o-mini-search-preview-2025-03-11": ModelCard(
        id="gpt-4o-mini-search-preview-2025-03-11",
        provider="openai",
        display_name="GPT-4o Mini Search Preview (2025-03-11)",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
        quirks={"search_optimized": True},
    ),

    # ---------------------------------------------------------------------------
    # OpenAI GPT-4 Turbo Family
    # ---------------------------------------------------------------------------
    "gpt-4-turbo": ModelCard(
        id="gpt-4-turbo",
        provider="openai",
        display_name="GPT-4 Turbo",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),
    "gpt-4-turbo-2024-04-09": ModelCard(
        id="gpt-4-turbo-2024-04-09",
        provider="openai",
        display_name="GPT-4 Turbo (2024-04-09)",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),
    "gpt-4-turbo-preview": ModelCard(
        id="gpt-4-turbo-preview",
        provider="openai",
        display_name="GPT-4 Turbo Preview",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),
    "gpt-4-0125-preview": ModelCard(
        id="gpt-4-0125-preview",
        provider="openai",
        display_name="GPT-4 (0125 Preview)",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, vision=True, tool_use=True),
    ),
    "gpt-4-1106-preview": ModelCard(
        id="gpt-4-1106-preview",
        provider="openai",
        display_name="GPT-4 (1106 Preview)",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, vision=True, tool_use=True),
    ),
    "gpt-4": ModelCard(
        id="gpt-4",
        provider="openai",
        display_name="GPT-4",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=True),
    ),
    "gpt-4-0613": ModelCard(
        id="gpt-4-0613",
        provider="openai",
        display_name="GPT-4 (0613)",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=True),
    ),

    # ---------------------------------------------------------------------------
    # OpenAI GPT-4.1 Family
    # ---------------------------------------------------------------------------
    "gpt-4.1": ModelCard(
        id="gpt-4.1",
        provider="openai",
        display_name="GPT-4.1",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
    ),
    "gpt-4.1-2025-04-14": ModelCard(
        id="gpt-4.1-2025-04-14",
        provider="openai",
        display_name="GPT-4.1 (2025-04-14)",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
    ),
    "gpt-4.1-mini": ModelCard(
        id="gpt-4.1-mini",
        provider="openai",
        display_name="GPT-4.1 Mini",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
    ),
    "gpt-4.1-mini-2025-04-14": ModelCard(
        id="gpt-4.1-mini-2025-04-14",
        provider="openai",
        display_name="GPT-4.1 Mini (2025-04-14)",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
    ),
    "gpt-4.1-nano": ModelCard(
        id="gpt-4.1-nano",
        provider="openai",
        display_name="GPT-4.1 Nano",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
    ),
    "gpt-4.1-nano-2025-04-14": ModelCard(
        id="gpt-4.1-nano-2025-04-14",
        provider="openai",
        display_name="GPT-4.1 Nano (2025-04-14)",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
    ),

    # ---------------------------------------------------------------------------
    # OpenAI GPT-3.5 Family
    # ---------------------------------------------------------------------------
    "gpt-3.5-turbo": ModelCard(
        id="gpt-3.5-turbo",
        provider="openai",
        display_name="GPT-3.5 Turbo",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=True),
    ),
    "gpt-3.5-turbo-0125": ModelCard(
        id="gpt-3.5-turbo-0125",
        provider="openai",
        display_name="GPT-3.5 Turbo (0125)",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=True),
    ),
    "gpt-3.5-turbo-1106": ModelCard(
        id="gpt-3.5-turbo-1106",
        provider="openai",
        display_name="GPT-3.5 Turbo (1106)",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=True),
    ),
    "gpt-3.5-turbo-16k": ModelCard(
        id="gpt-3.5-turbo-16k",
        provider="openai",
        display_name="GPT-3.5 Turbo 16K",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=True),
    ),
    "gpt-3.5-turbo-instruct": ModelCard(
        id="gpt-3.5-turbo-instruct",
        provider="openai",
        display_name="GPT-3.5 Turbo Instruct",
        api_family="chat.completions",
        capabilities=Capabilities(text=True),
    ),
    "gpt-3.5-turbo-instruct-0914": ModelCard(
        id="gpt-3.5-turbo-instruct-0914",
        provider="openai",
        display_name="GPT-3.5 Turbo Instruct (0914)",
        api_family="chat.completions",
        capabilities=Capabilities(text=True),
    ),

    # ---------------------------------------------------------------------------
    # OpenAI GPT-5 Family
    # ---------------------------------------------------------------------------
    "gpt-5": ModelCard(
        id="gpt-5",
        provider="openai",
        display_name="GPT-5",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "gpt-5-2025-08-07": ModelCard(
        id="gpt-5-2025-08-07",
        provider="openai",
        display_name="GPT-5 (2025-08-07)",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "gpt-5-chat-latest": ModelCard(
        id="gpt-5-chat-latest",
        provider="openai",
        display_name="GPT-5 Chat Latest",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "gpt-5-codex": ModelCard(
        id="gpt-5-codex",
        provider="openai",
        display_name="GPT-5 Codex",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "gpt-5-mini": ModelCard(
        id="gpt-5-mini",
        provider="openai",
        display_name="GPT-5 Mini",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "gpt-5-mini-2025-08-07": ModelCard(
        id="gpt-5-mini-2025-08-07",
        provider="openai",
        display_name="GPT-5 Mini (2025-08-07)",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "gpt-5-nano": ModelCard(
        id="gpt-5-nano",
        provider="openai",
        display_name="GPT-5 Nano",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "gpt-5-nano-2025-08-07": ModelCard(
        id="gpt-5-nano-2025-08-07",
        provider="openai",
        display_name="GPT-5 Nano (2025-08-07)",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "gpt-5-pro": ModelCard(
        id="gpt-5-pro",
        provider="openai",
        display_name="GPT-5 Pro",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "gpt-5-pro-2025-10-06": ModelCard(
        id="gpt-5-pro-2025-10-06",
        provider="openai",
        display_name="GPT-5 Pro (2025-10-06)",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "gpt-5-search-api": ModelCard(
        id="gpt-5-search-api",
        provider="openai",
        display_name="GPT-5 Search API",
        api_family="chat.completions",
        capabilities=Capabilities(text=True),
        quirks={"no_temperature": True, "search_optimized": True, "needs_developer_role": True},
    ),
    "gpt-5-search-api-2025-10-14": ModelCard(
        id="gpt-5-search-api-2025-10-14",
        provider="openai",
        display_name="GPT-5 Search API (2025-10-14)",
        api_family="chat.completions",
        capabilities=Capabilities(text=True),
        quirks={"no_temperature": True, "search_optimized": True, "needs_developer_role": True},
    ),

    # ---------------------------------------------------------------------------
    # OpenAI GPT-5.1 Family
    # ---------------------------------------------------------------------------
    "gpt-5.1": ModelCard(
        id="gpt-5.1",
        provider="openai",
        display_name="GPT-5.1",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "gpt-5.1-2025-11-13": ModelCard(
        id="gpt-5.1-2025-11-13",
        provider="openai",
        display_name="GPT-5.1 (2025-11-13)",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "gpt-5.1-chat-latest": ModelCard(
        id="gpt-5.1-chat-latest",
        provider="openai",
        display_name="GPT-5.1 Chat Latest",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "gpt-5.1-codex": ModelCard(
        id="gpt-5.1-codex",
        provider="openai",
        display_name="GPT-5.1 Codex",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "gpt-5.1-codex-max": ModelCard(
        id="gpt-5.1-codex-max",
        provider="openai",
        display_name="GPT-5.1 Codex Max",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "gpt-5.1-codex-mini": ModelCard(
        id="gpt-5.1-codex-mini",
        provider="openai",
        display_name="GPT-5.1 Codex Mini",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True
        ),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),

    # ---------------------------------------------------------------------------
    # OpenAI GPT-5.2 Family
    # ---------------------------------------------------------------------------
    "gpt-5.2": ModelCard(
        id="gpt-5.2",
        provider="openai",
        display_name="GPT-5.2",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True,
            image_gen=True, image_edit=True
        ),
        quirks={"no_temperature": True, "reasoning_effort_enabled": True, "reasoning_effort_level": "low", "needs_developer_role": True},
    ),
    "gpt-5.2-2025-12-11": ModelCard(
        id="gpt-5.2-2025-12-11",
        provider="openai",
        display_name="GPT-5.2 (2025-12-11)",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True,
            image_gen=True, image_edit=True
        ),
        quirks={"no_temperature": True, "reasoning_effort_enabled": True, "reasoning_effort_level": "low", "needs_developer_role": True},
    ),
    "gpt-5.2-chat-latest": ModelCard(
        id="gpt-5.2-chat-latest",
        provider="openai",
        display_name="GPT-5.2 Chat Latest",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True,
            image_gen=True, image_edit=True
        ),
        quirks={"no_temperature": True, "reasoning_effort_enabled": True, "reasoning_effort_level": "low", "needs_developer_role": True},
    ),
    "gpt-5.2-pro": ModelCard(
        id="gpt-5.2-pro",
        provider="openai",
        display_name="GPT-5.2 Pro",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True,
            image_gen=True, image_edit=True
        ),
        quirks={"no_temperature": True, "reasoning_effort_enabled": True, "reasoning_effort_level": "low", "needs_developer_role": True},
    ),
    "gpt-5.2-pro-2025-12-11": ModelCard(
        id="gpt-5.2-pro-2025-12-11",
        provider="openai",
        display_name="GPT-5.2 Pro (2025-12-11)",
        api_family="responses",
        capabilities=Capabilities(
            text=True, vision=True, files=True, tool_use=True, web_search=True,
            image_gen=True, image_edit=True
        ),
        quirks={"no_temperature": True, "reasoning_effort_enabled": True, "reasoning_effort_level": "low", "needs_developer_role": True},
    ),

    # ---------------------------------------------------------------------------
    # OpenAI Reasoning Models (o1, o3, o4 series)
    # ---------------------------------------------------------------------------
    "o1": ModelCard(
        id="o1",
        provider="openai",
        display_name="o1",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=False),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "o1-2024-12-17": ModelCard(
        id="o1-2024-12-17",
        provider="openai",
        display_name="o1 (2024-12-17)",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=False),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
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
    "o1-pro": ModelCard(
        id="o1-pro",
        provider="openai",
        display_name="o1 Pro",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=False),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "o1-pro-2025-03-19": ModelCard(
        id="o1-pro-2025-03-19",
        provider="openai",
        display_name="o1 Pro (2025-03-19)",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=False),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "o3": ModelCard(
        id="o3",
        provider="openai",
        display_name="o3",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=True),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "o3-2025-04-16": ModelCard(
        id="o3-2025-04-16",
        provider="openai",
        display_name="o3 (2025-04-16)",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=True),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "o3-mini": ModelCard(
        id="o3-mini",
        provider="openai",
        display_name="o3-mini",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=True),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "o3-mini-2025-01-31": ModelCard(
        id="o3-mini-2025-01-31",
        provider="openai",
        display_name="o3-mini (2025-01-31)",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=True),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "o3-pro": ModelCard(
        id="o3-pro",
        provider="openai",
        display_name="o3 Pro",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=True),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "o3-pro-2025-06-10": ModelCard(
        id="o3-pro-2025-06-10",
        provider="openai",
        display_name="o3 Pro (2025-06-10)",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=True),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "o3-deep-research": ModelCard(
        id="o3-deep-research",
        provider="openai",
        display_name="o3 Deep Research",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, web_search=True, tool_use=False),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "o3-deep-research-2025-06-26": ModelCard(
        id="o3-deep-research-2025-06-26",
        provider="openai",
        display_name="o3 Deep Research (2025-06-26)",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, web_search=True, tool_use=False),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "o4-mini": ModelCard(
        id="o4-mini",
        provider="openai",
        display_name="o4-mini",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=True),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "o4-mini-2025-04-16": ModelCard(
        id="o4-mini-2025-04-16",
        provider="openai",
        display_name="o4-mini (2025-04-16)",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, tool_use=True),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "o4-mini-deep-research": ModelCard(
        id="o4-mini-deep-research",
        provider="openai",
        display_name="o4-mini Deep Research",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, web_search=True, tool_use=False),
        quirks={"no_temperature": True, "needs_developer_role": True},
    ),
    "o4-mini-deep-research-2025-06-26": ModelCard(
        id="o4-mini-deep-research-2025-06-26",
        provider="openai",
        display_name="o4-mini Deep Research (2025-06-26)",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, web_search=True, tool_use=False),
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
        capabilities=Capabilities(text=True, vision=True, audio_in=True, audio_out=True),
        quirks={"requires_audio_modality": True},
    ),
    "gpt-4o-audio-preview-2024-12-17": ModelCard(
        id="gpt-4o-audio-preview-2024-12-17",
        provider="openai",
        display_name="GPT-4o Audio Preview (2024-12-17)",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, vision=True, audio_in=True, audio_out=True),
        quirks={"requires_audio_modality": True},
    ),
    "gpt-4o-audio-preview-2025-06-03": ModelCard(
        id="gpt-4o-audio-preview-2025-06-03",
        provider="openai",
        display_name="GPT-4o Audio Preview (2025-06-03)",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, vision=True, audio_in=True, audio_out=True),
        quirks={"requires_audio_modality": True},
    ),
    "gpt-4o-mini-audio-preview": ModelCard(
        id="gpt-4o-mini-audio-preview",
        provider="openai",
        display_name="GPT-4o Mini Audio Preview",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, vision=True, audio_in=True, audio_out=True),
        quirks={"requires_audio_modality": True},
    ),
    "gpt-4o-mini-audio-preview-2024-12-17": ModelCard(
        id="gpt-4o-mini-audio-preview-2024-12-17",
        provider="openai",
        display_name="GPT-4o Mini Audio Preview (2024-12-17)",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, vision=True, audio_in=True, audio_out=True),
        quirks={"requires_audio_modality": True},
    ),
    "gpt-audio": ModelCard(
        id="gpt-audio",
        provider="openai",
        display_name="GPT Audio",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, audio_in=True, audio_out=True),
        quirks={"requires_audio_modality": True},
    ),
    "gpt-audio-2025-08-28": ModelCard(
        id="gpt-audio-2025-08-28",
        provider="openai",
        display_name="GPT Audio (2025-08-28)",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, audio_in=True, audio_out=True),
        quirks={"requires_audio_modality": True},
    ),
    "gpt-audio-mini": ModelCard(
        id="gpt-audio-mini",
        provider="openai",
        display_name="GPT Audio Mini",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, audio_in=True, audio_out=True),
        quirks={"requires_audio_modality": True},
    ),
    "gpt-audio-mini-2025-10-06": ModelCard(
        id="gpt-audio-mini-2025-10-06",
        provider="openai",
        display_name="GPT Audio Mini (2025-10-06)",
        api_family="chat.completions",
        capabilities=Capabilities(text=True, audio_in=True, audio_out=True),
        quirks={"requires_audio_modality": True},
    ),

    # ---------------------------------------------------------------------------
    # OpenAI Realtime Models
    # ---------------------------------------------------------------------------
    "gpt-realtime": ModelCard(
        id="gpt-realtime",
        provider="openai",
        display_name="GPT Realtime",
        api_family="realtime",
        capabilities=Capabilities(text=True, audio_in=True, audio_out=True),
        quirks={"realtime_websocket": True},
    ),
    "gpt-realtime-2025-08-28": ModelCard(
        id="gpt-realtime-2025-08-28",
        provider="openai",
        display_name="GPT Realtime (2025-08-28)",
        api_family="realtime",
        capabilities=Capabilities(text=True, audio_in=True, audio_out=True),
        quirks={"realtime_websocket": True},
    ),
    "gpt-realtime-mini": ModelCard(
        id="gpt-realtime-mini",
        provider="openai",
        display_name="GPT Realtime Mini",
        api_family="realtime",
        capabilities=Capabilities(text=True, audio_in=True, audio_out=True),
        quirks={"realtime_websocket": True},
    ),
    "gpt-realtime-mini-2025-10-06": ModelCard(
        id="gpt-realtime-mini-2025-10-06",
        provider="openai",
        display_name="GPT Realtime Mini (2025-10-06)",
        api_family="realtime",
        capabilities=Capabilities(text=True, audio_in=True, audio_out=True),
        quirks={"realtime_websocket": True},
    ),

    # ---------------------------------------------------------------------------
    # OpenAI Transcription Models
    # ---------------------------------------------------------------------------
    "gpt-4o-transcribe": ModelCard(
        id="gpt-4o-transcribe",
        provider="openai",
        display_name="GPT-4o Transcribe",
        api_family="transcription",
        capabilities=Capabilities(text=True, audio_in=True),
    ),
    "gpt-4o-transcribe-diarize": ModelCard(
        id="gpt-4o-transcribe-diarize",
        provider="openai",
        display_name="GPT-4o Transcribe Diarize",
        api_family="transcription",
        capabilities=Capabilities(text=True, audio_in=True),
    ),
    "gpt-4o-mini-transcribe": ModelCard(
        id="gpt-4o-mini-transcribe",
        provider="openai",
        display_name="GPT-4o Mini Transcribe",
        api_family="transcription",
        capabilities=Capabilities(text=True, audio_in=True),
    ),
    "whisper-1": ModelCard(
        id="whisper-1",
        provider="openai",
        display_name="Whisper",
        api_family="transcription",
        capabilities=Capabilities(text=False, audio_in=True),
    ),

    # ---------------------------------------------------------------------------
    # OpenAI TTS Models
    # ---------------------------------------------------------------------------
    "tts-1": ModelCard(
        id="tts-1",
        provider="openai",
        display_name="TTS-1",
        api_family="tts",
        capabilities=Capabilities(text=False, audio_out=True),
    ),
    "tts-1-1106": ModelCard(
        id="tts-1-1106",
        provider="openai",
        display_name="TTS-1 (1106)",
        api_family="tts",
        capabilities=Capabilities(text=False, audio_out=True),
    ),
    "tts-1-hd": ModelCard(
        id="tts-1-hd",
        provider="openai",
        display_name="TTS-1 HD",
        api_family="tts",
        capabilities=Capabilities(text=False, audio_out=True),
    ),
    "tts-1-hd-1106": ModelCard(
        id="tts-1-hd-1106",
        provider="openai",
        display_name="TTS-1 HD (1106)",
        api_family="tts",
        capabilities=Capabilities(text=False, audio_out=True),
    ),
    "gpt-4o-mini-tts": ModelCard(
        id="gpt-4o-mini-tts",
        provider="openai",
        display_name="GPT-4o Mini TTS",
        api_family="tts",
        capabilities=Capabilities(text=False, audio_out=True),
    ),

    # ---------------------------------------------------------------------------
    # OpenAI Image Models
    # ---------------------------------------------------------------------------
    "dall-e-2": ModelCard(
        id="dall-e-2",
        provider="openai",
        display_name="DALL-E 2",
        api_family="images",
        capabilities=Capabilities(text=False, image_gen=True),
        image_sizes={"256x256", "512x512", "1024x1024"},
    ),
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
    # OpenAI Video Models
    # ---------------------------------------------------------------------------
    "sora-2": ModelCard(
        id="sora-2",
        provider="openai",
        display_name="Sora 2",
        api_family="video",
        capabilities=Capabilities(text=False),
        quirks={"video_generation": True},
    ),
    "sora-2-pro": ModelCard(
        id="sora-2-pro",
        provider="openai",
        display_name="Sora 2 Pro",
        api_family="video",
        capabilities=Capabilities(text=False),
        quirks={"video_generation": True},
    ),

    # ---------------------------------------------------------------------------
    # OpenAI Embedding Models (non-chat, included for completeness)
    # ---------------------------------------------------------------------------
    "text-embedding-3-large": ModelCard(
        id="text-embedding-3-large",
        provider="openai",
        display_name="Text Embedding 3 Large",
        api_family="embeddings",
        capabilities=Capabilities(text=False),
    ),
    "text-embedding-3-small": ModelCard(
        id="text-embedding-3-small",
        provider="openai",
        display_name="Text Embedding 3 Small",
        api_family="embeddings",
        capabilities=Capabilities(text=False),
    ),
    "text-embedding-ada-002": ModelCard(
        id="text-embedding-ada-002",
        provider="openai",
        display_name="Text Embedding Ada 002",
        api_family="embeddings",
        capabilities=Capabilities(text=False),
    ),

    # ---------------------------------------------------------------------------
    # OpenAI Codex Models
    # ---------------------------------------------------------------------------
    "codex-mini-latest": ModelCard(
        id="codex-mini-latest",
        provider="openai",
        display_name="Codex Mini Latest",
        api_family="responses",
        capabilities=Capabilities(text=True, tool_use=True),
    ),

    # ===========================================================================
    # Gemini Models
    # ===========================================================================

    # ---------------------------------------------------------------------------
    # Gemini 2.0 Flash Family
    # ---------------------------------------------------------------------------
    "gemini-2.0-flash": ModelCard(
        id="gemini-2.0-flash",
        provider="gemini",
        display_name="Gemini 2.0 Flash",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),
    "gemini-2.0-flash-001": ModelCard(
        id="gemini-2.0-flash-001",
        provider="gemini",
        display_name="Gemini 2.0 Flash (001)",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),
    "gemini-2.0-flash-exp": ModelCard(
        id="gemini-2.0-flash-exp",
        provider="gemini",
        display_name="Gemini 2.0 Flash Exp",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),
    "gemini-2.0-flash-lite": ModelCard(
        id="gemini-2.0-flash-lite",
        provider="gemini",
        display_name="Gemini 2.0 Flash Lite",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),
    "gemini-2.0-flash-lite-001": ModelCard(
        id="gemini-2.0-flash-lite-001",
        provider="gemini",
        display_name="Gemini 2.0 Flash Lite (001)",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),
    "gemini-2.0-flash-lite-preview": ModelCard(
        id="gemini-2.0-flash-lite-preview",
        provider="gemini",
        display_name="Gemini 2.0 Flash Lite Preview",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),
    "gemini-2.0-flash-lite-preview-02-05": ModelCard(
        id="gemini-2.0-flash-lite-preview-02-05",
        provider="gemini",
        display_name="Gemini 2.0 Flash Lite Preview (02-05)",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),

    # ---------------------------------------------------------------------------
    # Gemini 2.5 Family
    # ---------------------------------------------------------------------------
    "gemini-2.5-flash": ModelCard(
        id="gemini-2.5-flash",
        provider="gemini",
        display_name="Gemini 2.5 Flash",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),
    "gemini-2.5-flash-lite": ModelCard(
        id="gemini-2.5-flash-lite",
        provider="gemini",
        display_name="Gemini 2.5 Flash Lite",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),
    "gemini-2.5-flash-lite-preview-09-2025": ModelCard(
        id="gemini-2.5-flash-lite-preview-09-2025",
        provider="gemini",
        display_name="Gemini 2.5 Flash Lite Preview",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),
    "gemini-2.5-flash-preview-09-2025": ModelCard(
        id="gemini-2.5-flash-preview-09-2025",
        provider="gemini",
        display_name="Gemini 2.5 Flash Preview",
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
    "gemini-2.5-computer-use-preview-10-2025": ModelCard(
        id="gemini-2.5-computer-use-preview-10-2025",
        provider="gemini",
        display_name="Gemini 2.5 Computer Use Preview",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
        quirks={"computer_use": True},
    ),

    # ---------------------------------------------------------------------------
    # Gemini 2.5 TTS Models
    # ---------------------------------------------------------------------------
    "gemini-2.5-flash-preview-tts": ModelCard(
        id="gemini-2.5-flash-preview-tts",
        provider="gemini",
        display_name="Gemini 2.5 Flash TTS",
        api_family="tts",
        capabilities=Capabilities(text=True, audio_out=True),
    ),
    "gemini-2.5-pro-preview-tts": ModelCard(
        id="gemini-2.5-pro-preview-tts",
        provider="gemini",
        display_name="Gemini 2.5 Pro TTS",
        api_family="tts",
        capabilities=Capabilities(text=True, audio_out=True),
    ),

    # ---------------------------------------------------------------------------
    # Gemini 2.5 Image Models
    # ---------------------------------------------------------------------------
    "gemini-2.5-flash-image": ModelCard(
        id="gemini-2.5-flash-image",
        provider="gemini",
        display_name="Gemini 2.5 Flash Image",
        capabilities=Capabilities(text=True, image_gen=True, image_edit=True),
        quirks={"multimodal_image_gen": True},
    ),
    "gemini-2.5-flash-image-preview": ModelCard(
        id="gemini-2.5-flash-image-preview",
        provider="gemini",
        display_name="Gemini 2.5 Flash Image Preview",
        capabilities=Capabilities(text=True, image_gen=True, image_edit=True),
        quirks={"multimodal_image_gen": True},
    ),

    # ---------------------------------------------------------------------------
    # Gemini 3 Family
    # ---------------------------------------------------------------------------
    "gemini-3-pro-preview": ModelCard(
        id="gemini-3-pro-preview",
        provider="gemini",
        display_name="Gemini 3 Pro Preview",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),
    "gemini-3-pro-image-preview": ModelCard(
        id="gemini-3-pro-image-preview",
        provider="gemini",
        display_name="Gemini 3 Pro Image Preview",
        capabilities=Capabilities(text=True, image_gen=True, image_edit=True, tool_use=True),
        quirks={"multimodal_image_gen": True},
    ),

    # ---------------------------------------------------------------------------
    # Gemini Latest/Aliases
    # ---------------------------------------------------------------------------
    "gemini-flash-latest": ModelCard(
        id="gemini-flash-latest",
        provider="gemini",
        display_name="Gemini Flash Latest",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),
    "gemini-flash-lite-latest": ModelCard(
        id="gemini-flash-lite-latest",
        provider="gemini",
        display_name="Gemini Flash Lite Latest",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),
    "gemini-pro-latest": ModelCard(
        id="gemini-pro-latest",
        provider="gemini",
        display_name="Gemini Pro Latest",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),

    # ---------------------------------------------------------------------------
    # Gemini Legacy Models (1.5 and earlier)
    # ---------------------------------------------------------------------------
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
    "gemini-exp-1206": ModelCard(
        id="gemini-exp-1206",
        provider="gemini",
        display_name="Gemini Exp (1206)",
        capabilities=Capabilities(
            text=True, vision=True, tool_use=True, web_search=True
        ),
    ),

    # ---------------------------------------------------------------------------
    # Gemini Specialized Models
    # ---------------------------------------------------------------------------
    "deep-research-pro-preview-12-2025": ModelCard(
        id="deep-research-pro-preview-12-2025",
        provider="gemini",
        display_name="Deep Research Pro Preview",
        capabilities=Capabilities(text=True, web_search=True),
        quirks={"deep_research": True},
    ),
    "gemini-robotics-er-1.5-preview": ModelCard(
        id="gemini-robotics-er-1.5-preview",
        provider="gemini",
        display_name="Gemini Robotics ER 1.5 Preview",
        capabilities=Capabilities(text=True, vision=True),
        quirks={"robotics": True},
    ),

    # ---------------------------------------------------------------------------
    # Gemma Models (open models via Gemini API)
    # ---------------------------------------------------------------------------
    "gemma-3-1b-it": ModelCard(
        id="gemma-3-1b-it",
        provider="gemini",
        display_name="Gemma 3 1B IT",
        capabilities=Capabilities(text=True),
    ),
    "gemma-3-4b-it": ModelCard(
        id="gemma-3-4b-it",
        provider="gemini",
        display_name="Gemma 3 4B IT",
        capabilities=Capabilities(text=True),
    ),
    "gemma-3-12b-it": ModelCard(
        id="gemma-3-12b-it",
        provider="gemini",
        display_name="Gemma 3 12B IT",
        capabilities=Capabilities(text=True),
    ),
    "gemma-3-27b-it": ModelCard(
        id="gemma-3-27b-it",
        provider="gemini",
        display_name="Gemma 3 27B IT",
        capabilities=Capabilities(text=True),
    ),
    "gemma-3n-e2b-it": ModelCard(
        id="gemma-3n-e2b-it",
        provider="gemini",
        display_name="Gemma 3N E2B IT",
        capabilities=Capabilities(text=True),
    ),
    "gemma-3n-e4b-it": ModelCard(
        id="gemma-3n-e4b-it",
        provider="gemini",
        display_name="Gemma 3N E4B IT",
        capabilities=Capabilities(text=True),
    ),

    # ===========================================================================
    # Grok Models
    # ===========================================================================
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
    "grok-2-image-1212": ModelCard(
        id="grok-2-image-1212",
        provider="grok",
        display_name="Grok-2 Image (1212)",
        api_family="images",
        capabilities=Capabilities(text=False, image_gen=True),
    ),
    "grok-3": ModelCard(
        id="grok-3",
        provider="grok",
        display_name="Grok-3",
        capabilities=Capabilities(text=True, vision=True, tool_use=True, web_search=False),
    ),
    "grok-3-mini": ModelCard(
        id="grok-3-mini",
        provider="grok",
        display_name="Grok-3 Mini",
        capabilities=Capabilities(text=True, vision=True, tool_use=True, web_search=False),
    ),
    "grok-4-0709": ModelCard(
        id="grok-4-0709",
        provider="grok",
        display_name="Grok-4 (0709)",
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
    "grok-code-fast-1": ModelCard(
        id="grok-code-fast-1",
        provider="grok",
        display_name="Grok Code Fast",
        capabilities=Capabilities(text=True, tool_use=True, web_search=True),
    ),

    # ===========================================================================
    # Claude Models
    # ===========================================================================
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

    # ===========================================================================
    # Perplexity Models
    # ===========================================================================
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
