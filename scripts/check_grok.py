#!/usr/bin/env python3
"""Check live xAI listings and optionally run a small, billable search request."""

import argparse
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_providers import GrokProvider
from model_cards import get_card
from model_cards.catalog import BUILTIN_CARDS
from model_cards.grok import (
    GROK_UNSUPPORTED_MODEL_PREFIXES, register_grok_model_aliases,
)


def format_api_error(action, exc, secret):
    """Include the server's error message while redacting the configured key."""
    body = getattr(exc, "body", None)
    detail = body.get("error", body) if isinstance(body, dict) else body
    if isinstance(detail, dict):
        detail = detail.get("message") or detail.get("error") or detail.get("code")
    if not isinstance(detail, str) or not detail:
        detail = str(exc)
    message = (
        f"{action} failed: {type(exc).__name__} "
        f"(HTTP {getattr(exc, 'status_code', 'unknown')}): {detail}"
    )
    if secret:
        message = message.replace(secret, "[REDACTED]")
    return message[:2000]


def main():
    """Print model availability and card mismatches without exposing credentials."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="grok-latest")
    parser.add_argument(
        "--search", action="store_true",
        help="Also run one small chat request with web/X search (API charges apply).",
    )
    parser.add_argument(
        "--check-search-toggle", action="store_true",
        help="Run search-on then search-off turns (two billable API requests).",
    )
    args = parser.parse_args()
    key = os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY")
    if not key or not key.strip():
        parser.error("Export XAI_API_KEY or GROK_API_KEY in this shell first.")
    key = key.strip()

    provider = GrokProvider()
    provider.initialize(key)
    # Bound live diagnostics and avoid retrying billable requests.
    provider.client = provider.client.with_options(timeout=60, max_retries=0)
    errors = []
    model_ids = set()
    alias_ids = set()
    warnings = []
    report = {"endpoint": provider.BASE_URL, "requested_model": args.model}
    try:
        # These checks deliberately bypass the provider's curated fallback:
        # an outage or an empty response must be visible in the report.
        try:
            model_ids = {model.id for model in provider.client.models.list()}
            report["api_model_ids"] = sorted(model_ids)
            if not model_ids:
                errors.append("GET /models returned an empty list")
        except Exception as exc:
            errors.append(format_api_error("GET /models", exc, key))

        try:
            metadata = provider.client.get("/language-models", cast_to=dict[str, Any])
            register_grok_model_aliases(metadata)
            for model in metadata.get("models", []):
                if model.get("id"):
                    model_ids.add(model["id"])
                alias_ids.update(model.get("aliases") or [])
            report["api_language_aliases"] = sorted(alias_ids)
        except Exception as exc:
            errors.append(format_api_error("GET /language-models", exc, key))

        try:
            detail = provider.client.models.retrieve(args.model)
            report["resolved_model_id"] = detail.id
        except Exception as exc:
            message = format_api_error(f"GET /models/{args.model}", exc, key)
            if getattr(exc, "status_code", None) == 404:
                warnings.append(message + "; aliases may still work for generation")
            else:
                errors.append(message)

        available = model_ids | alias_ids
        unsupported = {
            model for model in available
            if model.startswith(GROK_UNSUPPORTED_MODEL_PREFIXES)
        }
        report["unsupported_api_models"] = sorted(unsupported)
        report["advertised_without_card"] = sorted(
            model for model in available - unsupported if get_card(model) is None
        )
        report["retired_cards"] = {
            model: card.quirks["replacement_model"]
            for model, card in BUILTIN_CARDS.items()
            if card.provider == "grok" and card.quirks.get("deprecated")
        }
        report["catalog_not_in_listing"] = sorted(
            model for model, card in BUILTIN_CARDS.items()
            if card.provider == "grok" and model not in available
            and model != "grok-realtime"
        )
        report["listing_note"] = (
            "Absence can mean an alias, retirement, or account restrictions; "
            "it does not alone prove a model is retired."
        )

        if args.search or args.check_search_toggle:
            phase = "Search-enabled request"
            try:
                response_meta = {}
                with redirect_stdout(sys.stderr):
                    answer = provider.generate_chat_completion(
                        [{"role": "user", "content": (
                            "Use web search to find xAI's official API model documentation. "
                            "Return its URL in one short sentence."
                        )}],
                        args.model,
                        web_search_enabled=True,
                        max_tokens=512,
                        response_meta=response_meta,
                    )
                outputs = response_meta.get("grok", {}).get("response_output", [])
                report["search_answer"] = answer
                report["search_output_types"] = [item["type"] for item in outputs]
                if not any(item.get("type") == "web_search_call" for item in outputs):
                    errors.append("Search was offered, but no web_search_call was returned")
                if not answer.strip():
                    errors.append("Search returned no text")
                if args.check_search_toggle:
                    phase = "Search-disabled request"
                    off_meta = {}
                    with redirect_stdout(sys.stderr):
                        off_answer = provider.generate_chat_completion(
                            [
                                {"role": "user", "content": "Find the xAI API model documentation."},
                                {"role": "assistant", "content": answer,
                                 "provider_meta": response_meta},
                                {"role": "user", "content": (
                                    "Check the documentation again and say whether "
                                    "you can search the web on this turn."
                                )},
                            ],
                            args.model, web_search_enabled=False,
                            max_tokens=512, response_meta=off_meta,
                        )
                    calls = off_meta.get("grok", {}).get("search_calls", {})
                    report["search_disabled_answer"] = off_answer
                    report["search_disabled_calls"] = calls
                    if calls.get("web", 0) or calls.get("x", 0):
                        errors.append("New search activity returned with search disabled")
            except Exception as exc:
                errors.append(format_api_error(phase, exc, key))
    finally:
        provider.client.close()

    report["errors"] = errors
    report["warnings"] = warnings
    print(json.dumps(report, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
