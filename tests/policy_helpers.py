"""Scripted provider responses for the turn-policy tests, one builder per provider SDK.

``make_backend(provider, mocker, rounds)`` returns ``(backend, requests)``: the backend is wired
to a mocked SDK that answers each request from ``rounds`` in order, and ``requests`` records, for
every request actually sent, what the policy asked of the provider.

A round is a dict: ``text`` (default "ok"), ``calls`` (a list of ``(name, args)``; ``args`` may be
a raw string to model unparseable JSON), ``cut_off`` (the response hit its token limit) and
``raise_after_text`` (an exception raised once the text has streamed).
"""

import json
from dataclasses import dataclass
from unittest.mock import MagicMock

from tests.test_backends import (
    _claude_stream,
    _claude_tool_block,
    _oai_chunk,
    _oai_stream,
    _oai_tc_delta,
    _ollama_chunk,
)

PROVIDERS = ["claude", "gemini", "openai", "ollama"]


@dataclass
class Request:
    tools_off: bool
    max_tokens: int
    timeout_s: float | None = None


def _text_pieces(text):
    # Two events per response, so a deadline can pass between them.
    half = max(1, len(text) // 2)
    return [text[:half], text[half:]] if text[half:] else [text]


def _claude(mocker, rounds, requests):
    client = mocker.patch("strides_ai.backends.claude.anthropic.Anthropic").return_value

    def stream(**kwargs):
        spec = rounds[len(requests)]
        timeout = kwargs.get("timeout")
        requests.append(
            Request(
                kwargs.get("tool_choice") == {"type": "none"},
                kwargs["max_tokens"],
                getattr(timeout, "read", None),
            )
        )
        calls = spec.get("calls", [])
        if spec.get("cut_off"):
            stop = "max_tokens"
        else:
            stop = "tool_use" if calls else "end_turn"
        blocks = [_claude_tool_block(n, a, f"t{i}") for i, (n, a) in enumerate(calls)]
        s = _claude_stream(_text_pieces(spec.get("text", "ok")), stop, blocks)
        if spec.get("raise_after_text"):
            exc = spec["raise_after_text"]
            events = list(s.__iter__.side_effect())

            def broken():
                yield from events
                raise exc

            s.__iter__.side_effect = broken
        return s

    client.messages.stream.side_effect = stream
    from strides_ai.backends.claude import ClaudeBackend

    return ClaudeBackend("fake", [])


def _openai(mocker, rounds, requests):
    client = mocker.patch("strides_ai.backends.openai._openai.OpenAI").return_value

    def create(**kwargs):
        spec = rounds[len(requests)]
        timeout = kwargs.get("timeout")
        requests.append(
            Request(
                kwargs.get("tool_choice") == "none",
                kwargs["max_completion_tokens"],
                getattr(timeout, "read", None),
            )
        )
        chunks = [_oai_chunk(piece) for piece in _text_pieces(spec.get("text", "ok"))]
        calls = spec.get("calls", [])
        if calls:
            deltas = [
                _oai_tc_delta(i, f"t{i}", name, args if isinstance(args, str) else json.dumps(args))
                for i, (name, args) in enumerate(calls)
            ]
            chunks.append(_oai_chunk(tool_calls=deltas))
        last = _oai_chunk()
        last.choices[0].finish_reason = (
            "length" if spec.get("cut_off") else ("tool_calls" if calls else "stop")
        )
        chunks.append(last)
        stream = _oai_stream(chunks)
        if spec.get("raise_after_text"):
            exc = spec["raise_after_text"]

            def broken():
                yield from chunks[:1]
                raise exc

            stream.__iter__ = MagicMock(side_effect=broken)
        return stream

    client.chat.completions.create.side_effect = create
    from strides_ai.backends.openai import OpenAIBackend

    return OpenAIBackend("fake", [])


def _gemini(mocker, rounds, requests):
    from google.genai import types

    client = mocker.patch("strides_ai.backends.gemini.genai.Client").return_value

    def record(config):
        mode = getattr(getattr(config.tool_config, "function_calling_config", None), "mode", None)
        timeout = config.http_options.timeout if config.http_options else None
        requests.append(
            Request(
                mode == types.FunctionCallingConfigMode.NONE,
                config.max_output_tokens,
                timeout / 1000 if timeout else None,
            )
        )

    def candidate(spec, parts):
        cand = MagicMock()
        cand.content.parts = parts
        cand.finish_reason = types.FinishReason.MAX_TOKENS if spec.get("cut_off") else None
        return cand

    def call_parts(spec):
        return [
            types.Part(function_call=types.FunctionCall(name=n, args=a))
            for n, a in spec.get("calls", [])
        ]

    def stream(**kwargs):
        spec = rounds[len(requests)]
        record(kwargs["config"])

        def chunks():
            for piece in _text_pieces(spec.get("text", "ok")):
                chunk = MagicMock()
                chunk.text = piece
                chunk.candidates = []
                yield chunk
            if spec.get("raise_after_text"):
                raise spec["raise_after_text"]
            last = MagicMock()
            last.text = None
            last.candidates = [candidate(spec, call_parts(spec))]
            yield last

        return chunks()

    def followup(**kwargs):
        spec = rounds[len(requests)]
        record(kwargs["config"])
        if spec.get("raise_after_text"):
            raise spec["raise_after_text"]
        text = MagicMock()
        text.text = spec.get("text", "ok")
        resp = MagicMock()
        resp.candidates = [candidate(spec, [text, *call_parts(spec)])]
        return resp

    client.models.generate_content_stream.side_effect = stream
    client.models.generate_content.side_effect = followup
    from strides_ai.backends.gemini import GeminiBackend

    return GeminiBackend("fake", [])


json_dumps = json.dumps


def _ollama(mocker, rounds, requests):
    cls = mocker.patch("strides_ai.backends.ollama.httpx.Client")

    def make_client(*args, **kwargs):
        client = MagicMock()
        client.__enter__.return_value = client

        def stream(method, url, json=None):
            spec = rounds[len(requests)]
            timeout = kwargs.get("timeout")
            requests.append(
                Request(
                    "tools" not in json,
                    json["options"]["num_predict"],
                    getattr(timeout, "read", None),
                )
            )
            pieces = _text_pieces(spec.get("text", "ok"))
            lines = [_ollama_chunk(piece) for piece in pieces]
            calls = [{"function": {"name": n, "arguments": a}} for n, a in spec.get("calls", [])]
            final = {"message": {"content": ""}, "done": True}
            if calls:
                final["message"]["tool_calls"] = calls
            if spec.get("cut_off"):
                final["done_reason"] = "length"
            resp = MagicMock()
            resp.status_code = 200

            def iterate():
                yield from lines
                if spec.get("raise_after_text"):
                    raise spec["raise_after_text"]
                yield json_dumps(final)

            resp.iter_lines.side_effect = iterate
            manager = MagicMock()
            manager.__enter__.return_value = resp
            manager.__exit__.return_value = False
            return manager

        client.stream.side_effect = stream
        return client

    cls.side_effect = make_client
    from strides_ai.backends.ollama import OllamaBackend

    return OllamaBackend("fake", [])


def make_backend(provider, mocker, rounds):
    requests: list[Request] = []
    build = {"claude": _claude, "gemini": _gemini, "openai": _openai, "ollama": _ollama}[provider]
    return build(mocker, rounds, requests), requests
