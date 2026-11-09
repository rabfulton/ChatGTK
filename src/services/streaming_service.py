"""Streaming chat orchestration for Responses, compatible chat and Gemini."""

import json
from contextlib import closing
from copy import deepcopy
from urllib.parse import urlparse

import requests

from model_cards import get_card
from tools import (
    ToolContext,
    build_enabled_tools_from_handlers,
    build_tools_for_provider,
    process_tool_result,
    run_tool_call,
)

from .response_stream import (
    check_cancelled,
    iter_sse,
    managed_stream,
    read_chat_chunks,
    read_response_events,
)

HANDLERS = (
    "image_tool_handler",
    "music_tool_handler",
    "read_aloud_tool_handler",
    "search_tool_handler",
    "text_get_handler",
    "text_edit_handler",
    "wolfram_handler",
)


def can_stream(provider, provider_name, model):
    """Return whether this request has a supported text streaming adapter."""
    from ai_providers import (
        CustomProvider,
        GeminiProvider,
        GrokProvider,
        OpenAIProvider,
    )

    types = {
        "custom": CustomProvider,
        "gemini": GeminiProvider,
        "grok": GrokProvider,
        "openai": OpenAIProvider,
    }
    if provider_name not in types or not isinstance(provider, types[provider_name]):
        return False
    card = get_card(model)
    if card and (
        not card.capabilities.text
        or card.capabilities.audio_out
        or card.api_family in ("realtime", "tts", "images")
    ):
        return False
    return provider_name != "custom" or provider.api_type in (
        "chat.completions",
        "responses",
    )


def _post_events(post, url, payload, headers, cancel_check):
    """Read an HTTP event stream; also accept endpoints returning plain JSON."""
    check_cancelled(cancel_check)
    response = post(url, headers=headers, json=payload, stream=True, timeout=(10, 120))
    with managed_stream(response, cancel_check):
        response.raise_for_status()
        if "application/json" in response.headers.get("Content-Type", ""):
            yield response.json()
        else:
            yield from iter_sse(response)


def _compatible_chunks(chunks):
    for chunk in chunks:
        for choice in chunk.get("choices") or []:
            if "message" in choice:
                choice.setdefault("finish_reason", "stop")
                for index, call in enumerate(choice["message"].get("tool_calls") or []):
                    call["index"] = index
        yield chunk


def _response_events(events):
    for event in events:
        if "output" in event and not event.get("type"):
            yield {"type": "response.completed", "response": event}
        else:
            yield event


def _tools(kwargs, card):
    handlers = [kwargs.get(name) for name in HANDLERS]
    enabled = build_enabled_tools_from_handlers(*handlers)
    if card and not card.capabilities.tool_use:
        enabled.clear()
    context = ToolContext(
        image_handler=handlers[0],
        music_handler=handlers[1],
        read_aloud_handler=handlers[2],
        search_handler=handlers[3],
        text_get_handler=handlers[4],
        text_edit_handler=handlers[5],
        wolfram_handler=handlers[6],
    )
    return enabled, context


def _run_tool(name, arguments, enabled, context, snippets, cancel_check):
    check_cancelled(cancel_check)
    if name not in enabled:
        return "Error: this tool is not available."
    # Never execute a truncated or malformed streamed call.
    parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
    if not isinstance(parsed, dict):
        raise TypeError("Tool arguments must be a JSON object.")
    result = run_tool_call(name, parsed, context)
    check_cancelled(cancel_check)
    return process_tool_result(result, snippets)


def _is_openrouter(provider):
    return urlparse(provider.endpoint or "").hostname == "openrouter.ai"


def _saved_state(message, namespace, model, search_enabled, provider):
    """Use protocol state only for the original model, policy and answer."""
    state = (message.get("provider_meta") or {}).get(namespace, {})
    if (
        state.get("model") != model
        or state.get("web_search_enabled") != search_enabled
        or state.get("answer", message.get("content")) != message.get("content")
    ):
        return {}
    if namespace == "custom" and state.get("source") != _custom_source(provider):
        return {}
    return state


def _custom_source(provider):
    return {
        "endpoint": provider.endpoint,
        "model_id": provider.model_id,
        "api_type": provider.api_type,
    }


def _set_temperature(params, kwargs, card):
    value = kwargs.get("temperature")
    if value is None and card:
        value = card.temperature
    if value is not None and not (
        card and card.quirks.get("no_temperature") and card.temperature is None
    ):
        params["temperature"] = value


def _compatible_messages(provider, messages, model, search_enabled):
    result = []
    for message in messages:
        clean = {
            key: message[key]
            for key in ("role", "content", "name", "tool_calls", "tool_call_id")
            if key in message
        }
        if message.get("images"):
            from ai_providers import _get_image_data

            clean["content"] = [{"type": "text", "text": message.get("content", "")}]
            for image in message["images"]:
                clean["content"].append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image.get('mime_type', 'image/jpeg')};base64,{_get_image_data(image)}",
                        },
                    }
                )
        state = _saved_state(message, "custom", model, search_enabled, provider)
        if state.get("turn_messages"):
            result.extend(deepcopy(state["turn_messages"]))
            continue
        result.append(clean)
    return result


def _stream_chat(provider, provider_name, kwargs, emit, cancel_check, meta):
    model = kwargs["model"]
    card = get_card(model)
    enabled, context = _tools(kwargs, card)
    search_enabled = bool(kwargs.get("web_search_enabled"))
    messages = _compatible_messages(provider, kwargs["messages"], model, search_enabled)
    initial_count = len(messages)
    if provider_name == "openai" and card and card.quirks.get("needs_developer_role"):
        for message in messages:
            if message["role"] == "system":
                message["role"] = "developer"
    params = {
        "model": getattr(provider, "model_id", None) or model,
        "messages": messages,
        "stream": True,
    }
    _set_temperature(params, kwargs, card)
    if kwargs.get("max_tokens"):
        key = "max_completion_tokens" if provider_name == "openai" else "max_tokens"
        params[key] = kwargs["max_tokens"]
    if card and card.quirks.get("reasoning_effort_enabled"):
        params["reasoning_effort"] = card.quirks.get("reasoning_effort_level", "low")
    if provider_name == "custom" and _is_openrouter(provider):
        params["reasoning"] = {"enabled": True, "exclude": False}
        # OpenRouter uses reasoning.effort instead of reasoning_effort.
        if "reasoning_effort" in params:
            params["reasoning"]["effort"] = params.pop("reasoning_effort")
    tools = build_tools_for_provider(enabled, "openai")
    if tools:
        params.update(tools=tools, tool_choice="auto")
    snippets = []
    for _ in range(5):
        check_cancelled(cancel_check)
        emit("reset", "")
        if provider_name == "custom":
            chunks = _post_events(
                provider.session.post,
                provider._get_base_endpoint() + "/chat/completions",
                params,
                provider._headers(),
                cancel_check,
            )

            with closing(chunks):
                message = read_chat_chunks(
                    _compatible_chunks(chunks), emit, cancel_check
                )
        else:
            stream = provider.client.chat.completions.create(**params)
            with managed_stream(stream, cancel_check):
                message = read_chat_chunks(
                    (chunk.model_dump(exclude_none=True) for chunk in stream),
                    emit,
                    cancel_check,
                )
        if (
            provider_name == "custom"
            and _is_openrouter(provider)
            and message.get("reasoning_content")
        ):
            message["reasoning"] = message.pop("reasoning_content")
        calls = message.get("tool_calls") or []
        if not calls:
            answer = message["content"] + (
                "\n\n" + "\n\n".join(snippets) if snippets else ""
            )
            if provider_name == "custom":
                meta["custom"] = {
                    "model": model,
                    "web_search_enabled": search_enabled,
                    "answer": answer,
                    "source": _custom_source(provider),
                    "turn_messages": deepcopy(messages[initial_count:] + [message]),
                }
            return answer
        messages.append(message)
        for call in calls:
            function = call["function"]
            output = _run_tool(
                function["name"],
                function["arguments"],
                enabled,
                context,
                snippets,
                cancel_check,
            )
            messages.append(
                {"role": "tool", "tool_call_id": call["id"], "content": output}
            )
    raise RuntimeError("The model exceeded the tool round limit.")


def _summary_supported(model, card):
    if card and "reasoning_summary" in card.quirks:
        return bool(card.quirks["reasoning_summary"])
    return (
        model.startswith(("gpt-5", "gpt-6", "o4-mini"))
        and "chat" not in model
        or model == "o3"
        or model.startswith("o3-20")
    )


def _stream_responses(provider, provider_name, kwargs, emit, cancel_check, meta):
    model = kwargs["model"]
    card = get_card(model)
    enabled, context = _tools(kwargs, card)
    search_enabled = bool(
        kwargs.get("web_search_enabled")
        and provider_name != "custom"
        and provider._supports_web_search_tool(model)
    )
    if provider_name == "grok":
        messages = []
        for message in kwargs["messages"]:
            state = _saved_state(message, "grok", model, search_enabled, provider)
            messages.append({**message, "provider_meta": {"grok": state}})
        inputs, instructions = provider._build_responses_input(
            messages, model, search_enabled
        )
    else:
        inputs, instructions = provider._build_responses_input(kwargs["messages"])
        assistants = iter(
            message
            for message in kwargs["messages"]
            if message.get("role") == "assistant"
        )
        replayed = []
        for item in inputs:
            if item.get("role") == "assistant":
                message = next(assistants)
                state = _saved_state(
                    message, provider_name, model, search_enabled, provider
                )
                if state.get("response_output"):
                    replayed.extend(deepcopy(state["response_output"]))
                    continue
            replayed.append(item)
        inputs = replayed
    if provider_name == "custom":
        tools = provider._build_responses_tools(enabled, model)
    else:
        tools = provider._build_responses_tools(enabled, search_enabled, model)
    params = {
        "model": getattr(provider, "model_id", None) or model,
        "input": inputs,
        "stream": True,
    }
    if instructions:
        params["instructions"] = instructions
    if tools:
        params["tools"] = tools
    _set_temperature(params, kwargs, card)
    if kwargs.get("max_tokens") and not (
        card and card.quirks.get("no_max_output_tokens")
    ):
        params["max_output_tokens"] = kwargs["max_tokens"]
    if card and card.quirks.get("reasoning_effort_enabled"):
        params["reasoning"] = {
            "effort": card.quirks.get("reasoning_effort_level", "low")
        }
    if provider_name == "openai" and _summary_supported(model, card):
        params.setdefault("reasoning", {})["summary"] = "auto"
        params["include"] = ["reasoning.encrypted_content"]
    turn_output = []
    snippets = []
    for _ in range(5):
        check_cancelled(cancel_check)
        emit("reset", "")
        if provider_name == "custom":
            events = _post_events(
                provider.session.post,
                provider._get_base_endpoint() + "/responses",
                params,
                provider._headers(),
                cancel_check,
            )

            with closing(events):
                response = read_response_events(
                    _response_events(events), emit, cancel_check
                )
        else:
            stream = provider.client.responses.create(**params)
            with managed_stream(stream, cancel_check):
                response = read_response_events(stream, emit, cancel_check)
        output = response.get("output") or []
        inputs.extend(output)
        turn_output.extend(output)
        calls = [item for item in output if item.get("type") == "function_call"]
        text = "".join(
            part.get("text", part.get("refusal", ""))
            for item in output
            if item.get("type") == "message"
            for part in item.get("content", [])
        )
        if provider_name == "openai":
            for item in output:
                if item.get("type") == "image_generation_call" and item.get("result"):
                    text += "\n\n__IMAGE_DATA__:data:image/png;base64," + item["result"]
            text = provider._process_image_data_placeholders(
                text, kwargs.get("chat_id")
            )
        elif provider_name == "custom":
            text, _ = provider._extract_responses_output(
                response, chat_id=kwargs.get("chat_id")
            )
        if not calls:
            answer = text + ("\n\n" + "\n\n".join(snippets) if snippets else "")
            meta[provider_name] = {
                "model": model,
                "web_search_enabled": search_enabled,
                "answer": answer,
                "response_output": deepcopy(turn_output),
            }
            if provider_name == "custom":
                meta[provider_name]["source"] = _custom_source(provider)
            return answer
        for call in calls:
            output = _run_tool(
                call["name"],
                call["arguments"],
                enabled,
                context,
                snippets,
                cancel_check,
            )
            result = {
                "type": "function_call_output",
                "call_id": call["call_id"],
                "output": output,
            }
            inputs.append(result)
            turn_output.append(result)
    raise RuntimeError("The model exceeded the tool round limit.")


def _stream_gemini(provider, kwargs, emit, cancel_check, meta):
    model = kwargs["model"]
    card = get_card(model)
    provider._require_key()
    enabled, context = _tools(kwargs, card)
    search_enabled = bool(
        kwargs.get("web_search_enabled")
        and not enabled
        and card
        and card.capabilities.web_search
    )
    contents, instructions = provider._convert_messages(kwargs["messages"])
    # Replace historical assistant text with signed native content when available.
    assistants = iter(
        message
        for message in kwargs["messages"]
        if message.get("role") == "assistant"
        and (message.get("content") or message.get("images"))
    )
    replayed = []
    for content in contents:
        if content["role"] == "model":
            state = _saved_state(
                next(assistants), "gemini", model, search_enabled, provider
            )
            if state.get("turn_content"):
                replayed.extend(deepcopy(state["turn_content"]))
                continue
        replayed.append(content)
    contents = replayed
    config = {}
    _set_temperature(config, kwargs, card)
    if kwargs.get("max_tokens"):
        config["maxOutputTokens"] = kwargs["max_tokens"]
    if (
        model.startswith(("gemini-2.5", "gemini-3", "gemini-4"))
        or model in ("gemini-pro-latest", "gemini-flash-latest")
    ) and "image" not in model:
        config["thinkingConfig"] = {"includeThoughts": True}
    payload = {"contents": contents, "generationConfig": config}
    if instructions:
        payload["systemInstruction"] = {"parts": [{"text": instructions}]}
    if enabled:
        payload["tools"] = [
            {"functionDeclarations": build_tools_for_provider(enabled, "gemini")}
        ]
    elif search_enabled:
        payload["tools"] = [{"google_search": {}}]
    snippets = []
    turn_content = []
    for _ in range(5):
        check_cancelled(cancel_check)
        emit("reset", "")
        parts = []
        text = []
        finished = False
        events = _post_events(
            requests.post,
            f"{provider.BASE_URL}/models/{model}:streamGenerateContent?alt=sse",
            payload,
            provider._headers(),
            cancel_check,
        )
        with closing(events):
            for event in events:
                check_cancelled(cancel_check)
                if event.get("error"):
                    raise RuntimeError(str(event["error"]))
                candidates = event.get("candidates") or []
                if not candidates:
                    if event.get("promptFeedback", {}).get("blockReason"):
                        raise RuntimeError(
                            "Gemini blocked this request: "
                            + str(event["promptFeedback"])
                        )
                    continue
                candidate = candidates[0]
                for part in candidate.get("content", {}).get("parts", []):
                    _append_gemini_part(parts, part)
                    if "text" in part:
                        kind = "reasoning" if part.get("thought") else "text"
                        emit(kind, part["text"])
                        if kind == "text":
                            text.append(part["text"])
                if candidate.get("finishReason"):
                    if candidate["finishReason"] != "STOP":
                        raise RuntimeError(
                            "Gemini response incomplete: " + candidate["finishReason"]
                        )
                    finished = True
                    break
        if not finished:
            raise RuntimeError("The Gemini stream ended before completion.")
        content = {"role": "model", "parts": parts}
        contents.append(content)
        turn_content.append(content)
        calls = [part["functionCall"] for part in parts if "functionCall" in part]
        if not calls:
            answer = "".join(text) + (
                "\n\n" + "\n\n".join(snippets) if snippets else ""
            )
            meta["gemini"] = {
                "model": model,
                "answer": answer,
                "web_search_enabled": search_enabled,
                "turn_content": deepcopy(turn_content),
            }
            return answer
        results = []
        for call in calls:
            output = _run_tool(
                call["name"],
                call.get("args", {}),
                enabled,
                context,
                snippets,
                cancel_check,
            )
            result = {"name": call["name"], "response": {"result": output}}
            if call.get("id"):
                result["id"] = call["id"]
            results.append({"functionResponse": result})
        content = {"role": "user", "parts": results}
        contents.append(content)
        turn_content.append(content)
    raise RuntimeError("The model exceeded the tool round limit.")


def _append_gemini_part(parts, part):
    """Join text fragments and bind signature-only chunks to their part."""
    if parts and set(part) == {"thoughtSignature"}:
        parts[-1]["thoughtSignature"] = part["thoughtSignature"]
    elif (
        parts
        and "text" in part
        and "text" in parts[-1]
        and bool(part.get("thought")) == bool(parts[-1].get("thought"))
        and not parts[-1].get("thoughtSignature")
    ):
        parts[-1]["text"] += part["text"]
        if part.get("thoughtSignature"):
            parts[-1]["thoughtSignature"] = part["thoughtSignature"]
    else:
        parts.append(deepcopy(part))


def stream_chat_completion(
    provider, provider_name, kwargs, on_stream, cancel_check, response_meta
):
    """Generate a complete answer while delivering text and reasoning deltas.

    ``on_stream(kind, text)`` receives text, reasoning, and reset (new tool round).
    Protocol state is returned separately in response_meta for subsequent turns.
    """
    if provider_name == "gemini":
        return _stream_gemini(provider, kwargs, on_stream, cancel_check, response_meta)
    model = kwargs["model"]
    card = get_card(model)
    if provider_name == "custom":
        responses = provider.api_type == "responses"
    elif provider_name == "grok":
        responses = bool(
            card
            and card.api_family == "responses"
            or kwargs.get("web_search_enabled")
            and provider._supports_web_search_tool(model)
        )
    else:
        responses = not (card and card.api_family == "chat.completions")
    adapter = _stream_responses if responses else _stream_chat
    return adapter(
        provider, provider_name, kwargs, on_stream, cancel_check, response_meta
    )
