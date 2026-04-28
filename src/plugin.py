"""Plugin system with request/response hooks and priority ordering."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from .types import ChatCompletionRequest, ChatCompletionResponse

logger = logging.getLogger(__name__)

# Hook type aliases
RequestHook = Callable[[ChatCompletionRequest], ChatCompletionRequest]
ResponseHook = Callable[[ChatCompletionRequest, ChatCompletionResponse], ChatCompletionResponse]
ErrorHook = Callable[[ChatCompletionRequest, Exception], None]


@dataclass
class Plugin:
    name: str
    description: str = ""
    priority: int = 0  # higher = runs first
    on_request: RequestHook | None = None
    on_response: ResponseHook | None = None
    on_error: ErrorHook | None = None


class PluginManager:
    """Register and execute plugins in priority order (descending)."""

    def __init__(self) -> None:
        self._plugins: list[Plugin] = []

    def register(self, plugin: Plugin) -> None:
        self._plugins.append(plugin)
        # Re-sort: highest priority first
        self._plugins.sort(key=lambda p: p.priority, reverse=True)

    def process_request(self, request: ChatCompletionRequest) -> ChatCompletionRequest:
        for plugin in self._plugins:
            if plugin.on_request is not None:
                try:
                    request = plugin.on_request(request)
                except Exception:
                    logger.exception("plugin %s on_request failed", plugin.name)
        return request

    def process_response(
        self,
        request: ChatCompletionRequest,
        response: ChatCompletionResponse,
    ) -> ChatCompletionResponse:
        for plugin in self._plugins:
            if plugin.on_response is not None:
                try:
                    response = plugin.on_response(request, response)
                except Exception:
                    logger.exception("plugin %s on_response failed", plugin.name)
        return response

    def process_error(self, request: ChatCompletionRequest, error: Exception) -> None:
        for plugin in self._plugins:
            if plugin.on_error is not None:
                try:
                    plugin.on_error(request, error)
                except Exception:
                    logger.exception("plugin %s on_error failed", plugin.name)

    def list(self) -> list[Plugin]:
        return list(self._plugins)
