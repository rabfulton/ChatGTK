"""Deprecation presentation must not change model availability or routing."""

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from model_cards import get_card, get_model_deprecation, loader, overrides
from model_cards.lifecycle import _OPENAI_GROUPS, OPENAI_DEPRECATIONS


@pytest.fixture(autouse=True)
def isolate_cards(monkeypatch):
    monkeypatch.setattr(loader, "_custom_cards", {})
    monkeypatch.setattr(loader, "_discovered_cards", {})
    monkeypatch.setattr(overrides, "load_overrides", dict)


@pytest.mark.parametrize(
    "model, shutdown",
    [
        ("tts-1", "2027-01-06"),
        ("gpt-4o-mini-tts-2025-12-15", "2027-01-06"),
        ("gpt-realtime-mini", "2027-01-20"),
        ("gpt-realtime-mini-2025-10-06", "2026-07-23"),
        ("gpt-4o-mini-transcribe", "2027-02-26"),
        ("gpt-5.1", "2027-04-01"),
        ("gpt-image-1-mini", "2026-12-01"),
        ("dall-e-3", "2026-05-12"),
    ],
)
def test_documented_shutdowns_are_provider_specific(model, shutdown):
    info = get_model_deprecation(model, "openai")
    assert info["shutdown_date"] == shutdown
    assert info["replacement_model"]
    assert get_model_deprecation(model, "custom") is None


@pytest.mark.parametrize(
    "model",
    [
        "gpt-realtime-2.1-mini",
        "gpt-audio-1.5",
        "gpt-5.2",
        "gpt-image-2.6-sunburst",
        "unknown-model",
        "openai/tts-1",
    ],
)
def test_other_models_do_not_inherit_deprecation_from_names(model):
    assert get_model_deprecation(model, "openai") is None


def test_metadata_covers_new_ids_without_assigning_unknown_capabilities():
    model = "gpt-5.4-nano-2026-03-17"
    assert get_card(model) is None
    assert get_model_deprecation(model, "openai")["shutdown_date"] == "2027-04-01"
    assert get_card(model) is None


def test_existing_card_flags_and_explicit_overrides_are_respected(monkeypatch):
    assert get_model_deprecation("grok-3", "grok")["replacement_model"] == "grok-4.3"
    monkeypatch.setattr(
        overrides,
        "load_overrides",
        lambda: {
            "tts-1": {"quirks": {"deprecated": False}},
            "private-model": {"provider": "custom", "quirks": {"deprecated": True}},
        },
    )
    assert get_model_deprecation("tts-1", "openai") is None
    assert get_model_deprecation("private-model", "custom")["deprecated"]


def test_lifecycle_lookup_preserves_routing_and_returns_independent_metadata():
    before = get_card("tts-1")
    info = get_model_deprecation("tts-1", "openai")
    info["shutdown_date"] = "changed"
    assert get_model_deprecation("tts-1", "openai")["shutdown_date"] == "2027-01-06"
    assert get_card("tts-1") == before
    assert before.api_family == "tts"


def test_deprecation_table_has_no_duplicates_or_invalid_dates():
    identifiers = [model for _, _, models in _OPENAI_GROUPS for model in models]
    assert len(identifiers) == len(set(identifiers))
    for info in OPENAI_DEPRECATIONS.values():
        date.fromisoformat(info["shutdown_date"])
