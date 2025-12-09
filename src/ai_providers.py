from abc import ABC, abstractmethod
from openai import OpenAI
import requests
from pathlib import Path
from datetime import datetime
import websockets
import asyncio
import json
import os
from gi.repository import GLib
import numpy as np
import sounddevice as sd
import threading
import base64
import tempfile
import subprocess

from tools import (
    build_tools_for_provider,
    ToolContext,
    run_tool_call,
    parse_tool_arguments,
)
from config import HISTORY_DIR

class AIProvider(ABC):
    """Abstract base class for AI providers."""
    
    @abstractmethod
    def initialize(self, api_key: str):
        """Initialize the AI provider with API key."""
        pass
    
    @abstractmethod
    def get_available_models(self):
        """Get list of available models."""
        pass
    
    @abstractmethod
    def generate_chat_completion(self, messages, model, temperature=0.7, max_tokens=None):
        """Generate chat completion."""
        pass
    
    @abstractmethod
    def generate_image(self, prompt, chat_id, model="dall-e-3"):
        """Generate image from prompt."""
        pass
    
    @abstractmethod
    def transcribe_audio(self, audio_file):
        """Transcribe audio file to text."""
        pass
    
    @abstractmethod
    def generate_speech(self, text, voice):
        """Generate speech from text."""
        pass

class CustomProvider(AIProvider):
    """
    Generic provider for user-defined, OpenAI-compatible endpoints.
    Supports chat.completions, responses, images, and TTS endpoints.
    """

    def __init__(self):
        self.api_key = None
        self.endpoint = None
        self.model_name = None
        self.api_type = "chat.completions"
        self.session = requests.Session()

    def initialize(self, api_key: str, endpoint: str = None, model_name: str = None, api_type: str = None):
        self.api_key = api_key
        if endpoint:
            self.endpoint = endpoint.rstrip("/")
        if model_name:
            self.model_name = model_name
        if api_type:
            self.api_type = api_type

    # -----------------------------
    # Helpers
    # -----------------------------
    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _url(self, path: str) -> str:
        base = self.endpoint or ""
        if base.endswith("/"):
            base = base[:-1]
        if not path.startswith("/"):
            path = "/" + path
        return base + path

    def _extract_text(self, data: dict) -> str:
        # Try OpenAI chat/completions style
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        if isinstance(message, dict) and "content" in message:
            return message.get("content") or ""

        # Try Responses output_text or content array
        if "output_text" in data:
            return data.get("output_text") or ""
        if "output" in data:
            output = data["output"]
            if isinstance(output, list) and output:
                if isinstance(output[0], dict) and output[0].get("content"):
                    # content may be list of {type,text}
                    content = output[0]["content"]
                    if isinstance(content, list) and content:
                        first = content[0]
                        if isinstance(first, dict) and "text" in first:
                            return first.get("text") or ""
                if isinstance(output[0], str):
                    return output[0]
        return ""

    # -----------------------------
    # APIProvider interface
    # -----------------------------
    def get_available_models(self, disable_filter: bool = False):
        return [self.model_name] if self.model_name else []

    def generate_chat_completion(
        self,
        messages,
        model,
        temperature=0.7,
        max_tokens=None,
        chat_id=None,
        web_search_enabled: bool = False,
        image_tool_handler=None,
        music_tool_handler=None,
        read_aloud_tool_handler=None,
    ):
        api_type = (self.api_type or "chat.completions").lower()
        if api_type == "responses":
            return self._call_responses(messages, temperature, max_tokens)
        # Default to chat.completions
        url = self._url("/chat/completions")
        payload = {"model": model or self.model_name, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens and max_tokens > 0:
            payload["max_tokens"] = int(max_tokens)

        resp = self.session.post(url, headers=self._headers(), json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return self._extract_text(data)

    def _call_responses(self, messages, temperature, max_tokens):
        url = self._url("/responses")
        # Minimal conversion to Responses input
        inputs = []
        for msg in messages or []:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            inputs.append({"role": role, "content": content})

        payload = {"model": self.model_name, "input": inputs}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens and max_tokens > 0:
            payload["max_output_tokens"] = int(max_tokens)

        resp = self.session.post(url, headers=self._headers(), json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return self._extract_text(data)

    def generate_image(self, prompt, chat_id, model="dall-e-3", image_data=None):
        api_type = (self.api_type or "").lower()
        url = self._url("/images/generations")
        payload = {"model": self.model_name or model, "prompt": prompt}
        resp = self.session.post(url, headers=self._headers(), json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        # Expect OpenAI-style {data:[{url:...}]} or base64
        first = (data.get("data") or [{}])[0]
        return first.get("url") or first.get("b64_json") or ""

    def transcribe_audio(self, audio_file):
        raise NotImplementedError("Transcription not implemented for custom provider")

    def generate_speech(self, text, voice):
        url = self._url("/audio/speech")
        payload = {"model": self.model_name, "input": text}
        if voice:
            payload["voice"] = voice
        resp = self.session.post(url, headers=self._headers(), json=payload, timeout=60)
        resp.raise_for_status()
        return resp.content

    # -----------------------------
    # Connection test
    # -----------------------------
    def test_connection(self):
        """
        Perform a light-weight request based on api_type.
        Returns (ok: bool, message: str)
        """
        try:
            api_type = (self.api_type or "chat.completions").lower()
            if api_type == "responses":
                _ = self._call_responses(
                    [{"role": "user", "content": "ping"}],
                    temperature=1.0,
                    max_tokens=16,
                )
            elif api_type == "images":
                # Attempt a minimal image generation with a benign prompt.
                _ = self.generate_image("ping", chat_id="test")
            elif api_type == "tts":
                # Attempt a minimal TTS call; do not save output.
                _ = self.generate_speech("ping", voice=None)
            else:
                _ = self.generate_chat_completion(
                    [{"role": "user", "content": "ping"}],
                    model=self.model_name,
                    temperature=1.0,
                    max_tokens=16,
                )
            return True, "Connection successful"
        except Exception as exc:
            return False, str(exc)

class OpenAIProvider(AIProvider):
    # Maximum file size for document uploads (in bytes) - 512 MB per OpenAI docs
    MAX_FILE_SIZE = 512 * 1024 * 1024
    
    # Supported MIME types for document uploads.
    # NOTE: The Responses API currently only accepts PDF files for file inputs,
    # so we restrict uploads to PDFs here. Other text-like formats (TXT, MD,
    # etc.) are inlined as text by the UI instead of being uploaded.
    SUPPORTED_DOC_TYPES = {
        "application/pdf",
    }
    
    def __init__(self):
        self.client = None
        self._current_api_key = None
        # Cache for uploaded file IDs: key = (path, size, mtime) -> file_id
        self._file_id_cache = {}
    
    def initialize(self, api_key: str):
        # Only clear file cache when API key actually changes (different account)
        if api_key != self._current_api_key:
            self._file_id_cache = {}
            self._current_api_key = api_key
        self.client = OpenAI(api_key=api_key)
    
    def _get_file_cache_key(self, file_path: str) -> tuple:
        """Generate a cache key for a file based on path, size, and modification time."""
        try:
            stat = os.stat(file_path)
            return (file_path, stat.st_size, stat.st_mtime)
        except OSError:
            return None
    
    def _upload_file(self, file_path: str, mime_type: str) -> str:
        """
        Upload a file to OpenAI and return the file_id.
        Uses caching to avoid re-uploading unchanged files.
        """
        cache_key = self._get_file_cache_key(file_path)
        if cache_key and cache_key in self._file_id_cache:
            print(f"[OpenAIProvider] Using cached file_id for {file_path}")
            return self._file_id_cache[cache_key]
        
        # Check file size
        file_size = os.path.getsize(file_path)
        if file_size > self.MAX_FILE_SIZE:
            raise ValueError(
                f"File too large: {file_size / (1024*1024):.1f} MB exceeds "
                f"maximum of {self.MAX_FILE_SIZE / (1024*1024):.0f} MB"
            )
        
        # Check MIME type
        if mime_type not in self.SUPPORTED_DOC_TYPES:
            raise ValueError(
                f"Unsupported file type: {mime_type}. "
                f"Supported types: {', '.join(sorted(self.SUPPORTED_DOC_TYPES))}"
            )
        
        print(f"[OpenAIProvider] Uploading file: {file_path} ({mime_type})")
        
        with open(file_path, "rb") as f:
            response = self.client.files.create(
                file=f,
                purpose="user_data",
            )
        
        file_id = response.id
        print(f"[OpenAIProvider] File uploaded successfully: {file_id}")
        
        # Cache the file_id
        if cache_key:
            self._file_id_cache[cache_key] = file_id
        
        return file_id
    
    def _has_attached_files(self, messages) -> bool:
        """Check if any message in the conversation has attached files."""
        for msg in messages:
            if msg.get("files"):
                return True
        return False
    
    def _supports_web_search_tool(self, model: str) -> bool:
        """
        Return True if the given OpenAI model supports the built-in web_search
        tool via the Responses API.
        
        Web search is available for modern GPT models that support the Responses
        API. Older models (gpt-3.5) and specialized models (audio, realtime, image)
        are excluded.
        
        See: https://platform.openai.com/docs/guides/tools/web-search
        """
        if not model:
            return False
        
        model_lower = model.lower()
        
        # Exclude models that don't support web search
        excluded_terms = ("audio", "realtime", "image", "dall-e", "whisper", "tts")
        if any(term in model_lower for term in excluded_terms):
            return False
        
        # Explicit allow-list of models known to support web search via Responses API
        # This is conservative to avoid sending unsupported tools to older models
        web_search_models = {
            # GPT-4o family
            "gpt-4o",
            "gpt-4o-mini",
            "chatgpt-4o-latest",
            # GPT-4 Turbo
            "gpt-4-turbo",
            "gpt-4-turbo-preview",
            # GPT-5 family
            "gpt-5.1",
            "gpt-5.1-chat-latest",
            "gpt-5-pro",
        }
        
        # Check explicit list first
        if model in web_search_models or model_lower in web_search_models:
            return True
        
        # Allow any gpt-5.x model
        if model_lower.startswith("gpt-5"):
            return True
        
        # Allow any gpt-4.x model (4.1, 4.5, etc.) but not older gpt-4
        if model_lower.startswith("gpt-4."):
            return True
        
        return False

    def _build_responses_input(self, messages) -> tuple:
        """
        Convert internal message format to Responses API input format.
        
        Returns
        -------
        tuple
            (input_items, instructions) where input_items is a list suitable for
            the Responses API `input` parameter and instructions is the extracted
            system message content (or None).
        """
        input_items = []
        instructions = None
        
        for msg in messages:
            role = msg.get("role", "user")
            content_text = msg.get("content", "")
            files = msg.get("files", [])
            images = msg.get("images", [])
            
            # Extract system messages for instructions parameter
            if role == "system":
                instructions = content_text
                continue
            
            # Map assistant role to the responses API format
            if role == "assistant":
                # For assistant messages, we add them as output references
                input_items.append({
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": content_text}],
                })
                continue
            
            # Build content parts for user messages
            content_parts = []
            
            # Add text content
            if content_text:
                content_parts.append({
                    "type": "input_text",
                    "text": content_text,
                })
            
            # Add file attachments
            for file_info in files:
                file_path = file_info.get("path")
                mime_type = file_info.get("mime_type", "application/octet-stream")
                
                # Check if we already have a file_id (from previous upload)
                file_id = file_info.get("file_id")
                
                if not file_id and file_path:
                    # Upload the file and get the file_id
                    file_id = self._upload_file(file_path, mime_type)
                
                if file_id:
                    content_parts.append({
                        "type": "input_file",
                        "file_id": file_id,
                    })
            
            # Add image attachments (convert to base64 data URL format)
            for img in images:
                img_data = img.get("data", "")
                img_mime = img.get("mime_type", "image/jpeg")
                content_parts.append({
                    "type": "input_image",
                    "image_url": f"data:{img_mime};base64,{img_data}",
                })
            
            if content_parts:
                input_items.append({
                    "type": "message",
                    "role": role,
                    "content": content_parts,
                })
        
        return input_items, instructions

    def _build_responses_tools(
        self,
        enabled_tools: set,
        web_search_enabled: bool,
        model: str,
    ) -> list:
        """
        Build the tools array for the Responses API.
        
        Includes both function tools (image/music/read_aloud) and the built-in
        web_search tool when enabled and supported.
        """
        tools = []
        
        # Add web_search tool if enabled and model supports it
        if web_search_enabled:
            if self._supports_web_search_tool(model):
                tools.append({"type": "web_search"})
                print(f"[OpenAIProvider] Web search enabled for model: {model}")
            else:
                print(f"[OpenAIProvider] Web search requested but not supported for model: {model}")
        
        # Add function tools for image/music/read_aloud
        # The Responses API uses a similar but slightly different format than
        # chat.completions - each function tool has type, name, description, parameters
        from tools import TOOL_REGISTRY
        for tool_name in sorted(enabled_tools):
            spec = TOOL_REGISTRY.get(tool_name)
            if spec:
                tools.append({
                    "type": "function",
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                })
        
        return tools

    def _extract_responses_output(self, response) -> tuple:
        """
        Extract text content and function calls from a Responses API response.
        
        Returns
        -------
        tuple
            (text_content, function_calls) where function_calls is a list of
            dicts with keys: call_id, name, arguments
        """
        text_content = ""
        function_calls = []
        
        if hasattr(response, "output") and response.output:
            for item in response.output:
                item_type = getattr(item, "type", None)
                
                # Handle message output (contains text)
                if item_type == "message" and hasattr(item, "content"):
                    for content_item in item.content:
                        if hasattr(content_item, "text"):
                            text_content += content_item.text
                
                # Handle function_call output
                elif item_type == "function_call":
                    call_id = getattr(item, "call_id", None) or getattr(item, "id", "")
                    name = getattr(item, "name", "")
                    arguments = getattr(item, "arguments", "{}")
                    if name:
                        function_calls.append({
                            "call_id": call_id,
                            "name": name,
                            "arguments": arguments,
                        })
        
        return text_content, function_calls

    def _generate_with_responses_api(
        self,
        messages,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = None,
        web_search_enabled: bool = False,
        image_tool_handler=None,
        music_tool_handler=None,
        read_aloud_tool_handler=None,
    ) -> str:
        """
        Generate a response using the OpenAI Responses API.
        
        This is the primary execution path for OpenAI text models. It supports:
        - File attachments and images
        - Web search (for supported models)
        - Function tools (image generation, music control, read aloud)
        - Multi-round tool calling
        
        Parameters
        ----------
        messages : list
            Conversation messages in internal format.
        model : str
            OpenAI model name.
        temperature : float
            Sampling temperature.
        max_tokens : int
            Maximum output tokens.
        web_search_enabled : bool
            Whether to enable the web_search tool.
        image_tool_handler : callable
            Handler for generate_image tool calls.
        music_tool_handler : callable
            Handler for control_music tool calls.
        read_aloud_tool_handler : callable
            Handler for read_aloud tool calls.
            
        Returns
        -------
        str
            The assistant's response text, with any tool outputs appended.
        """
        model_lower = (model or "").lower()
        # Some Responses-only models (e.g. gpt-4o-mini-search-preview) do not
        # support temperature. We gate the parameter below based on the model
        # name to avoid "Model incompatible request argument supplied" errors.
        is_search_model = "search" in model_lower
        is_gpt5_model = model_lower.startswith("gpt-5")
        
        # Build input from messages
        input_items, instructions = self._build_responses_input(messages)
        
        # Determine which function tools are enabled
        enabled_tools = set()
        if image_tool_handler is not None:
            enabled_tools.add("generate_image")
        if music_tool_handler is not None:
            enabled_tools.add("control_music")
        if read_aloud_tool_handler is not None:
            enabled_tools.add("read_aloud")
        
        # Build tools array
        tools = self._build_responses_tools(enabled_tools, web_search_enabled, model)
        
        # Build base params
        params = {
            "model": model,
            "input": input_items,
        }
        
        if instructions:
            params["instructions"] = instructions
        
        # Temperature handling - some models don't support it
        if temperature is not None and not is_search_model and not is_gpt5_model:
            params["temperature"] = temperature
        
        if max_tokens and max_tokens > 0:
            params["max_output_tokens"] = max_tokens
        
        if tools:
            params["tools"] = tools
        
        print(f"[OpenAIProvider] Calling Responses API with {len(input_items)} input items, {len(tools)} tools")
        
        # If no function tools are enabled, we can do a simple one-shot call
        if not enabled_tools:
            response = self.client.responses.create(**params)
            text_content, _ = self._extract_responses_output(response)
            return text_content
        
        # Tool-aware flow: allow the model to call tools, route those through
        # handlers, then continue the conversation until we get a final answer.
        tool_context = ToolContext(
            image_handler=image_tool_handler,
            music_handler=music_tool_handler,
            read_aloud_handler=read_aloud_tool_handler,
        )
        
        max_tool_rounds = 3
        tool_result_snippets = []
        current_input = input_items.copy()
        
        for round_num in range(max_tool_rounds):
            response = self.client.responses.create(**{
                **params,
                "input": current_input,
            })
            
            text_content, function_calls = self._extract_responses_output(response)
            
            if not function_calls:
                # No function calls - this is the final answer
                if tool_result_snippets:
                    # Append tool outputs (e.g. <img> tags) so UI always renders them
                    return text_content + "\n\n" + "\n\n".join(tool_result_snippets)
                return text_content
            
            # Process each function call
            for fc in function_calls:
                parsed_args = parse_tool_arguments(fc["arguments"])
                tool_result = run_tool_call(fc["name"], parsed_args, tool_context)
                
                if tool_result:
                    tool_result_snippets.append(tool_result)
                
                # Add the function call and its result to the conversation
                # First, add the assistant's function call
                current_input.append({
                    "type": "function_call",
                    "call_id": fc["call_id"],
                    "name": fc["name"],
                    "arguments": fc["arguments"],
                })
                
                # Then add the function result
                current_input.append({
                    "type": "function_call_output",
                    "call_id": fc["call_id"],
                    "output": tool_result or "",
                })
        
        # If we exhausted tool rounds, return what we have
        final_text = text_content if text_content else ""
        if tool_result_snippets:
            return final_text + "\n\n" + "\n\n".join(tool_result_snippets)
        return final_text
    
    def get_available_models(self, disable_filter=False):
        import re
        try:
            models = self.client.models.list()
            
            # Check both parameter and environment variable
            disable_filter = disable_filter or os.getenv('DISABLE_MODEL_FILTER', '').lower() in ('true', '1', 'yes')
            #disable_filter = 1 
            if disable_filter:
                # Return all available models when filtering is disabled
                return sorted([model.id for model in models])
            
            # Default filtering behavior
            allowed_models = {
                "gpt-3.5-turbo",
                "gpt-4",
                "dall-e-3",
                "gpt-image-1",
                "gpt-image-1-mini",
                "gpt-4o-mini-realtime-preview",
                "o1-mini",
                "o1-preview",
                "chatgpt-4o-latest",
                "gpt-4-turbo",
                "gpt-4.1",
                "gpt-4o-mini",
                "gpt-4o-audio-preview",
                "gpt-4o-mini-audio-preview",
                "gpt-4o",
                "gpt-4o-realtime-preview",
                "gpt-4",
                "gpt-realtime",
                "o3",
                "o3-mini",
                "gpt-5.1",
                "gpt-5.1-chat-latest",
                "gpt-5-pro",
            }
            filtered_models = [model.id for model in models if model.id in allowed_models]
            return sorted(filtered_models)
        except Exception as e:
            print(f"Error fetching models: {e}")
            return sorted(["gpt-3.5-turbo", "gpt-4", "gpt-4-turbo-preview", "dall-e-3"])

    def _requires_chat_completions(self, model: str) -> tuple:
        """
        Determine if a model requires the chat.completions API instead of Responses.
        
        Returns
        -------
        tuple
            (requires_chat_completions: bool, reason: str)
            reason is one of: "audio", "reasoning", or ""
        """
        model_lower = (model or "").lower()
        
        # Audio models require chat.completions for audio output modalities
        if "audio" in model_lower:
            return True, "audio"
        
        # Reasoning models (o1, o3) require special developer message handling
        # that we've only tested with chat.completions
        reasoning_models = ["o1-mini", "o1-preview", "o3", "o3-mini"]
        if any(r in model_lower for r in reasoning_models):
            return True, "reasoning"
        
        return False, ""

    def _generate_with_chat_completions_audio(
        self,
        messages,
        model: str,
        temperature: float,
        max_tokens: int,
        chat_id: str,
    ) -> str:
        """
        Generate a response using chat.completions for audio-capable models.
        
        Audio models require the chat.completions API with special modalities
        and audio parameters.
        """
        # Preprocess messages to handle images
        processed_messages = []
        for msg in messages:
            content = msg.get("content", "")
            
            if "images" in msg and msg["images"]:
                content_parts = [{"type": "text", "text": content}]
                for img in msg["images"]:
                    mime_type = img.get("mime_type", "image/jpeg")
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{img['data']}",
                            "detail": "auto"
                        }
                    })
                processed_messages.append({
                    "role": msg["role"],
                    "content": content_parts
                })
            else:
                clean_msg = {k: v for k, v in msg.items() 
                           if k in ("role", "content", "name")}
                processed_messages.append(clean_msg)
        
        params = {
            "model": model,
            "messages": processed_messages,
            "modalities": ["text", "audio"],
            "audio": {
                "voice": "alloy",
                "format": "wav"
            }
        }
        
        if temperature is not None:
            params["temperature"] = temperature
        if max_tokens and max_tokens > 0:
            params["max_tokens"] = max_tokens
        
        print(f"[OpenAIProvider] Using chat.completions for audio model: {model}")
        response = self.client.chat.completions.create(**params)
        
        text_content = response.choices[0].message.content or ""
        
        # Handle audio response
        if hasattr(response.choices[0].message, 'audio') and response.choices[0].message.audio:
            try:
                transcript = response.choices[0].message.audio.transcript or ""
                text_content = transcript
                
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                audio_dir = Path(HISTORY_DIR) / chat_id.replace('.json', '') / 'audio'
                audio_dir.mkdir(parents=True, exist_ok=True)
                
                audio_file = audio_dir / f"response_{timestamp}.wav"
                audio_bytes = base64.b64decode(response.choices[0].message.audio.data)
                with open(audio_file, 'wb') as f:
                    f.write(audio_bytes)
                
                def play_audio(file_path):
                    try:
                        try:
                            subprocess.run(['paplay', str(file_path)], check=True)
                        except (subprocess.CalledProcessError, FileNotFoundError):
                            subprocess.run(['aplay', str(file_path)], check=True)
                    except Exception as e:
                        print(f"Error playing audio: {e}")
                
                threading.Thread(target=play_audio, args=(audio_file,), daemon=True).start()
                text_content = f"{text_content}\n<audio_file>{audio_file}</audio_file>"
                
            except Exception as e:
                print(f"Error handling audio response: {e}")
        
        return text_content

    def _generate_with_chat_completions_reasoning(
        self,
        messages,
        model: str,
        max_tokens: int,
    ) -> str:
        """
        Generate a response using chat.completions for reasoning models (o1, o3).
        
        Reasoning models require special developer message formatting and don't
        support tools or temperature.
        """
        # Format messages for reasoning models
        formatted_messages = []
        formatting_flag_added = False

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Map system → developer for o1/o3 models
            if role == "system":
                role = "developer"
                if not formatting_flag_added:
                    if "Formatting re-enabled" not in content:
                        content = "Formatting re-enabled\n\n" + (content.lstrip() if isinstance(content, str) else content)
                    formatting_flag_added = True

            if not content:
                continue

            formatted_messages.append({
                "role": role,
                "content": [{"type": "text", "text": content}],
            })

        params = {
            "model": model,
            "messages": formatted_messages,
            "response_format": {"type": "text"},
        }
        
        if max_tokens and max_tokens > 0:
            params["max_tokens"] = max_tokens
        
        print(f"[OpenAIProvider] Using chat.completions for reasoning model: {model}")
        response = self.client.chat.completions.create(**params)
        return response.choices[0].message.content or ""

    def generate_chat_completion(
        self,
        messages,
        model,
        temperature=0.7,
        max_tokens=None,
        chat_id=None,
        web_search_enabled: bool = False,
        image_tool_handler=None,
        music_tool_handler=None,
        read_aloud_tool_handler=None,
    ):
        """
        Generate a chat completion using the most appropriate API.
        
        Routing logic:
        1. Audio models → chat.completions (requires modalities/audio params)
        2. Reasoning models (o1, o3) → chat.completions (requires developer messages)
        3. All other models → Responses API (supports web search, tools, files)
        
        The Responses API is the primary path as it supports:
        - Web search (for supported models)
        - Function tools (image/music/read_aloud)
        - File attachments
        - Image inputs
        """
        # Determine if we need to use chat.completions
        needs_chat_completions, reason = self._requires_chat_completions(model)
        
        if needs_chat_completions:
            if reason == "audio":
                return self._generate_with_chat_completions_audio(
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    chat_id=chat_id or "temp",
                )
            elif reason == "reasoning":
                return self._generate_with_chat_completions_reasoning(
                    messages=messages,
                    model=model,
                    max_tokens=max_tokens,
                )
        
        # Default path: use Responses API for everything else
        # This handles standard chat, files, images, tools, and web search
        print(f"[OpenAIProvider] Using Responses API for model: {model}")
        return self._generate_with_responses_api(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            web_search_enabled=web_search_enabled,
            image_tool_handler=image_tool_handler,
            music_tool_handler=music_tool_handler,
            read_aloud_tool_handler=read_aloud_tool_handler,
        )
    
    def generate_image(self, prompt, chat_id, model="dall-e-3", image_data=None):
        """
        Generate or edit an image using OpenAI image models.
        - For models like `dall-e-3` this performs text → image generation.
        - For `gpt-image-1`/`gpt-image-1-mini` with `image_data` this performs image → image editing.
        """
        if model in ("gpt-image-1", "gpt-image-1-mini") and image_data:
            # Image edit: decode the attached image and send it to the images.edit endpoint
            raw_bytes = base64.b64decode(image_data)
            
            # Create a temporary file for the uploaded image
            with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as temp_img:
                temp_img.write(raw_bytes)
                temp_img.flush()
                
                # Re‑open as a file handle for the SDK
                with open(temp_img.name, "rb") as img_file:
                    response = self.client.images.edit(
                        model=model,
                        image=img_file,
                        prompt=prompt,
                        n=1,
                        size="1024x1024",
                    )
            
            image_b64 = response.data[0].b64_json
            final_image_bytes = base64.b64decode(image_b64)
        else:
            # Standard image generation (no source image)
            response = self.client.images.generate(
                model=model,
                prompt=prompt,
                size="1024x1024",
                #quality="standard",
                n=1,
            )
            
            data_obj = response.data[0]
            final_image_bytes = None
            
            if getattr(data_obj, "url", None):
                download_response = requests.get(data_obj.url)
                download_response.raise_for_status()
                final_image_bytes = download_response.content
            elif getattr(data_obj, "b64_json", None):
                final_image_bytes = base64.b64decode(data_obj.b64_json)
            else:
                raise ValueError("Image response missing both URL and base64 data")
        
        images_dir = Path(HISTORY_DIR) / chat_id.replace('.json', '') / 'images'
        images_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        model_prefix = model.replace('-', '_')
        image_path = images_dir / f"{model_prefix}_{timestamp}.png"
        
        image_path.write_bytes(final_image_bytes)
        
        return f'<img src="{image_path}"/>'
    
    def transcribe_audio(self, audio_file):
        transcript = self.client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            timeout=20
        )
        return transcript.text
    
    def generate_speech(self, text, voice):
        return self.client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text
        )

    # Add a property to access audio functionality
    @property
    def audio(self):
        return self.client.audio

    def play_audio_file(self, file_path):
        """Play an audio file from the chat history"""
        if not Path(file_path).exists():
            print(f"Audio file not found: {file_path}")
            return
        
        def play_audio():
            try:
                # Try paplay first
                try:
                    subprocess.run(['paplay', str(file_path)], check=True)
                except (subprocess.CalledProcessError, FileNotFoundError):
                    # Fallback to aplay if paplay fails
                    subprocess.run(['aplay', str(file_path)], check=True)
            except Exception as e:
                print(f"Error playing audio: {e}")
        
        threading.Thread(target=play_audio, daemon=True).start()


class GrokProvider(AIProvider):
    """
    AI provider implementation for xAI's Grok models.
    Uses the OpenAI-compatible HTTP API at https://api.x.ai/v1.
    """

    BASE_URL = "https://api.x.ai/v1"

    def __init__(self):
        self.client = None

    def initialize(self, api_key: str):
        # Reuse the OpenAI client with a different base_url.
        self.client = OpenAI(api_key=api_key, base_url=self.BASE_URL)

    # ------------------------------------------------------------------
    # Helpers for Responses API + web search
    # ------------------------------------------------------------------

    def _supports_web_search_tool(self, model: str) -> bool:
        """
        Return True if the given Grok model should be offered the web_search/x_search tools.

        xAI's documentation indicates that modern Grok chat models support the Responses
        API with built-in web search tools. We conservatively enable web search for
        non-image Grok models.
        """
        if not model:
            return False

        model_lower = model.lower()

        # Skip obvious non-chat models.
        if "image" in model_lower:
            return False

        return model_lower.startswith("grok-")

    def _build_responses_input(self, messages):
        """
        Convert internal message format to Responses API input format for Grok.

        This mirrors the OpenAI Responses input structure but omits file uploads,
        since Grok integration currently does not support PDF/file attachments.

        Returns
        -------
        tuple
            (input_items, instructions)
        """
        input_items = []
        instructions = None

        for msg in messages:
            role = msg.get("role", "user")
            content_text = msg.get("content", "")
            images = msg.get("images", [])

            # Extract system messages for the instructions parameter.
            if role == "system":
                instructions = content_text
                continue

            # For now, skip assistant messages when building Responses input.
            # xAI's current Responses API rejects assistant-side `output_text`
            # style inputs, so we only send user/system content.
            if role == "assistant":
                continue

            # Build content parts for user messages.
            content_parts = []

            if content_text:
                content_parts.append(
                    {
                        "type": "input_text",
                        "text": content_text,
                    }
                )

            # Add image attachments (convert to base64 data URL format).
            for img in images:
                img_data = img.get("data", "")
                img_mime = img.get("mime_type", "image/jpeg")
                if img_data:
                    content_parts.append(
                        {
                            "type": "input_image",
                            "image_url": f"data:{img_mime};base64,{img_data}",
                        }
                    )

            if content_parts:
                input_items.append(
                    {
                        "type": "message",
                        "role": role,
                        "content": content_parts,
                    }
                )

        return input_items, instructions

    def _extract_responses_output(self, response) -> str:
        """
        Extract concatenated text content from a Grok Responses API response.

        For Grok web search we currently ignore function_call outputs and only
        care about the textual answer.
        """
        text_content = ""

        if hasattr(response, "output") and response.output:
            for item in response.output:
                item_type = getattr(item, "type", None)

                # Handle message output (contains text).
                if item_type == "message" and hasattr(item, "content"):
                    for content_item in item.content:
                        if hasattr(content_item, "text"):
                            text_content += content_item.text

        return text_content

    def _generate_with_responses_api(
        self,
        messages,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = None,
        web_search_enabled: bool = False,
    ) -> str:
        """
        Generate a response using xAI's Responses API for Grok models.

        This path is used primarily to enable web search via the built-in
        `web_search` and `x_search` tools when the web search toggle is on.
        """
        if not self.client:
            raise RuntimeError("Grok client not initialized")

        input_items, instructions = self._build_responses_input(messages)

        tools = []
        if web_search_enabled and self._supports_web_search_tool(model):
            # xAI supports both `web_search` and `x_search` tools per docs.
            tools.append({"type": "web_search"})
            tools.append({"type": "x_search"})

        params = {
            "model": model,
            "input": input_items,
        }

        if instructions:
            params["instructions"] = instructions

        if temperature is not None:
            params["temperature"] = float(temperature)

        if max_tokens and max_tokens > 0:
            params["max_output_tokens"] = int(max_tokens)

        if tools:
            params["tools"] = tools

        print(
            f"[GrokProvider] Calling Responses API with {len(input_items)} input items, "
            f"{len(tools)} tools (web_search_enabled={web_search_enabled})"
        )

        response = self.client.responses.create(**params)
        return self._extract_responses_output(response)

    def get_available_models(self, disable_filter: bool = False):
        """
        Return Grok models. If the xAI models.list endpoint is available,
        use it; otherwise, fall back to a small, curated set.
        """
        try:
            models = self.client.models.list()
            model_ids = [model.id for model in models]
            # print(f"[GrokProvider] models returned: {model_ids}")

            # Hardcode the primary image model so it's always available for testing,
            # even if it is not listed by the API.
            image_model_id = "grok-2-image-1212"
            if image_model_id not in model_ids:
                model_ids.append(image_model_id)

            # Allow disabling filtering via parameter or env var.
            env_val = os.getenv('DISABLE_MODEL_FILTER', '')
            disable_filter = disable_filter or env_val.strip().lower() in ('true', '1', 'yes')
            if disable_filter:
                return sorted(model_ids)

            # Prefer commonly used Grok chat and image models.
            allowed_models = {
                "grok-2-1212",
                "grok-2-vision-1212",
                "grok-2-image-1212",
                "grok-3",
                "grok-3-mini",
                "grok-4-1-fast-non-reasoning",
                "grok-4-1-fast-reasoning",
                "grok-4-fast-non-reasoning",
                "grok-4-fast-reasoning",
            }
            filtered = [m for m in model_ids if m in allowed_models]
            return sorted(filtered or model_ids)
        except Exception as exc:
            print(f"Error fetching Grok models: {exc}")
            # Fallback to a reasonable default set.
            return sorted(["grok-2", "grok-2-mini", "grok-2-image-1212"])

    def generate_chat_completion(
        self,
        messages,
        model,
        temperature=0.7,
        max_tokens=None,
        chat_id=None,
        # response_meta kept for interface compatibility; not used by Grok.
        web_search_enabled: bool = False,
        response_meta=None,
        image_tool_handler=None,
        music_tool_handler=None,
        read_aloud_tool_handler=None,
    ):
        """
        Generate a chat completion using Grok text models.

        Routing logic:
        - When web_search is enabled and the model supports it (and no function
          tools are in play), use the Responses API with web_search/x_search.
        - Otherwise, fall back to the standard chat.completions schema with
          optional function tools (image/music/read_aloud).
        """
        if not self.client:
            raise RuntimeError("Grok client not initialized")

        # Decide whether to route via the Responses API for web search.
        has_function_tools = any(
            handler is not None
            for handler in (image_tool_handler, music_tool_handler, read_aloud_tool_handler)
        )
        if web_search_enabled and not has_function_tools and self._supports_web_search_tool(model):
            return self._generate_with_responses_api(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                web_search_enabled=web_search_enabled,
            )

        # Clean messages for the OpenAI-compatible schema; drop provider-specific keys.
        # Also support image input using the same structure as OpenAI vision models.
        processed_messages = []
        for msg in messages:
            content = msg.get("content", "")

            # If the message has attached images, convert them to image_url parts.
            if "images" in msg and msg["images"]:
                content_parts = []
                if content:
                    content_parts.append({
                        "type": "text",
                        "text": content
                    })
                for img in msg["images"]:
                    mime_type = img.get("mime_type", "image/jpeg")
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{img['data']}",
                            "detail": "auto"
                        }
                    })
                processed_messages.append({
                    "role": msg.get("role", "user"),
                    "content": content_parts
                })
            else:
                clean_msg = {
                    k: v
                    for k, v in msg.items()
                    if k in ("role", "content", "name")
                }
                processed_messages.append(clean_msg)

        params = {
            "model": model,
            "messages": processed_messages,
        }
        if temperature is not None:
            params["temperature"] = float(temperature)
        if max_tokens and max_tokens > 0:
            params["max_tokens"] = int(max_tokens)

        # Enable tools for Grok chat models when handlers are supplied. xAI's
        # API follows the OpenAI tools schema:
        # https://docs.x.ai/docs/guides/tools/overview
        enabled_tools = set()
        if image_tool_handler is not None:
            enabled_tools.add("generate_image")
        if music_tool_handler is not None:
            enabled_tools.add("control_music")
        if read_aloud_tool_handler is not None:
            enabled_tools.add("read_aloud")
        tools = build_tools_for_provider(enabled_tools, "grok")
        if tools:
            params["tools"] = tools
            params["tool_choice"] = "auto"

        # Simple one-shot path when no tools are involved.
        if image_tool_handler is None and music_tool_handler is None and read_aloud_tool_handler is None:
            response = self.client.chat.completions.create(**params)
            return response.choices[0].message.content or ""

        # Tool-aware flow for Grok: let the model call generate_image, route that
        # through the handler, and then append the resulting <img> tags so the
        # UI can render images even if the model does not echo them back.
        tool_aware_messages = params["messages"]
        max_tool_rounds = 3
        last_response = None
        tool_result_snippets = []

        for _ in range(max_tool_rounds):
            last_response = self.client.chat.completions.create(
                **{
                    **params,
                    "messages": tool_aware_messages,
                }
            )
            msg = last_response.choices[0].message

            tool_calls = getattr(msg, "tool_calls", None) or []
            if not tool_calls:
                # No tools requested; this is the final assistant answer.
                break

            # Append the assistant message that requested tools.
            tool_aware_messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )

            # For each tool call, invoke the appropriate handler and append a tool result.
            tool_context = ToolContext(
                image_handler=image_tool_handler,
                music_handler=music_tool_handler,
                read_aloud_handler=read_aloud_tool_handler,
            )
            for tc in tool_calls:
                if tc.type != "function":
                    tool_result_content = "Error: unknown tool requested."
                else:
                    parsed_args = parse_tool_arguments(tc.function.arguments or "{}")
                    tool_result_content = run_tool_call(tc.function.name, parsed_args, tool_context)

                if tool_result_content:
                    tool_result_snippets.append(tool_result_content)

                tool_aware_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.function.name,
                        "content": tool_result_content or "",
                    }
                )

        if last_response is None:
            raise RuntimeError("No response received from Grok chat completion.")

        base_text = last_response.choices[0].message.content or ""
        if tool_result_snippets:
            return base_text + "\n\n" + "\n\n".join(tool_result_snippets)
        return base_text

    def generate_image(self, prompt, chat_id, model="grok-2-image", image_data=None, mime_type=None):
        """
        Generate an image using Grok image models (e.g. grok-2-image-1212).
        Currently supports text → image generation.
        """
        if not self.client:
            raise RuntimeError("Grok client not initialized")

        # xAI's API currently does not support the OpenAI-style `size` argument,
        # so we omit it and let the API choose defaults.
        response = self.client.images.generate(
            model=model,
            prompt=prompt,
            n=1,
        )

        data_obj = response.data[0]
        final_image_bytes = None

        if getattr(data_obj, "url", None):
            download_response = requests.get(data_obj.url)
            download_response.raise_for_status()
            final_image_bytes = download_response.content
        elif getattr(data_obj, "b64_json", None):
            final_image_bytes = base64.b64decode(data_obj.b64_json)
        else:
            raise ValueError("Grok image response missing both URL and base64 data")

        images_dir = Path(HISTORY_DIR) / (chat_id.replace('.json', '') if chat_id else 'temp') / 'images'
        images_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        model_prefix = model.replace('-', '_')
        image_path = images_dir / f"{model_prefix}_{timestamp}.png"

        image_path.write_bytes(final_image_bytes)

        return f'<img src="{image_path}"/>'

    def transcribe_audio(self, audio_file):
        raise NotImplementedError("Grok provider does not support audio transcription yet.")

    def generate_speech(self, text, voice):
        raise NotImplementedError("Grok provider does not support TTS yet.")


class ClaudeProvider(AIProvider):
    """
    AI provider implementation for Anthropic Claude models using the
    OpenAI SDK compatibility layer.

    See: `https://platform.claude.com/docs/en/api/openai-sdk`
    """

    # Claude OpenAI-compatible endpoint base URL.
    BASE_URL = "https://api.anthropic.com/v1/"

    def __init__(self):
        self.client = None

    def initialize(self, api_key: str):
        """
        Initialize the Claude client using the OpenAI SDK with a custom base URL.
        """
        # We reuse the official OpenAI client, pointing it at the Claude
        # compatibility endpoint as described in the Anthropic docs:
        # `https://platform.claude.com/docs/en/api/openai-sdk`
        self.client = OpenAI(api_key=api_key, base_url=self.BASE_URL)

    def get_available_models(self, disable_filter: bool = False):
        """
        Return Claude models.

        The Anthropic OpenAI SDK compatibility docs (`https://platform.claude.com/docs/en/api/openai-sdk`)
        only guarantee support for chat/completions-style endpoints. The models.list
        endpoint is not documented and may reject otherwise valid API keys.

        To avoid confusing 401 errors during startup, we skip models.list entirely
        and return a curated set of known Claude chat models, with optional filtering.
        """
        # Base curated set; extendable over time.
        allowed_models = {
            "claude-sonnet-4-5", 
            "claude-haiku-4-5",
            "claude-opus-4-5",
            "claude-3-5-sonnet-latest",
            "claude-3-5-haiku-latest",
        }

        # Allow disabling filtering via parameter or env var to keep similar
        # semantics to other providers, even though we currently only have a
        # static set here.
        env_val = os.getenv('DISABLE_MODEL_FILTER', '')
        disable_filter = disable_filter or env_val.strip().lower() in ('true', '1', 'yes')
        if disable_filter:
            return sorted(allowed_models)

        return sorted(allowed_models)

    def generate_chat_completion(
        self,
        messages,
        model,
        temperature=0.7,
        max_tokens=None,
        chat_id=None,
        response_meta=None,
        web_search_enabled: bool = False,
        image_tool_handler=None,
        music_tool_handler=None,
        read_aloud_tool_handler=None,
    ):
        """
        Generate a chat completion using Claude models via the OpenAI-compatible
        /v1/chat/completions endpoint.
        """
        if not self.client:
            raise RuntimeError("Claude client not initialized")

        # Clean messages for the OpenAI-compatible schema; drop provider-specific keys.
        # Also support image input using the same structure as OpenAI vision models.
        processed_messages = []
        for msg in messages:
            content = msg.get("content", "")

            # If the message has attached images, convert them to image_url parts.
            if "images" in msg and msg["images"]:
                content_parts = []
                if content:
                    content_parts.append({
                        "type": "text",
                        "text": content
                    })
                for img in msg["images"]:
                    mime_type = img.get("mime_type", "image/jpeg")
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{img['data']}",
                            "detail": "auto"
                        }
                    })
                processed_messages.append({
                    "role": msg.get("role", "user"),
                    "content": content_parts
                })
            else:
                clean_msg = {
                    k: v
                    for k, v in msg.items()
                    if k in ("role", "content", "name")
                }
                processed_messages.append(clean_msg)

        params = {
            "model": model,
            "messages": processed_messages,
        }
        if temperature is not None:
            # Anthropic supports temperature in [0, 1]; higher values are capped
            # according to the OpenAI compatibility docs:
            # `https://platform.claude.com/docs/en/api/openai-sdk`
            params["temperature"] = float(temperature)
        if max_tokens and max_tokens > 0:
            params["max_tokens"] = int(max_tokens)

        # Enable tools for Claude chat models when handlers are supplied. The
        # compatibility layer supports the OpenAI tools schema.
        enabled_tools = set()
        if image_tool_handler is not None:
            enabled_tools.add("generate_image")
        if music_tool_handler is not None:
            enabled_tools.add("control_music")
        if read_aloud_tool_handler is not None:
            enabled_tools.add("read_aloud")
        tools = build_tools_for_provider(enabled_tools, "claude")
        if tools:
            params["tools"] = tools
            params["tool_choice"] = "auto"

        # Simple one-shot path when no tools are involved.
        if image_tool_handler is None and music_tool_handler is None and read_aloud_tool_handler is None:
            response = self.client.chat.completions.create(**params)
            return response.choices[0].message.content or ""

        # Tool-aware flow for Claude: let the model call tools, route them
        # through handlers, and append results (e.g. <img> tags) so the UI can
        # render them even if the model does not echo them back explicitly.
        tool_aware_messages = params["messages"]
        max_tool_rounds = 3
        last_response = None
        tool_result_snippets = []

        for _ in range(max_tool_rounds):
            last_response = self.client.chat.completions.create(
                **{
                    **params,
                    "messages": tool_aware_messages,
                }
            )
            msg = last_response.choices[0].message

            tool_calls = getattr(msg, "tool_calls", None) or []
            if not tool_calls:
                # No tools requested; this is the final assistant answer.
                break

            # Append the assistant message that requested tools.
            tool_aware_messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )

            # For each tool call, invoke the appropriate handler and append a tool result.
            tool_context = ToolContext(
                image_handler=image_tool_handler,
                music_handler=music_tool_handler,
                read_aloud_handler=read_aloud_tool_handler,
            )
            for tc in tool_calls:
                if tc.type != "function":
                    tool_result_content = "Error: unknown tool requested."
                else:
                    parsed_args = parse_tool_arguments(tc.function.arguments or "{}")
                    tool_result_content = run_tool_call(tc.function.name, parsed_args, tool_context)

                if tool_result_content:
                    tool_result_snippets.append(tool_result_content)

                tool_aware_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.function.name,
                        "content": tool_result_content or "",
                    }
                )

        if last_response is None:
            raise RuntimeError("No response received from Claude chat completion.")

        base_text = last_response.choices[0].message.content or ""
        if tool_result_snippets:
            return base_text + "\n\n" + "\n\n".join(tool_result_snippets)
        return base_text

    def generate_image(self, prompt, chat_id, model=None, image_data=None, mime_type=None):
        """
        Claude's OpenAI-compatible API does not currently expose a dedicated
        image-generation endpoint in this integration. Image generation is
        handled via the shared image tool instead.
        """
        raise NotImplementedError("Claude provider does not support direct image generation.")

    def transcribe_audio(self, audio_file):
        raise NotImplementedError("Claude provider does not support audio transcription yet.")

    def generate_speech(self, text, voice):
        raise NotImplementedError("Claude provider does not support TTS yet.")


class PerplexityProvider(AIProvider):
    """
    AI provider implementation for Perplexity AI models.
    Uses the OpenAI-compatible HTTP API at https://api.perplexity.ai.
    
    See: https://docs.perplexity.ai/guides/chat-completions-guide
    """

    BASE_URL = "https://api.perplexity.ai"

    def __init__(self):
        self.client = None

    def initialize(self, api_key: str):
        """Initialize the Perplexity client using the OpenAI SDK with a custom base URL."""
        self.client = OpenAI(api_key=api_key, base_url=self.BASE_URL)

    def get_available_models(self, disable_filter: bool = False):
        """
        Return Perplexity models.
        
        Perplexity's API does not provide a models.list endpoint, so we return
        a curated set of known Sonar models.
        """
        # Curated set of Perplexity Sonar models
        allowed_models = {
            "sonar",
            "sonar-pro",
            "sonar-reasoning",
        }

        # Allow disabling filtering via parameter or env var
        env_val = os.getenv('DISABLE_MODEL_FILTER', '')
        disable_filter = disable_filter or env_val.strip().lower() in ('true', '1', 'yes')
        if disable_filter:
            return sorted(allowed_models)

        return sorted(allowed_models)

    def generate_chat_completion(
        self,
        messages,
        model,
        temperature=0.7,
        max_tokens=None,
        chat_id=None,
        response_meta=None,
        web_search_enabled: bool = False,
        image_tool_handler=None,
        music_tool_handler=None,
        read_aloud_tool_handler=None,
    ):
        """
        Generate a chat completion using Perplexity models via the OpenAI-compatible
        /chat/completions endpoint.
        
        Note: Perplexity Sonar models have built-in web search capabilities.
        """
        if not self.client:
            raise RuntimeError("Perplexity client not initialized")

        # Clean messages for the OpenAI-compatible schema; drop provider-specific keys.
        # Note: Perplexity does not support image inputs currently.
        processed_messages = []
        for msg in messages:
            clean_msg = {
                k: v
                for k, v in msg.items()
                if k in ("role", "content", "name")
            }
            processed_messages.append(clean_msg)

        params = {
            "model": model,
            "messages": processed_messages,
        }
        if temperature is not None:
            params["temperature"] = float(temperature)
        if max_tokens and max_tokens > 0:
            params["max_tokens"] = int(max_tokens)

        # Perplexity doesn't support function calling tools in the same way as OpenAI,
        # so we use a simple one-shot path.
        response = self.client.chat.completions.create(**params)
        content = response.choices[0].message.content or ""

        # Capture web search results (if any) into provider metadata so they can be
        # persisted with chat history and rendered alongside the answer.
        #
        # Per the Perplexity docs:
        # https://docs.perplexity.ai/guides/chat-completions-guide
        # responses include a `search_results` field with title / URL / date.
        if response_meta is not None:
            try:
                search_results = getattr(response, "search_results", None)
            except Exception:
                search_results = None

            if search_results:
                normalized_results = []
                for item in search_results:
                    # `item` may be a plain dict or an object with attributes.
                    if isinstance(item, dict):
                        title = item.get("title")
                        url = item.get("url")
                        date = item.get("date")
                    else:
                        title = getattr(item, "title", None)
                        url = getattr(item, "url", None)
                        date = getattr(item, "date", None)

                    norm = {}
                    if title is not None:
                        norm["title"] = str(title)
                    if url is not None:
                        norm["url"] = str(url)
                    if date is not None:
                        norm["date"] = str(date)

                    if norm:
                        normalized_results.append(norm)

                if normalized_results:
                    perplexity_meta = response_meta.setdefault("perplexity", {})
                    perplexity_meta["search_results"] = normalized_results

        return content

    def generate_image(self, prompt, chat_id, model=None, image_data=None, mime_type=None):
        """Perplexity does not support image generation."""
        raise NotImplementedError("Perplexity provider does not support image generation.")

    def transcribe_audio(self, audio_file):
        raise NotImplementedError("Perplexity provider does not support audio transcription.")

    def generate_speech(self, text, voice):
        raise NotImplementedError("Perplexity provider does not support TTS.")


class GeminiProvider(AIProvider):
    """AI provider implementation for Google's Gemini API."""
    
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    
    def __init__(self):
        self.api_key = None
    
    def initialize(self, api_key: str):
        self.api_key = api_key
    
    def _require_key(self):
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable not set")
    
    def _headers(self):
        self._require_key()
        return {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key
        }
    
    def _convert_messages(self, messages):
        contents = []
        system_instruction = None
        for msg in messages:
            role = msg.get("role", "user")
            text = msg.get("content", "")
            
            if role == "system":
                system_instruction = text
                continue
            
            if not text and not msg.get("images"):
                continue

            gemini_role = "user" if role == "user" else "model"
            
            parts = []
            if text:
                parts.append({"text": text})
            
            if "images" in msg and msg["images"]:
                for img in msg["images"]:
                    parts.append({
                        "inlineData": {
                            "mimeType": img.get("mime_type", "image/jpeg"),
                            "data": img["data"]
                        }
                    })
            
            contents.append({
                "role": gemini_role,
                "parts": parts
            })
        return contents, system_instruction
    
    def _extract_text(self, response_json):
        candidates = response_json.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        text_segments = []
        for part in parts:
            if "text" in part:
                text_segments.append(part["text"])
        return "".join(text_segments).strip()

    def _find_thought_signatures(self, obj):
        """
        Recursively search a response JSON object for any Gemini thought signature fields.
        We treat these as opaque provider metadata and simply return the first match.
        """
        if isinstance(obj, dict):
            for key, value in obj.items():
                # Support both snake_case and camelCase just in case.
                if key in ("thought_signatures", "thoughtSignatures"):
                    return value
                found = self._find_thought_signatures(value)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = self._find_thought_signatures(item)
                if found is not None:
                    return found
        return None
    
    def get_available_models(self, disable_filter=False):
        self._require_key()
        try:
            resp = requests.get(
                f"{self.BASE_URL}/models",
                headers=self._headers(),
                params={"pageSize": 50},
                timeout=30
            )
            resp.raise_for_status()
            data = resp.json()
            models = []
            for model in data.get("models", []):
                name = model.get("name", "")
                if not name:
                    continue
                model_id = name.split("/")[-1]
                if "generateContent" in model.get("supportedGenerationMethods", []):
                    models.append(model_id)

            # Check both parameter and environment variable
            disable_filter = disable_filter or os.getenv('DISABLE_MODEL_FILTER', '').lower() in ('true', '1', 'yes')
            if disable_filter:
                # Return all available models when filtering is disabled
                return sorted(models) if models else []

            # Default filtering behavior for Gemini
            allowed_models = {"gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-image",
                            "gemini-3-pro-preview", "gemini-pro", "gemini-pro-vision",
                            "gemini-pro-latest", "gemini-flash-latest", "gemini-3-pro-image-preview"}
            filtered_models = [model_id for model_id in models if model_id in allowed_models]
            if filtered_models:
                return sorted(filtered_models)
        except Exception as exc:
            print(f"Error fetching Gemini models: {exc}")
        return sorted(["gemini-flash-latest", "gemini-pro-latest"])
    
    def generate_chat_completion(
        self,
        messages,
        model,
        temperature=0.7,
        max_tokens=None,
        chat_id=None,
        response_meta=None,
        web_search_enabled: bool = False,
        image_tool_handler=None,
        music_tool_handler=None,
        read_aloud_tool_handler=None,
    ):
        self._require_key()
        contents, system_instruction = self._convert_messages(messages)
        payload = {
            "contents": contents
        }

        # Reuse any previously returned thought signatures, if present.
        # We scan the incoming messages for provider-specific Gemini metadata.
        thought_sigs = None
        for msg in messages or []:
            meta = msg.get("provider_meta") if isinstance(msg, dict) else None
            if not isinstance(meta, dict):
                continue
            gem_meta = meta.get("gemini")
            if isinstance(gem_meta, dict) and "thought_signatures" in gem_meta:
                thought_sigs = gem_meta["thought_signatures"]
        if thought_sigs is not None:
            # Attach exactly as stored; Gemini will interpret or ignore as appropriate.
            payload["thought_signatures"] = thought_sigs

        if system_instruction:
            payload["system_instruction"] = {
                "parts": [{"text": system_instruction}]
            }
        generation_config = {}
        if temperature is not None:
            generation_config["temperature"] = temperature
        if max_tokens and max_tokens > 0:
            generation_config["max_output_tokens"] = max_tokens
        if generation_config:
            payload["generation_config"] = generation_config

        # Optionally enable Google grounding with Search for supported models,
        # following the Gemini API docs:
        # https://ai.google.dev/gemini-api/docs/google-search
        def _supports_google_search_tool(model_name: str) -> bool:
            if not model_name:
                return False
            name = model_name.lower()
            # Google Search grounding is available for Gemini 2.x+ models; we avoid
            # attaching it to legacy 1.5 models that rely on google_search_retrieval.
            return name.startswith("gemini-2.") or name.startswith("gemini-3.")

        if web_search_enabled and _supports_google_search_tool(model):
            payload.setdefault("tools", []).append({"google_search": {}})

        # When tool handlers are provided, expose corresponding function
        # declarations to Gemini using its functionDeclarations schema,
        # mirroring the documented pattern in the Gemini function calling guide:
        # https://ai.google.dev/gemini-api/docs/function-calling?example=meeting
        enabled_tools = set()
        if image_tool_handler is not None:
            enabled_tools.add("generate_image")
        if music_tool_handler is not None:
            enabled_tools.add("control_music")
        if read_aloud_tool_handler is not None:
            enabled_tools.add("read_aloud")
        function_declarations = build_tools_for_provider(enabled_tools, "gemini")
        if function_declarations:
            payload.setdefault("tools", []).append(
                {"functionDeclarations": function_declarations}
            )
        
        try:
            resp = requests.post(
                f"{self.BASE_URL}/models/{model}:generateContent",
                headers=self._headers(),
                json=payload,
                timeout=60
            )
            resp.raise_for_status()
            data = resp.json()

            # Capture any thought signatures as opaque provider metadata for the caller.
            if response_meta is not None:
                thought_sigs = self._find_thought_signatures(data)
                if thought_sigs is not None:
                    gemini_meta = response_meta.setdefault("gemini", {})
                    gemini_meta["thought_signatures"] = thought_sigs

            # If no tool handlers are supplied, fall back to the existing
            # simple text-extraction behavior.
            if image_tool_handler is None and music_tool_handler is None and read_aloud_tool_handler is None:
                return self._extract_text(data)

            # With tool handlers, inspect the response for any functionCall
            # parts, invoke the appropriate handler, and append the results
            # (and a short caption) to the text we return so the UI can render
            # images and/or show music control feedback.
            base_text = self._extract_text(data)
            tool_segments = []

            tool_context = ToolContext(
                image_handler=image_tool_handler,
                music_handler=music_tool_handler,
                read_aloud_handler=read_aloud_tool_handler,
            )
            for candidate in data.get("candidates", []) or []:
                parts = candidate.get("content", {}).get("parts", []) or []
                for part in parts:
                    fn = part.get("functionCall")
                    if not fn:
                        continue
                    name = fn.get("name")
                    args = fn.get("args") or {}

                    tool_output = run_tool_call(name, args, tool_context)

                    if tool_output:
                        # Build a caption based on the tool name.
                        if name == "generate_image":
                            caption = f"Generated image for prompt: {args.get('prompt', '')}".strip()
                        elif name == "control_music":
                            caption = f"Music control result for action: {args.get('action', '')}".strip()
                        elif name == "read_aloud":
                            caption = f"Read aloud: {args.get('text', '')[:50]}...".strip() if len(args.get('text', '')) > 50 else f"Read aloud: {args.get('text', '')}".strip()
                        else:
                            caption = ""
                        segment = f"{caption}\n{tool_output}" if caption else tool_output
                        tool_segments.append(segment)

            if not tool_segments:
                return base_text

            if base_text:
                return base_text + "\n\n" + "\n\n".join(tool_segments)
            return "\n\n".join(tool_segments)
        except Exception as exc:
            raise RuntimeError(f"Gemini completion failed: {exc}") from exc
    
    def generate_image(self, prompt, chat_id, model="gemini-3-pro-image-preview", image_data=None, mime_type=None):
        """
        Generate or transform an image using Gemini image models.
        - When `image_data` is None, this is text → image generation.
        - When `image_data` is provided, this is image → image with text instructions.
        """
        self._require_key()
        parts = []
        if image_data:
            parts.append({
                "inlineData": {
                    "mimeType": mime_type or "image/png",
                    "data": image_data
                }
            })
        if prompt:
            parts.append({"text": prompt})

        payload = {
            "contents": [{
                "role": "user",
                "parts": parts or [{"text": ""}]
            }]
        }
        try:
            resp = requests.post(
                f"{self.BASE_URL}/models/{model}:generateContent",
                headers=self._headers(),
                json=payload,
                timeout=60
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(f"Gemini image generation failed: {exc}") from exc
        
        candidates = data.get("candidates", [])
        if not candidates:
            raise ValueError("No image returned from Gemini")
        
        inline_data = None
        for candidate in candidates:
            parts = candidate.get("content", {}).get("parts", [])
            for part in parts:
                if "inlineData" in part:
                    inline_data = part["inlineData"].get("data")
                    break
            if inline_data:
                break
        
        if not inline_data:
            raise ValueError("Gemini response missing inline image data")
        
        image_bytes = base64.b64decode(inline_data)
        images_dir = Path(HISTORY_DIR) / (chat_id.replace('.json', '') if chat_id else 'temp') / 'images'
        images_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        image_path = images_dir / f"{model.replace('-', '_')}_{timestamp}.png"
        image_path.write_bytes(image_bytes)
        return f'<img src="{image_path}"/>'
    
    def transcribe_audio(self, audio_file):
        raise NotImplementedError("Gemini provider does not support audio transcription yet.")
    
    def generate_speech(self, text: str, voice: str) -> bytes:
        """
        Generate speech audio using Gemini TTS model.
        
        Parameters
        ----------
        text : str
            The text to synthesize into speech.
        voice : str
            The Gemini voice name (e.g., "Zephyr", "Puck", "Kore").
            
        Returns
        -------
        bytes
            The WAV audio data (with proper header).
            
        Raises
        ------
        RuntimeError
            If the API call fails or no audio is returned.
        """
        self._require_key()
        
        # Gemini TTS model
        model = "gemini-2.5-flash-preview-tts"
        
        # Build the request payload following Gemini speech generation docs
        # The voice is specified in speechConfig
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": text}]
                }
            ],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": voice
                        }
                    }
                }
            }
        }
        
        try:
            resp = requests.post(
                f"{self.BASE_URL}/models/{model}:generateContent",
                headers=self._headers(),
                json=payload,
                timeout=120  # TTS can take a while for longer texts
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.RequestException as exc:
            raise RuntimeError(f"Gemini TTS API call failed: {exc}") from exc
        
        # Extract audio data from response
        # Gemini returns audio as base64-encoded data in inlineData
        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini TTS returned no candidates")
        
        audio_data = None
        mime_type = None
        for candidate in candidates:
            parts = candidate.get("content", {}).get("parts", [])
            for part in parts:
                inline_data = part.get("inlineData")
                if inline_data and inline_data.get("mimeType", "").startswith("audio/"):
                    audio_data = inline_data.get("data")
                    mime_type = inline_data.get("mimeType", "")
                    break
            if audio_data:
                break
        
        if not audio_data:
            raise RuntimeError("Gemini TTS response missing audio data")
        
        # Decode the base64 audio data
        raw_audio = base64.b64decode(audio_data)
        
        # Gemini TTS returns LINEAR16 PCM data at 24kHz mono
        # If it's raw PCM (audio/L16), we need to add a WAV header
        if "L16" in mime_type or "pcm" in mime_type.lower():
            # Add WAV header for 24kHz, 16-bit, mono PCM
            return self._add_wav_header(raw_audio, sample_rate=24000, channels=1, bits_per_sample=16)
        
        # If it's already WAV or another playable format, return as-is
        return raw_audio
    
    def _add_wav_header(self, pcm_data: bytes, sample_rate: int = 24000, channels: int = 1, bits_per_sample: int = 16) -> bytes:
        """
        Add a WAV header to raw PCM audio data.
        
        Parameters
        ----------
        pcm_data : bytes
            Raw PCM audio samples.
        sample_rate : int
            Sample rate in Hz (default 24000 for Gemini TTS).
        channels : int
            Number of audio channels (default 1 for mono).
        bits_per_sample : int
            Bits per sample (default 16).
            
        Returns
        -------
        bytes
            Complete WAV file with header.
        """
        import struct
        
        byte_rate = sample_rate * channels * bits_per_sample // 8
        block_align = channels * bits_per_sample // 8
        data_size = len(pcm_data)
        
        # WAV header (44 bytes)
        header = struct.pack(
            '<4sI4s4sIHHIIHH4sI',
            b'RIFF',                    # ChunkID
            36 + data_size,             # ChunkSize
            b'WAVE',                    # Format
            b'fmt ',                    # Subchunk1ID
            16,                         # Subchunk1Size (PCM)
            1,                          # AudioFormat (1 = PCM)
            channels,                   # NumChannels
            sample_rate,                # SampleRate
            byte_rate,                  # ByteRate
            block_align,                # BlockAlign
            bits_per_sample,            # BitsPerSample
            b'data',                    # Subchunk2ID
            data_size                   # Subchunk2Size
        )
        
        return header + pcm_data

class OpenAIWebSocketProvider:
    def __init__(self):
        self.ws = None
        self.loop = None
        self.thread = None
        self.is_recording = False
        self.audio_buffer = bytearray()
        self.is_ai_speaking = False  # New flag to track AI speech state
        self.last_event_id = None  # Track event ID for responses
        
        # Audio configuration
        self.input_sample_rate = 48000  # Input from mic
        self.output_sample_rate = 24000  # Server rate
        self.channels = 1
        self.dtype = np.int16
        self.min_audio_ms = 100
        
        self.output_stream = None
        self.message_lock = asyncio.Lock()  # Add lock for message handling
        self._lock = threading.Lock()
        
    def start_loop(self):
        """Start the event loop in a new thread if not already running"""
        with self._lock:
            if self.thread is None or not self.thread.is_alive():
                self.loop = asyncio.new_event_loop()
                self.thread = threading.Thread(target=self.run_loop, daemon=True)
                self.thread.start()

    def run_loop(self):
        """Run the event loop"""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def stop_loop(self):
        """Safely stop the event loop"""
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
            if self.thread and self.thread.is_alive():
                self.thread.join()
            self.loop.close()
            self.loop = None
            self.thread = None

    def __del__(self):
        """Cleanup when the object is destroyed"""
        self.stop_loop()
        if self.output_stream:
            self.output_stream.stop()
            self.output_stream.close()

    async def ensure_connection(self, voice):
        """Ensure we have an active WebSocket connection"""
        print(f"Ensuring connection")
        if not self.ws or not self.ws.open:
            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                raise ValueError("OPENAI_API_KEY environment variable not set")
                
            # Get model from URL parameters
            model = getattr(self, 'model', 'gpt-4o-realtime-preview')  # Default fallback
            
            self.ws = await websockets.connect(
                f"wss://api.openai.com/v1/realtime?model={model}",
                extra_headers={
                    "Authorization": f"Bearer {api_key}",
                    "OpenAI-Beta": "realtime=v1"
                }
            )
            print(f"Connected to server using model: {model}")
            
            # Send initial configuration with session parameters
            config_message = {
                "type": "response.create",
                "response": {
                    "modalities": ["text", "audio"],
                    "instructions": self.system_message,
                    "temperature": self.temperature,
                    "voice": "alloy",        # Current voice options for realtime models are: alloy, ash, ballad, coral, echo sage, shimmer, verse
                }
            }
            config_message2 = {
                "type": "session.update",
                "session": {
                    "modalities": ["text", "audio"],
                    "instructions": self.system_message,
                    "voice": voice,
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "input_audio_transcription": {
                        # "enabled": True,
                        "model": "whisper-1"
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.1,
                        "prefix_padding_ms": 10,
                        "silence_duration_ms": 999
                    },
                }
            }
            await self.ws.send(json.dumps(config_message2))
            print("Sent initial configuration message")

            # Wait for session.updated confirmation
            while True:
                response = await self.ws.recv()
                if isinstance(response, str):
                    data = json.loads(response)
                    if data.get("type") == "session.updated":
                        self.last_event_id = data.get("event_id")  # Store the event ID
                        print("Session configuration confirmed")
                        break
            
    def _initialize_output_stream(self):
        """Initialize audio output stream if needed"""
        if self.output_stream is None:
            self.output_stream = sd.OutputStream(
                channels=1,
                samplerate=self.output_sample_rate,
                dtype=np.int16,
                blocksize=4800,  # 200ms chunks at 24kHz
                latency='low'
            )
            self.output_stream.start()
        
    async def start_audio_stream(self, callback):
        """Start streaming audio to the API"""
        try:
            await self.ensure_connection(self.voice)
            
            self.is_recording = True
            
            # Initialize audio output stream
            self._initialize_output_stream()
            
            # Find the device index for the selected microphone
            devices = sd.query_devices()
            device_idx = None
            for i, device in enumerate(devices):
                if device['name'] == self.microphone and device['max_input_channels'] > 0:
                    device_idx = i
                    break
            
            print(f"Found device index: {device_idx}")
            
            # If selected microphone not found, use default
            if device_idx is None:
                print("Using default input device")  # Add this debug print
                device_idx = sd.default.device[0]
            
            # Query device capabilities
            device_info = sd.query_devices(device_idx, 'input')
            if device_info is not None:
                # Use the device's supported sample rate
                supported_sample_rate = int(device_info['default_samplerate'])
            else:
                supported_sample_rate = 24000  # fallback
            
            # Start audio input stream with specific format
            stream = sd.InputStream(
                device=device_idx,
                channels=1,
                samplerate=supported_sample_rate,
                dtype=np.float32,
                blocksize=int(supported_sample_rate * 0.2),  # 200ms chunks
                callback=self.audio_callback
            )
            
            with stream:
                print(f"Started audio input stream: {supported_sample_rate}Hz, 1 channels")
                print(f"Using microphone: {devices[device_idx]['name']}")
                print(f"Resampling from {self.input_sample_rate}Hz to {self.output_sample_rate}Hz")
                
                while self.is_recording:
                    try:
                        message = await self.ws.recv()
                        if isinstance(message, str):
                            response = json.loads(message)
                            
                            # Update event ID from responses
                            if "event_id" in response:
                                self.last_event_id = response["event_id"]
                            
                            # Track AI speech state
                            if response.get("type") == "response.created":
                                print("Speech started - pausing mic input")
                                self.is_ai_speaking = True
                            elif response.get("type") == "response.done":
                                print("Speech ended - resuming mic input")
                                self.is_ai_speaking = False
                            
                            # Only log non-heartbeat messages
                            if response.get("type") != "heartbeat":
                                print(("Received event: " + json.dumps(response, indent=2))[:250])
                            
                            if "text" in response:
                                print(f"Received text: {response['text']}")
                                GLib.idle_add(callback, response["text"])
                            elif response.get("type") == "response.audio.delta":
                                try:
                                    # Get the audio delta data
                                    audio_bytes = base64.b64decode(response["delta"])
                                    print(f"Received audio delta: {len(audio_bytes)} bytes")
                                    
                                    # Convert to numpy array
                                    audio_data = np.frombuffer(audio_bytes, dtype=np.int16)
                                    
                                    # Ensure audio is in correct shape for playback
                                    if audio_data.ndim == 1:
                                        audio_data = audio_data.reshape(-1, 1)
                                    
                                    # Write to output stream
                                    self.output_stream.write(audio_data)
                                    print(f"Played audio chunk: shape={audio_data.shape}, dtype={audio_data.dtype}")
                                except Exception as e:
                                    print(f"Error playing audio delta: {e}")
                                    import traceback
                                    traceback.print_exc()
                            elif response.get("type") == "error":
                                print(f"Error from server: {response}")
                                if response.get("error", {}).get("code") != "end_of_speech":
                                    break
                            elif "audio" in response:  # Audio data in base64
                                try:
                                    # Decode base64 audio data
                                    audio_bytes = base64.b64decode(response["audio"])
                                    print(f"Received audio data: {len(audio_bytes)} bytes")
                                    
                                    # Convert to numpy array and ensure correct format
                                    audio_data = np.frombuffer(audio_bytes, dtype=np.int16)
                                    
                                    # Ensure audio is in correct shape for playback
                                    if audio_data.ndim == 1:
                                        audio_data = audio_data.reshape(-1, 1)
                                    
                                    # Write to output stream
                                    self.output_stream.write(audio_data)
                                    print(f"Played audio chunk: shape={audio_data.shape}, dtype={audio_data.dtype}")
                                except Exception as e:
                                    print(f"Error playing audio: {e}")
                                    import traceback
                                    traceback.print_exc()
                        
                    except websockets.exceptions.ConnectionClosed as e:
                        print(f"WebSocket closed with code {e.code}: {e.reason}")
                        if not self.is_recording:  # Only break if we're stopping
                            break
                        # Try to reconnect
                        try:
                            await self.ensure_connection(self.voice)
                            continue
                        except:
                            break
                    except Exception as e:
                        print(f"Error processing message: {e}")
                        if not self.is_recording:
                            break
                        
        except Exception as e:
            print(f"Error in audio stream: {e}")
            GLib.idle_add(callback, f"\nError: {str(e)}")
        finally:
            self.is_recording = False
            if hasattr(self, 'output_stream'):
                self.output_stream.stop()
                self.output_stream.close()
            print("Audio streaming stopped")

    def audio_callback(self, indata, frames, time, status):
        """Callback for audio input"""
        if status:
            print(f"Audio input status: {status}")
            
        # Skip recording if AI is speaking to prevent feedback
        if self.is_ai_speaking:
            return
            
        if self.ws and self.ws.open and self.is_recording:
            try:
                # Normalize and scale the audio data
                audio_data = indata.copy()
                audio_data = audio_data.flatten()
                
                # Resample from 48kHz to 24kHz
                resampled_size = int(len(audio_data) * self.output_sample_rate / self.input_sample_rate)
                resampled_data = np.interp(
                    np.linspace(0, len(audio_data), resampled_size, endpoint=False),
                    np.arange(len(audio_data)),
                    audio_data
                )
                
                # Convert to int16 with proper scaling
                audio_data = np.clip(resampled_data * 32767, -32768, 32767)
                audio_bytes = audio_data.astype(np.int16).tobytes()
                
                # Add to buffer
                self.audio_buffer.extend(audio_bytes)
                
                # Calculate buffer duration in ms
                buffer_duration_ms = (len(self.audio_buffer) / 2) * 1000 / self.output_sample_rate
                
                # Send audio data if we have enough
                if buffer_duration_ms >= self.min_audio_ms:
                    print(f"Buffer size: {len(self.audio_buffer)} bytes, {buffer_duration_ms:.1f}ms at {self.output_sample_rate}Hz")
                    
                    # Just send append - let server handle VAD
                    message = {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(bytes(self.audio_buffer)).decode('utf-8')
                    }
                    
                    future = asyncio.run_coroutine_threadsafe(
                        self.ws.send(json.dumps(message)),
                        self.loop
                    )
                    future.add_done_callback(lambda f: self._handle_send_result(f))
                    
                    # Clear buffer after sending
                    self.audio_buffer = bytearray()
                
            except Exception as e:
                print(f"Error in audio callback: {e}")
                import traceback
                traceback.print_exc()

    def _handle_send_result(self, future):
        """Handle the result of sending audio data"""
        try:
            future.result()  # Check for errors
        except Exception as e:
            print(f"Error sending audio data: {e}")

    def start_streaming(self, callback, microphone=None, system_message=None, temperature=None, voice=None):
        """Start streaming audio in a background task"""
        print(f"Starting streaming")
        # Store the configuration
        self.microphone = microphone
        self.system_message = system_message or "You are a helpful assistant."
        self.temperature = temperature or 0.7
        self.voice = voice or "alloy"
        
        self.start_loop()
        
        # Create and run the audio stream in the event loop
        future = asyncio.run_coroutine_threadsafe(
            self.start_audio_stream(callback),
            self.loop
        )
        
        # Add error handling for the future
        def handle_future(fut):
            try:
                fut.result()
            except Exception as e:
                print(f"Error in audio stream: {e}")
            
        future.add_done_callback(handle_future)

    def stop_streaming(self):
        """Stop audio streaming"""
        print("Stopping audio stream...")
        self.is_recording = False
        
        if self.loop and self.ws and self.ws.open:
            try:
                # Just close the connection - no need to send end event
                future = asyncio.run_coroutine_threadsafe(
                    self.ws.close(),
                    self.loop
                )
                future.result(timeout=1.0)  # Wait for close to complete
            except Exception as e:
                print(f"Error during cleanup: {e}")
        
        self.stop_loop()
        
        self.ws = None

    async def send_text_message(self, text):
        """Send a text message through the realtime connection"""
        try:
            if not self.ws or not self.ws.open:
                await self.ensure_connection(self.voice)
            
            # Initialize audio output stream
            self._initialize_output_stream()
            
            async with self.message_lock:  # Use lock for message handling
                # Create and send the text message
                text_message = {
                    'event_id': self.last_event_id,
                    "type": "conversation.item.create",
                    "item": {
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": text}]
                    }
                }
                await self.ws.send(json.dumps(text_message))
                print(f"Sent text message: {text}")
                
                # Process responses including audio
                while True:
                    response = await self.ws.recv()
                    if isinstance(response, str):
                        data = json.loads(response)
                        
                        if data.get("type") == "conversation.item.created":
                            # Send response configuration
                            response_config = {
                                'event_id': data.get('event_id'),
                                "type": "response.create",
                                "response": {
                                    "modalities": ["audio", "text"],
                                    "voice": "alloy",
                                    "instructions": self.system_message,
                                    "output_audio_format": "pcm16"
                                }
                            }
                            await self.ws.send(json.dumps(response_config))
                            print("Sent response configuration")
                        
                        elif data.get("type") == "response.audio.delta":
                            try:
                                audio_bytes = base64.b64decode(data["delta"])
                                print(f"Received audio delta: {len(audio_bytes)} bytes")
                                
                                audio_data = np.frombuffer(audio_bytes, dtype=np.int16)
                                if audio_data.ndim == 1:
                                    audio_data = audio_data.reshape(-1, 1)
                                
                                self.output_stream.write(audio_data)
                            except Exception as e:
                                print(f"Error playing audio delta: {e}")
                        
                        elif data.get("type") == "response.done":
                            break
                
        except Exception as e:
            print(f"Error sending text message: {e}")
            if self.output_stream:
                self.output_stream.stop()
                self.output_stream.close()
                self.output_stream = None

    def send_text(self, text, callback):
        """Send text message from main thread"""
        if self.loop:
            asyncio.run_coroutine_threadsafe(
                self.send_text_message(text),
                self.loop
            )

    def connect(self, model=None, system_message=None, temperature=None, voice=None):
        """Initialize WebSocket connection without starting audio stream"""
        # Store the configuration
        self.model = model or 'gpt-4o-realtime-preview'
        self.system_message = system_message or "You are a helpful assistant."
        self.temperature = temperature or 0.7
        self.voice = voice or "alloy"
        
        self.start_loop()
        
        # Ensure connection is established
        future = asyncio.run_coroutine_threadsafe(
            self.ensure_connection(self.voice),
            self.loop
        )
        try:
            future.result(timeout=10.0)  # Wait up to 10 seconds for connection
            print("WebSocket connection established")
            return True
        except Exception as e:
            print(f"Error connecting to WebSocket server: {e}")
            return False

    def disconnect(self):
        """Close the WebSocket connection and cleanup"""
        if self.output_stream:
            self.output_stream.stop()
            self.output_stream.close()
            self.output_stream = None
            
        if self.ws and self.ws.open:
            future = asyncio.run_coroutine_threadsafe(
                self.ws.close(),
                self.loop
            )
            try:
                future.result(timeout=5.0)
            except Exception as e:
                print(f"Error during cleanup: {e}")
        
        self.stop_loop()
        
        self.ws = None

# Factory function to get the appropriate provider
def get_ai_provider(provider_name: str) -> AIProvider:
    providers = {
        'openai': OpenAIProvider,
        'gemini': GeminiProvider,
        'grok': GrokProvider,
        'claude': ClaudeProvider,
        'perplexity': PerplexityProvider,
        'custom': CustomProvider,
    }
    
    provider_class = providers.get(provider_name)
    if not provider_class:
        raise ValueError(f"Unknown AI provider: {provider_name}")
    
    return provider_class() 