"""
Ollama backend implementation for local models.

Provides integration with Ollama via its HTTP API:
- /api/tags - List installed models
- /api/chat - Chat completion (streaming)
"""

import json
import os
import time
from typing import List, Optional, Callable, Any

import requests

from .types import LocalModelEntry, LocalModelHealth, LocalModelCapabilities
from .backend import LocalModelBackend


class OllamaBackend(LocalModelBackend):
    """
    Backend for Ollama local LLM server.
    
    Ollama provides a local HTTP API (default: http://localhost:11434) for
    running local LLMs. This backend implements model discovery, health
    checks, and streaming chat completion.
    """
    
    def __init__(self, base_url: str = "http://localhost:11434"):
        """
        Initialize the Ollama backend.
        
        Parameters
        ----------
        base_url : str
            The base URL of the Ollama server.
        """
        self.base_url = base_url.rstrip("/")
        self._debug = os.environ.get("DEBUG_CHATGTK", "").lower() in ("1", "true", "yes")
    
    def _log(self, msg: str) -> None:
        """Log debug message if debugging is enabled."""
        if self._debug:
            print(f"[OllamaBackend] {msg}")
    
    @property
    def backend_name(self) -> str:
        """Return the unique name for this backend."""
        return "ollama"
    
    def list_models(self) -> List[LocalModelEntry]:
        """
        Fetch installed models from Ollama via GET /api/tags.
        
        Returns
        -------
        List[LocalModelEntry]
            List of discovered Ollama models.
        """
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            self._log(f"Failed to list models: {e}")
            return []
        
        entries = []
        for model in data.get("models", []):
            model_name = model.get("name", "")
            if not model_name:
                continue
            
            # Create stable ID
            model_id = f"ollama:{model_name}"
            
            # Try to determine capabilities from model details
            details = model.get("details", {})
            family = details.get("family", "").lower()
            
            # Vision models typically have "vision" or "llava" in name/family
            has_vision = "vision" in model_name.lower() or "llava" in family
            
            entry = LocalModelEntry(
                id=model_id,
                type="chat",
                backend="ollama",
                display_name=model_name,
                enabled=True,
                config={
                    "base_url": self.base_url,
                    "model": model_name,
                },
                capabilities=LocalModelCapabilities(
                    tools=False,  # Ollama tool support varies by model
                    vision=has_vision,
                    audio_in=False,
                    audio_out=False,
                ),
            )
            entries.append(entry)
        
        self._log(f"Discovered {len(entries)} models")
        return entries
    
    def health_check(self, entry: Optional[LocalModelEntry] = None) -> LocalModelHealth:
        """
        Check Ollama server connectivity and optionally model availability.
        
        Parameters
        ----------
        entry : Optional[LocalModelEntry]
            If provided, also verify this model is available.
            
        Returns
        -------
        LocalModelHealth
            Health status with connectivity info.
        """
        start = time.time()
        
        try:
            # Basic connectivity check
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            resp.raise_for_status()
            latency_ms = (time.time() - start) * 1000
            
            if entry:
                # Check if specific model is installed
                data = resp.json()
                model_names = [m.get("name", "") for m in data.get("models", [])]
                model_name = entry.config.get("model", "")
                
                if model_name not in model_names:
                    return LocalModelHealth(
                        ok=False,
                        detail=f"Model '{model_name}' not installed",
                        latency_ms=latency_ms,
                    )
            
            return LocalModelHealth(
                ok=True,
                detail=f"Connected to Ollama at {self.base_url}",
                latency_ms=latency_ms,
            )
            
        except requests.ConnectionError:
            return LocalModelHealth(
                ok=False,
                detail=f"Cannot connect to Ollama at {self.base_url}",
                latency_ms=0,
            )
        except requests.Timeout:
            return LocalModelHealth(
                ok=False,
                detail=f"Connection to Ollama timed out",
                latency_ms=5000,
            )
        except requests.RequestException as e:
            return LocalModelHealth(
                ok=False,
                detail=f"Ollama error: {e}",
                latency_ms=0,
            )
    
    def _convert_messages(self, messages: List[dict]) -> List[dict]:
        """
        Convert ChatGTK message format to Ollama format.
        
        ChatGTK uses:
            {"role": "user"|"assistant"|"system", "content": "...", ...}
        
        Ollama uses:
            {"role": "user"|"assistant"|"system"|"tool", "content": "...", "images": [...], "tool_calls": [...]}
        
        Parameters
        ----------
        messages : List[dict]
            Messages in ChatGTK format.
            
        Returns
        -------
        List[dict]
            Messages in Ollama format.
        """
        ollama_messages = []
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            # Skip empty messages unless they are tool results or have tool calls
            if not content and not msg.get("images") and not msg.get("tool_calls") and role != "tool":
                continue
            
            ollama_msg = {
                "role": role,
                "content": content,
            }
            
            # Handle tool calls for assistant role
            if role == "assistant" and "tool_calls" in msg:
                ollama_msg["tool_calls"] = msg["tool_calls"]
            
            # Handle tool role specific fields
            # Ollama uses tool_name instead of tool_call_id per official API docs
            if role == "tool" and "tool_name" in msg:
                ollama_msg["tool_name"] = msg["tool_name"]
            
            # Handle images if present
            images = msg.get("images", [])
            if images:
                # Ollama expects base64-encoded images
                ollama_images = []
                for img in images:
                    if isinstance(img, dict) and "data" in img:
                        ollama_images.append(img["data"])
                    elif isinstance(img, str):
                        ollama_images.append(img)
                if ollama_images:
                    ollama_msg["images"] = ollama_images
            
            ollama_messages.append(ollama_msg)
        
        return ollama_messages
    
    def _convert_tools(self, tools: List[dict]) -> List[dict]:
        """
        Convert OpenAI-format tools to Ollama format.
        
        Ollama uses a similar format to OpenAI for tool definitions.
        """
        if not tools:
            return []
        
        ollama_tools = []
        for tool in tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                ollama_tools.append({
                    "type": "function",
                    "function": {
                        "name": func.get("name", ""),
                        "description": func.get("description", ""),
                        "parameters": func.get("parameters", {}),
                    }
                })
        return ollama_tools
    
    def chat(
        self,
        entry: LocalModelEntry,
        messages: List[dict],
        stream_cb: Optional[Callable[[str], None]] = None,
        tools: Optional[List[dict]] = None,
        tool_call_handler: Optional[Callable[[str, dict], str]] = None,
        **opts: Any,
    ) -> str:
        """
        Generate a chat completion using Ollama's /api/chat endpoint.
        
        Parameters
        ----------
        entry : LocalModelEntry
            The model configuration.
        messages : List[dict]
            Conversation messages.
        stream_cb : Optional[Callable[[str], None]]
            Callback for streaming chunks.
        tools : Optional[List[dict]]
            List of tool definitions in OpenAI format.
        tool_call_handler : Optional[Callable[[str, dict], str]]
            Callback to handle tool calls: (tool_name, args) -> result
        **opts : Any
            Additional options: temperature, max_tokens, keep_alive, etc.
            
        Returns
        -------
        str
            The complete response text.
        """
        model = entry.config.get("model", "")
        if not model:
            raise ValueError("Model name not configured")
        
        # Build request payload
        payload = {
            "model": model,
            "messages": self._convert_messages(messages),
            "stream": stream_cb is not None and not tools,  # Disable streaming when using tools
        }
        
        # Add tools if provided
        if tools:
            payload["tools"] = self._convert_tools(tools)
            # Ollama doesn't support streaming with tools, use sync mode
            payload["stream"] = False
        
        # Add optional parameters
        options = {}
        if "temperature" in opts and opts["temperature"] is not None:
            options["temperature"] = opts["temperature"]
        if "max_tokens" in opts and opts["max_tokens"]:
            options["num_predict"] = opts["max_tokens"]
        if options:
            payload["options"] = options
        
        # Keep-alive setting (how long to keep model loaded)
        if "keep_alive" in entry.config:
            payload["keep_alive"] = entry.config["keep_alive"]
        
        tool_count = len(tools) if tools else 0
        self._log(f"Chat request: model={model}, messages={len(messages)}, tools={tool_count}, stream={payload['stream']}")
        
        try:
            if tools and tool_call_handler:
                return self._chat_with_tools(payload, messages, tools, tool_call_handler, entry, opts)
            elif stream_cb and not tools:
                return self._stream_chat(payload, stream_cb)
            else:
                return self._sync_chat(payload)
        except requests.RequestException as e:
            self._log(f"Chat error: {e}")
            raise RuntimeError(f"Ollama chat failed: {e}") from e
    
    def _chat_with_tools(
        self,
        payload: dict,
        original_messages: List[dict],
        tools: List[dict],
        tool_call_handler: Callable[[str, dict], str],
        entry: LocalModelEntry,
        opts: dict,
        max_iterations: int = 10,
    ) -> str:
        """Handle chat with tool calls in a loop until completion."""
        messages = list(original_messages)
        payload["stream"] = False
        
        for iteration in range(max_iterations):
            payload["messages"] = self._convert_messages(messages)
            
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            
            message = data.get("message", {})
            content = message.get("content", "")
            tool_calls = message.get("tool_calls", [])
            
            if not tool_calls:
                # No tool calls, return the content
                return content
            
            self._log(f"Tool calls in iteration {iteration + 1}: {[tc.get('function', {}).get('name') for tc in tool_calls]}")
            
            # Add assistant message with tool calls to history
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls,
            })
            
            # Process each tool call
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                
                # Ollama often returns arguments as a dict already
                args = func.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                
                # Call the handler
                result = tool_call_handler(tool_name, args)
                
                # Add tool result to messages with tool_name per Ollama API docs
                messages.append({
                    "role": "tool",
                    "content": result,
                    "tool_name": tool_name,
                })
        
        # Max iterations reached
        self._log(f"Max tool iterations ({max_iterations}) reached")
        return content
    
    def _sync_chat(self, payload: dict) -> str:
        """Non-streaming chat request."""
        payload["stream"] = False
        resp = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("message", {}).get("content", "")
    
    def _stream_chat(self, payload: dict, stream_cb: Callable[[str], None]) -> str:
        """Streaming chat request."""
        payload["stream"] = True
        full_response = []
        
        with requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            stream=True,
            timeout=120,
        ) as resp:
            resp.raise_for_status()
            
            for line in resp.iter_lines():
                if not line:
                    continue
                    
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                # Extract content from the message
                message = chunk.get("message", {})
                content = message.get("content", "")
                
                if content:
                    full_response.append(content)
                    stream_cb(content)
                
                # Check if done
                if chunk.get("done", False):
                    break
        
        return "".join(full_response)
