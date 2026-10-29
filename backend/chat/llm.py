"""The language model connection: send a conversation, get the reply.

This file only talks to the model. It knows nothing about users, roles,
documents or chat history, and nothing about what the prompt says
(that is in chat/grounding.py).

The model runs in a separate program, llama.cpp's llama-server.exe,
which offers the same kind of web API as many online AI services
("/v1/chat/completions"). Django calls it with Python's own urllib, so
no extra package is needed. It runs on this computer only: no question,
document or answer is ever sent to the internet.
"""

import json
from urllib.request import ProxyHandler, Request, build_opener

from django.conf import settings

# Sends web requests WITHOUT any proxy server. The model is on this
# computer, so a proxy configured for the internet must not be used.
_send = build_opener(ProxyHandler({})).open


class LLMUnavailable(Exception):
    """The model could not produce an answer: llama-server is not
    running, took too long, or sent back something unexpected."""


def generate(messages, json_schema=None):
    """Send a conversation to llama-server and return the model's reply.

    json_schema: if given, the reply is FORCED to be JSON of that shape.
    llama-server enforces it while the model writes ("constrained
    decoding"), so the reply can always be read by the program.

    Raises LLMUnavailable if no usable reply arrives.
    """
    payload = {
        "messages": messages,
        "temperature": settings.LLM_TEMPERATURE,
        "max_tokens": settings.LLM_MAX_ANSWER_TOKENS,
        # llama-server can reuse work from the previous request to save
        # time ("prompt cache"). That slightly changes the arithmetic, so
        # the same question could get a different answer depending on what
        # was asked before. Switched off: answers stay repeatable, at the
        # cost of a fraction of a second.
        "cache_prompt": False,
    }
    if json_schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "reply", "schema": json_schema},
        }

    headers = {"Content-Type": "application/json"}
    if settings.LLM_API_KEY:
        # llama-server refuses any request without this key.
        headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"

    request = Request(
        settings.LLM_SERVER_URL + "/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with _send(request, timeout=settings.LLM_TIMEOUT_SECONDS) as response:
            reply = json.load(response)
    except (OSError, ValueError) as error:
        # OSError: not running, refused, timed out, or an error status.
        # ValueError: the reply was not JSON.
        raise LLMUnavailable(f"The language model did not answer: {error}") from error

    try:
        text = reply["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise LLMUnavailable("The language model sent an unexpected reply.") from error

    if not text:
        raise LLMUnavailable("The language model sent an empty answer.")
    return text
