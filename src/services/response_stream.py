"""Incremental response decoding shared by chat provider adapters."""

import json
import logging
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class StreamCancelled(Exception):
    """The originating chat request was cancelled or superseded."""


def check_cancelled(cancel_check):
    """Stop decoding before delivering more content or executing a tool."""
    if cancel_check():
        raise StreamCancelled()


@contextmanager
def managed_stream(resource, cancel_check):
    """Close a response on cancellation, including while waiting for tokens."""
    stopped = threading.Event()

    def watch():
        while not stopped.wait(0.1):
            if cancel_check():
                try:
                    resource.close()
                except Exception:
                    logger.debug("Cancelled transport already closed", exc_info=True)
                return

    watcher = threading.Thread(target=watch, daemon=True)
    watcher.start()
    try:
        check_cancelled(cancel_check)
        yield resource
        check_cancelled(cancel_check)
    except Exception:
        check_cancelled(cancel_check)
        raise
    finally:
        stopped.set()
        try:
            resource.close()
        except Exception:
            logger.debug("Could not close response transport", exc_info=True)


def iter_sse(response):
    """Decode SSE frames, accepting comments, CRLF and multiline data."""
    lines = []
    for line in response.iter_lines(chunk_size=1):
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        if not line:
            if lines:
                payload = "\n".join(lines)
                lines = []
                if payload == "[DONE]":
                    return
                yield json.loads(payload)
        elif line.startswith("data:"):
            lines.append(line[5:].lstrip(" "))
    if lines:
        payload = "\n".join(lines)
        if payload != "[DONE]":
            yield json.loads(payload)


class ThinkParser:
    """Separate leading think blocks even when a tag spans several chunks.

    Only leading blocks are recognized, so examples in an answer stay intact.
    Explicit provider reasoning fields should take precedence over inline tags.
    """

    def __init__(self, emit):
        self.emit = emit
        self.pending = ""
        self.mode = "start"

    def feed(self, text):
        self.pending += text
        while self.pending:
            if self.mode == "answer":
                self.emit("text", self.pending)
                self.pending = ""
                return
            if self.mode == "start":
                stripped = self.pending.lstrip()
                if stripped.lower().startswith("<think>"):
                    self.pending = stripped[7:]
                    self.mode = "thinking"
                    continue
                if not stripped or "<think>".startswith(stripped.lower()):
                    return
                self.mode = "answer"
                continue
            index = self.pending.lower().find("</think>")
            if index >= 0:
                self.emit("reasoning", self.pending[:index])
                self.pending = self.pending[index + 8 :]
                self.mode = "start"
                continue
            # Retain any suffix that could be the start of a closing tag.
            keep = 0
            for length in range(1, min(len(self.pending), 7) + 1):
                if "</think>".startswith(self.pending[-length:].lower()):
                    keep = length
            end = len(self.pending) - keep
            if end:
                self.emit("reasoning", self.pending[:end])
                self.pending = self.pending[end:]
            return

    def finish(self):
        """Flush text at completion; unterminated thinking stays reasoning."""
        if self.pending:
            self.emit("reasoning" if self.mode == "thinking" else "text", self.pending)
            self.pending = ""


def _merge_fragments(target, delta):
    for key, value in delta.items():
        if value is None:
            continue
        if isinstance(value, str) and key in ("text", "summary", "data"):
            target[key] = target.get(key, "") + value
        else:
            target[key] = value


def read_chat_chunks(chunks, emit, cancel_check):
    """Assemble a chat completion, including fragmented tool arguments."""
    text = []
    reasoning = []
    calls = {}
    details = {}
    finished = False
    explicit_reasoning = False
    reasoning_field_seen = False

    def deliver(kind, value):
        if value:
            (text if kind == "text" else reasoning).append(value)
            emit(kind, value)

    def deliver_inline(kind, value):
        if kind != "reasoning" or not explicit_reasoning:
            deliver(kind, value)

    parser = ThinkParser(deliver_inline)
    for chunk in chunks:
        check_cancelled(cancel_check)
        if chunk.get("error"):
            raise RuntimeError(str(chunk["error"]))
        choices = chunk.get("choices") or []
        if not choices:
            continue
        choice = choices[0]
        delta = choice.get("delta") or choice.get("message") or {}
        explicit = delta.get("reasoning_content") or delta.get("reasoning")
        detail_delta = delta.get("reasoning_details") or []
        explicit_reasoning = (
            explicit_reasoning
            or bool(explicit)
            or any(
                detail.get("type") in ("reasoning.text", "reasoning.summary")
                for detail in detail_delta
            )
        )
        if isinstance(explicit, str):
            reasoning_field_seen = True
            deliver("reasoning", explicit)
        for position, detail in enumerate(detail_delta):
            key = detail.get("index")
            if key is None:
                key = detail.get("id") or position
            _merge_fragments(details.setdefault(key, {}), detail)
            if not reasoning_field_seen:
                if detail.get("type") == "reasoning.text":
                    deliver("reasoning", detail.get("text", ""))
                elif detail.get("type") == "reasoning.summary":
                    deliver("reasoning", detail.get("summary", ""))
        content = delta.get("content")
        if isinstance(content, str):
            parser.feed(content)
        refusal = delta.get("refusal")
        if refusal:
            parser.feed(refusal)
        for fragment in delta.get("tool_calls") or []:
            index = fragment.get("index", 0)
            call = calls.setdefault(
                index,
                {
                    "id": "",
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                },
            )
            if fragment.get("id"):
                call["id"] = fragment["id"]
            for key in ("name", "arguments"):
                call["function"][key] += (fragment.get("function") or {}).get(key) or ""
        if choice.get("finish_reason"):
            if choice["finish_reason"] not in ("stop", "tool_calls", "function_call"):
                raise RuntimeError("Response incomplete: " + choice["finish_reason"])
            finished = True
            break
    parser.finish()
    if not finished:
        raise RuntimeError("The response stream ended before completion.")
    message = {"role": "assistant", "content": "".join(text)}
    if calls:
        message["tool_calls"] = [calls[key] for key in sorted(calls)]
    if reasoning:
        message["reasoning_content"] = "".join(reasoning)
    if details:
        message["reasoning_details"] = list(details.values())
    return message


def read_response_events(events, emit, cancel_check):
    """Deliver Responses deltas and retain complete output for tool replay."""
    final = None
    parts = {"text": {}, "reasoning": {}}

    def deliver(kind, key, value, complete=False):
        if not value:
            return
        previous = parts[kind].get(key, "")
        if complete:
            # Done events repeat the accumulated text. Emit only any suffix
            # that was absent from the deltas, or the whole missing part.
            delta = value[len(previous) :] if value.startswith(previous) else ""
        else:
            delta = value
        if not delta:
            return
        if kind == "reasoning" and key not in parts[kind] and parts[kind]:
            emit(kind, "\n\n")
        parts[kind][key] = previous + delta
        emit(kind, delta)

    def read_item(item, item_id):
        item_id = item.get("id") or item_id
        if item.get("type") == "reasoning":
            for index, part in enumerate(item.get("summary") or []):
                deliver(
                    "reasoning",
                    ("summary", item_id, index),
                    part.get("text", ""),
                    complete=True,
                )
            for index, part in enumerate(item.get("content") or []):
                if part.get("type") == "reasoning_text":
                    deliver(
                        "reasoning",
                        ("content", item_id, index),
                        part.get("text", ""),
                        complete=True,
                    )
        elif item.get("type") == "message":
            for index, part in enumerate(item.get("content") or []):
                deliver(
                    "text",
                    (item_id, index),
                    part.get("text", part.get("refusal", "")),
                    complete=True,
                )

    for event in events:
        check_cancelled(cancel_check)
        if hasattr(event, "model_dump"):
            event = event.model_dump(exclude_none=True)
        event_type = event.get("type", "")
        if event_type in ("error", "response.failed"):
            error = event.get("error") or event.get("response", {}).get("error")
            raise RuntimeError(str(error or event.get("message") or "Response failed"))
        item_id = event.get("item_id") or event.get("output_index", 0)
        if event_type in ("response.output_text.delta", "response.refusal.delta"):
            deliver(
                "text", (item_id, event.get("content_index", 0)), event.get("delta", "")
            )
        elif event_type in ("response.output_text.done", "response.refusal.done"):
            deliver(
                "text",
                (item_id, event.get("content_index", 0)),
                event.get("text", event.get("refusal", "")),
                complete=True,
            )
        elif event_type.startswith("response.reasoning_summary_"):
            key = ("summary", item_id, event.get("summary_index", 0))
            if event_type == "response.reasoning_summary_text.delta":
                deliver("reasoning", key, event.get("delta", ""))
            elif event_type == "response.reasoning_summary_text.done":
                deliver("reasoning", key, event.get("text", ""), complete=True)
            elif event_type in (
                "response.reasoning_summary_part.added",
                "response.reasoning_summary_part.done",
            ):
                deliver(
                    "reasoning",
                    key,
                    (event.get("part") or {}).get("text", ""),
                    complete=True,
                )
        elif event_type in (
            "response.reasoning_text.delta",
            "response.reasoning_text.done",
        ):
            key = ("content", item_id, event.get("content_index", 0))
            done = event_type.endswith(".done")
            deliver(
                "reasoning",
                key,
                event.get("text" if done else "delta", ""),
                complete=done,
            )
        elif event_type == "response.output_item.done":
            read_item(event.get("item") or {}, item_id)
        elif event_type in ("response.completed", "response.incomplete"):
            final = event["response"]
            break
    if final is None:
        raise RuntimeError("The response stream ended before completion.")
    for index, item in enumerate(final.get("output") or []):
        read_item(item, index)
    if final.get("status") == "incomplete":
        raise RuntimeError(
            "Response incomplete: " + str(final.get("incomplete_details"))
        )
    return final
