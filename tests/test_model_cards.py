"""
test_model_cards.py – Unit tests for the model_cards package.

Tests cover:
- ModelCard and Capabilities dataclasses
- Built-in card catalog lookup
- Custom model card synthesis from legacy format
- Card registration and listing
- ToolManager integration with card-first checks
"""

import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from model_cards import (
    ModelCard,
    Capabilities,
    get_card,
    list_cards,
    register_card,
    unregister_card,
    clear_custom_cards,
)
from model_cards.catalog import BUILTIN_CARDS
from model_cards.overrides import apply_override_to_card


class TestCapabilities:
    """Tests for the Capabilities dataclass."""

    def test_default_capabilities(self):
        """Default capabilities should have text=True, everything else False."""
        caps = Capabilities()
        assert caps.text is True
        assert caps.vision is False
        assert caps.files is False
        assert caps.tool_use is False
        assert caps.web_search is False
        assert caps.audio_in is False
        assert caps.audio_out is False
        assert caps.image_gen is False
        assert caps.image_edit is False

    def test_custom_capabilities(self):
        """Can create capabilities with custom flags."""
        caps = Capabilities(text=True, vision=True, tool_use=True)
        assert caps.text is True
        assert caps.vision is True
        assert caps.tool_use is True
        assert caps.image_gen is False


class TestModelCard:
    """Tests for the ModelCard dataclass."""

    def test_minimal_card(self):
        """Can create a card with just id and provider."""
        card = ModelCard(id="test-model", provider="openai")
        assert card.id == "test-model"
        assert card.provider == "openai"
        assert card.display_name is None
        assert card.api_family == "chat.completions"

    def test_supports_tools(self):
        """supports_tools() returns capabilities.tool_use."""
        card_with_tools = ModelCard(
            id="chat-model",
            provider="openai",
            capabilities=Capabilities(text=True, tool_use=True),
        )
        card_without_tools = ModelCard(
            id="basic-model",
            provider="openai",
            capabilities=Capabilities(text=True, tool_use=False),
        )
        assert card_with_tools.supports_tools() is True
        assert card_without_tools.supports_tools() is False

    def test_is_image_model(self):
        """is_image_model() returns True only for image-gen models without text."""
        image_card = ModelCard(
            id="dall-e-3",
            provider="openai",
            capabilities=Capabilities(text=False, image_gen=True),
        )
        multimodal_card = ModelCard(
            id="gemini-flash-image",
            provider="gemini",
            capabilities=Capabilities(text=True, image_gen=True),
        )
        chat_card = ModelCard(
            id="gpt-4o",
            provider="openai",
            capabilities=Capabilities(text=True),
        )
        assert image_card.is_image_model() is True
        assert multimodal_card.is_image_model() is False  # Has text capability
        assert chat_card.is_image_model() is False

    def test_is_chat_model(self):
        """is_chat_model() returns True for text models that aren't image-only."""
        chat_card = ModelCard(
            id="gpt-4o",
            provider="openai",
            capabilities=Capabilities(text=True, tool_use=True),
        )
        image_card = ModelCard(
            id="dall-e-3",
            provider="openai",
            capabilities=Capabilities(text=False, image_gen=True),
        )
        assert chat_card.is_chat_model() is True
        assert image_card.is_chat_model() is False

    def test_get_display_name(self):
        """get_display_name() returns display_name or falls back to id."""
        card_with_name = ModelCard(
            id="gpt-4o-mini",
            provider="openai",
            display_name="GPT-4o Mini",
        )
        card_without_name = ModelCard(id="gpt-4o-mini", provider="openai")
        assert card_with_name.get_display_name() == "GPT-4o Mini"
        assert card_without_name.get_display_name() == "gpt-4o-mini"


class TestBuiltinCatalog:
    """Tests for the built-in card catalog."""

    def test_catalog_not_empty(self):
        """Built-in catalog should contain cards."""
        assert len(BUILTIN_CARDS) > 0

    def test_common_models_present(self):
        """Common models should be in the catalog."""
        expected_models = [
            "gpt-4o",
            "gpt-4o-mini",
            "dall-e-3",
            "gemini-2.5-flash",
            "grok-3",
            "claude-sonnet-4-5",
            "sonar",
        ]
        for model_id in expected_models:
            assert model_id in BUILTIN_CARDS, f"{model_id} should be in catalog"

    def test_image_models_flagged_correctly(self):
        """Image models should have correct capabilities."""
        dalle = BUILTIN_CARDS.get("dall-e-3")
        assert dalle is not None
        assert dalle.is_image_model() is True
        assert dalle.capabilities.image_gen is True
        assert dalle.capabilities.text is False

    def test_chat_models_have_tool_support(self):
        """Major chat models should have tool_use capability."""
        chat_models = ["gpt-4o", "gpt-4o-mini", "gemini-2.5-flash", "grok-3", "claude-sonnet-4-5"]
        for model_id in chat_models:
            card = BUILTIN_CARDS.get(model_id)
            assert card is not None, f"{model_id} should be in catalog"
            assert card.capabilities.tool_use is True, f"{model_id} should support tools"

    def test_reasoning_models_quirks(self):
        """Reasoning models (o1, o3) should require developer role and leave temperature unset."""
        for model_id in ["o1-mini", "o1-preview", "o3", "o3-mini"]:
            card = BUILTIN_CARDS.get(model_id)
            assert card is not None, f"{model_id} should be in catalog"
            assert card.temperature is None
            assert card.quirks.get("needs_developer_role") is True


class TestCardLookup:
    """Tests for the get_card() function."""

    def setup_method(self):
        """Clear custom cards before each test."""
        clear_custom_cards()

    def teardown_method(self):
        """Clear custom cards after each test."""
        clear_custom_cards()

    def test_builtin_card_lookup(self):
        """Can look up built-in cards."""
        card = get_card("gpt-4o-mini")
        assert card is not None
        assert card.provider == "openai"
        assert card.capabilities.tool_use is True

    def test_unknown_model_returns_none(self):
        """Unknown models return None."""
        card = get_card("unknown-model-xyz-12345")
        assert card is None

    def test_custom_model_synthesized(self):
        """Custom models are synthesized from config dict."""
        custom_models = {
            "my-custom-model": {
                "endpoint": "https://api.example.com/v1",
                "api_type": "chat.completions",
                "display_name": "My Custom Model",
            }
        }
        card = get_card("my-custom-model", custom_models)
        assert card is not None
        assert card.provider == "custom"
        assert card.display_name == "My Custom Model"
        assert card.base_url == "https://api.example.com/v1"
        assert card.capabilities.text is True
        assert card.capabilities.tool_use is True

    def test_custom_image_model_synthesized(self):
        """Custom image models get correct capabilities."""
        custom_models = {
            "my-image-model": {
                "endpoint": "https://api.example.com/v1",
                "api_type": "images",
            }
        }
        card = get_card("my-image-model", custom_models)
        assert card is not None
        assert card.is_image_model() is True
        assert card.capabilities.image_gen is True
        assert card.capabilities.text is False

    def test_registered_card_takes_precedence(self):
        """Registered custom cards take precedence over built-in."""
        custom_card = ModelCard(
            id="gpt-4o-mini",
            provider="custom",
            display_name="My Override",
            capabilities=Capabilities(text=True, tool_use=False),
        )
        register_card(custom_card)

        card = get_card("gpt-4o-mini")
        assert card.provider == "custom"
        assert card.display_name == "My Override"
        assert card.capabilities.tool_use is False

    def test_unregister_card(self):
        """Can unregister custom cards."""
        custom_card = ModelCard(id="test-card", provider="custom")
        register_card(custom_card)
        assert get_card("test-card") is not None

        result = unregister_card("test-card")
        assert result is True
        assert get_card("test-card") is None

    def test_override_applies_temperature(self):
        """Overrides should carry through temperature configuration."""
        base_card = ModelCard(id="temp-model", provider="openai")
        override = {"temperature": 0.55}
        updated = apply_override_to_card(base_card, override)
        assert updated.temperature == 0.55

    def test_list_cards(self):
        """list_cards() returns all cards."""
        all_cards = list_cards()
        assert len(all_cards) >= len(BUILTIN_CARDS)
        assert "gpt-4o" in all_cards
        assert "dall-e-3" in all_cards


class TestToolManagerIntegration:
    """Tests for ToolManager using model cards."""

    def setup_method(self):
        """Clear custom cards and import ToolManager."""
        clear_custom_cards()
        from tools import ToolManager
        self.ToolManager = ToolManager

    def teardown_method(self):
        """Clear custom cards after each test."""
        clear_custom_cards()

    def test_image_model_does_not_support_tools(self):
        """Image-only models should not be offered tools."""
        tm = self.ToolManager(image_tool_enabled=True)
        assert tm.supports_image_tools("dall-e-3") is False
        assert tm.supports_image_tools("gpt-image-1") is False

    def test_chat_model_supports_tools(self):
        """Chat models with tool_use capability should support tools."""
        tm = self.ToolManager(image_tool_enabled=True)
        assert tm.supports_image_tools("gpt-4o-mini") is True
        assert tm.supports_image_tools("gpt-4o") is True

    def test_reasoning_model_tool_support(self):
        """o1 models don't support tools, but o3/o4 models do."""
        tm = self.ToolManager(image_tool_enabled=True)
        # o1 series doesn't support tools
        assert tm.supports_image_tools("o1-mini") is False
        assert tm.supports_image_tools("o1-preview") is False
        # o3 and o4 series support tools
        assert tm.supports_image_tools("o3-mini") is True
        assert tm.supports_image_tools("o4-mini") is True

    def test_tool_disabled_globally(self):
        """When image tool is disabled, no models support it."""
        tm = self.ToolManager(image_tool_enabled=False)
        assert tm.supports_image_tools("gpt-4o-mini") is False

    def test_get_provider_from_card(self):
        """get_provider_name_for_model uses card data."""
        tm = self.ToolManager()
        assert tm.get_provider_name_for_model("gpt-4o-mini") == "openai"
        assert tm.get_provider_name_for_model("gemini-2.5-flash") == "gemini"
        assert tm.get_provider_name_for_model("grok-3") == "grok"
        assert tm.get_provider_name_for_model("claude-sonnet-4-5") == "claude"
        assert tm.get_provider_name_for_model("sonar") == "perplexity"

    def test_is_image_model_from_card(self):
        """is_image_model_for_provider uses card data."""
        tm = self.ToolManager()
        assert tm.is_image_model_for_provider("dall-e-3", "openai") is True
        assert tm.is_image_model_for_provider("gpt-4o-mini", "openai") is False
        assert tm.is_image_model_for_provider("grok-2-image-1212", "grok") is True

    def test_unknown_model_defaults_to_openai(self):
        """Unknown models default to openai provider."""
        tm = self.ToolManager(image_tool_enabled=True)
        # Unknown models not in the catalog default to openai
        assert tm.get_provider_name_for_model("some-unknown-model") == "openai"
        assert tm.get_provider_name_for_model("future-model-xyz") == "openai"

    def test_music_tool_uses_card(self):
        """Music tool support also uses card data."""
        tm = self.ToolManager(music_tool_enabled=True)
        assert tm.supports_music_tools("gpt-4o-mini") is True
        assert tm.supports_music_tools("dall-e-3") is False
        assert tm.supports_music_tools("o1-mini") is False  # o1 doesn't support tools

    def test_read_aloud_tool_uses_card(self):
        """Read aloud tool support also uses card data."""
        tm = self.ToolManager(read_aloud_tool_enabled=True)
        assert tm.supports_read_aloud_tools("gpt-4o-mini") is True
        assert tm.supports_read_aloud_tools("dall-e-3") is False
        assert tm.supports_read_aloud_tools("o1-mini") is False  # o1 doesn't support tools


class TestPhase2ProviderIntegration:
    """Tests for Phase 2: Provider API routing via model cards."""

    def setup_method(self):
        """Clear custom cards before each test."""
        clear_custom_cards()

    def teardown_method(self):
        """Clear custom cards after each test."""
        clear_custom_cards()

    def test_web_search_capability_openai(self):
        """OpenAI chat models should have web_search capability."""
        card = get_card("gpt-4o")
        assert card is not None
        assert card.capabilities.web_search is True

        card = get_card("gpt-4o-mini")
        assert card is not None
        assert card.capabilities.web_search is True

    def test_web_search_capability_grok(self):
        """Grok chat models should have web_search capability."""
        card = get_card("grok-3")
        assert card is not None
        assert card.capabilities.web_search is True

        card = get_card("grok-2-1212")
        assert card is not None
        assert card.capabilities.web_search is True

    def test_web_search_capability_gemini(self):
        """Gemini 2.x+ models should have web_search capability."""
        card = get_card("gemini-2.5-flash")
        assert card is not None
        assert card.capabilities.web_search is True

    def test_image_models_no_web_search(self):
        """Image-only models should not have web_search capability."""
        card = get_card("dall-e-3")
        assert card is not None
        assert card.capabilities.web_search is False

        card = get_card("grok-2-image-1212")
        assert card is not None
        assert card.capabilities.web_search is False

    def test_audio_model_quirks(self):
        """Audio models should have requires_audio_modality quirk."""
        card = get_card("gpt-4o-audio-preview")
        assert card is not None
        assert card.quirks.get("requires_audio_modality") is True

        card = get_card("gpt-4o-mini-audio-preview")
        assert card is not None
        assert card.quirks.get("requires_audio_modality") is True

    def test_reasoning_model_quirks(self):
        """Reasoning models should have needs_developer_role and unset temperature."""
        for model_id in ["o1-mini", "o1-preview", "o3", "o3-mini"]:
            card = get_card(model_id)
            assert card is not None, f"{model_id} should be in catalog"
            assert card.quirks.get("needs_developer_role") is True, f"{model_id} should need developer role"
            assert card.temperature is None, f"{model_id} should not set temperature by default"

    def test_gpt5_temperature_default(self):
        """GPT-5 models should leave temperature unset by default."""
        for model_id in ["gpt-5.1", "gpt-5.1-chat-latest", "gpt-5-pro"]:
            card = get_card(model_id)
            assert card is not None, f"{model_id} should be in catalog"
            assert card.temperature is None, f"{model_id} should not set temperature by default"

    def test_api_family_routing(self):
        """Models should have correct api_family for routing."""
        # Responses API models
        card = get_card("gpt-4o")
        assert card.api_family == "responses"

        # Chat completions models (reasoning)
        card = get_card("o3")
        assert card.api_family == "chat.completions"

        # Image models
        card = get_card("dall-e-3")
        assert card.api_family == "images"

    def test_perplexity_always_web_search(self):
        """Perplexity models should have always_web_search quirk."""
        for model_id in ["sonar", "sonar-pro", "sonar-reasoning"]:
            card = get_card(model_id)
            assert card is not None, f"{model_id} should be in catalog"
            assert card.capabilities.web_search is True
            assert card.quirks.get("always_web_search") is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
