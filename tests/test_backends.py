"""Unit tests for strides_ai LLM backends.

All external SDK calls are mocked — no network or API keys required.
"""

import json
from unittest.mock import MagicMock

import pytest


# ── Shared helpers ─────────────────────────────────────────────────────────────


def _collect():
    """Return (on_token callback, accumulated tokens list)."""
    tokens = []
    return lambda t: tokens.append(t), tokens


# ══════════════════════════════════════════════════════════════════════════════
# ClaudeBackend
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_anthropic(mocker):
    return mocker.patch("strides_ai.backends.claude.anthropic.Anthropic")


def _claude_stream(tokens, stop_reason="end_turn", content_blocks=None):
    """Mock Anthropic stream context manager."""
    s = MagicMock()
    s.__enter__.return_value = s
    s.__exit__.return_value = False
    s.text_stream = iter(tokens)
    final = MagicMock()
    final.stop_reason = stop_reason
    final.content = content_blocks or []
    s.get_final_message.return_value = final
    return s


def _claude_tool_block(name, input_dict, block_id="tu_1"):
    b = MagicMock()
    b.type = "tool_use"
    b.name = name
    b.input = input_dict
    b.id = block_id
    return b


def test_claude_label(mock_anthropic):
    from strides_ai.backends.claude import ClaudeBackend

    assert ClaudeBackend("key", [], model="claude-test").label == "claude-test"


def test_claude_supports_attachments(mock_anthropic):
    from strides_ai.backends.claude import ClaudeBackend

    assert ClaudeBackend("key", []).supports_attachments is True


def test_claude_stream_turn_text(mock_anthropic):
    mock_anthropic.return_value.messages.stream.return_value = _claude_stream(["Hello", " world"])

    from strides_ai.backends.claude import ClaudeBackend

    on_token, tokens = _collect()
    text, memories = ClaudeBackend("key", []).stream_turn("sys", "hi", on_token)

    assert text == "Hello world"
    assert tokens == ["Hello", " world"]
    assert memories == []


def test_claude_stream_turn_appends_history(mock_anthropic):
    mock_anthropic.return_value.messages.stream.return_value = _claude_stream(["reply"])

    from strides_ai.backends.claude import ClaudeBackend

    b = ClaudeBackend("key", [])
    b.stream_turn("sys", "hello", lambda _: None)

    assert b._history[0] == {"role": "user", "content": "hello"}
    assert b._history[1]["role"] == "assistant"


def test_claude_stream_turn_initial_history_preserved(mock_anthropic):
    mock_anthropic.return_value.messages.stream.return_value = _claude_stream(["ok"])

    from strides_ai.backends.claude import ClaudeBackend

    prior = [
        {"role": "user", "content": "prev q"},
        {"role": "assistant", "content": "prev a"},
    ]
    b = ClaudeBackend("key", prior)
    assert b._history[0]["content"] == "prev q"
    assert b._history[1]["content"] == "prev a"


def test_claude_stream_turn_attachment_prepended(mock_anthropic):
    mock_anthropic.return_value.messages.stream.return_value = _claude_stream(["ok"])

    from strides_ai.backends.claude import ClaudeBackend

    b = ClaudeBackend("key", [])
    img = {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "abc"}}
    b.stream_turn("sys", "describe", lambda _: None, attachments=[img])

    user_content = b._history[0]["content"]
    assert isinstance(user_content, list)
    assert user_content[0] == img
    assert user_content[-1]["text"] == "describe"


def test_claude_stream_turn_saves_memory(mock_anthropic, mocker):
    mock_db = mocker.patch("strides_ai.backends.claude.db.save_memory", return_value="ok")
    tool_block = _claude_tool_block("save_memory", {"category": "goal", "content": "BQ 2025"})
    mock_anthropic.return_value.messages.stream.side_effect = [
        _claude_stream([], stop_reason="tool_use", content_blocks=[tool_block]),
        _claude_stream(["Noted."]),
    ]

    from strides_ai.backends.claude import ClaudeBackend

    text, memories = ClaudeBackend("key", []).stream_turn("sys", "save it", lambda _: None)

    mock_db.assert_called_once_with("goal", "BQ 2025")
    assert memories == [("goal", "BQ 2025")]
    assert text == "Noted."


def test_claude_stream_turn_multiple_tool_calls(mock_anthropic, mocker):
    mock_db = mocker.patch("strides_ai.backends.claude.db.save_memory", return_value="ok")
    blocks = [
        _claude_tool_block(
            "save_memory", {"category": "goal", "content": "sub-3 marathon"}, "tu_1"
        ),
        _claude_tool_block(
            "save_memory", {"category": "injury", "content": "left IT band"}, "tu_2"
        ),
    ]
    mock_anthropic.return_value.messages.stream.side_effect = [
        _claude_stream([], stop_reason="tool_use", content_blocks=blocks),
        _claude_stream(["Done."]),
    ]

    from strides_ai.backends.claude import ClaudeBackend

    _, memories = ClaudeBackend("key", []).stream_turn("sys", "save both", lambda _: None)

    assert mock_db.call_count == 2
    assert len(memories) == 2
    assert ("goal", "sub-3 marathon") in memories
    assert ("injury", "left IT band") in memories


# ══════════════════════════════════════════════════════════════════════════════
# GeminiBackend
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_genai(mocker):
    return mocker.patch("strides_ai.backends.gemini.genai.Client")


def _gemini_text_chunk(text):
    chunk = MagicMock()
    chunk.text = text
    chunk.candidates = []
    return chunk


def _gemini_fc_chunk(fn_name, args_dict):
    """Chunk carrying a function_call part (no text content).

    Uses real google.genai types so Pydantic validation passes when the backend
    re-appends these parts to a types.Content history message.
    """
    from google.genai import types as _gtypes

    part = _gtypes.Part(function_call=_gtypes.FunctionCall(name=fn_name, args=args_dict))
    candidate = MagicMock()
    candidate.content.parts = [part]
    chunk = MagicMock()
    chunk.text = None
    chunk.candidates = [candidate]
    return chunk


def _gemini_text_response(text):
    """Non-streaming generate_content response with text only."""
    part = MagicMock()
    part.text = text
    fc = MagicMock()
    fc.name = None
    part.function_call = fc
    candidate = MagicMock()
    candidate.content.parts = [part]
    resp = MagicMock()
    resp.candidates = [candidate]
    return resp


def test_gemini_label(mock_genai):
    from strides_ai.backends.gemini import GeminiBackend

    assert GeminiBackend("key", [], model="gemini-test").label == "gemini:gemini-test"


def test_gemini_supports_attachments(mock_genai):
    from strides_ai.backends.gemini import GeminiBackend

    assert GeminiBackend("key", []).supports_attachments is False


def test_gemini_stream_turn_rejects_attachments(mock_genai):
    from strides_ai.backends.gemini import GeminiBackend

    with pytest.raises(NotImplementedError):
        GeminiBackend("key", []).stream_turn(
            "sys", "hi", lambda _: None, attachments=[{"type": "image"}]
        )


def test_gemini_stream_turn_text(mock_genai):
    mock_genai.return_value.models.generate_content_stream.return_value = iter(
        [_gemini_text_chunk("Hello"), _gemini_text_chunk(" world")]
    )

    from strides_ai.backends.gemini import GeminiBackend

    on_token, tokens = _collect()
    text, memories = GeminiBackend("key", []).stream_turn("sys", "hi", on_token)

    assert text == "Hello world"
    assert tokens == ["Hello", " world"]
    assert memories == []


def test_gemini_stream_turn_appends_history(mock_genai):
    mock_genai.return_value.models.generate_content_stream.return_value = iter(
        [_gemini_text_chunk("reply")]
    )

    from strides_ai.backends.gemini import GeminiBackend

    b = GeminiBackend("key", [])
    b.stream_turn("sys", "hello", lambda _: None)

    # history[0] is the user message (a Content object)
    assert b._history[0].role == "user"
    # history[1] is the assistant response
    assert b._history[1].role == "model"


def test_gemini_stream_turn_saves_memory(mock_genai, mocker):
    mock_db = mocker.patch("strides_ai.backends.gemini.db.save_memory", return_value="ok")
    mock_client = mock_genai.return_value
    mock_client.models.generate_content_stream.return_value = iter(
        [_gemini_fc_chunk("save_memory", {"category": "injury", "content": "knee pain"})]
    )
    mock_client.models.generate_content.return_value = _gemini_text_response("Noted your injury.")

    from strides_ai.backends.gemini import GeminiBackend

    on_token, tokens = _collect()
    text, memories = GeminiBackend("key", []).stream_turn("sys", "save injury", on_token)

    mock_db.assert_called_once_with("injury", "knee pain")
    assert memories == [("injury", "knee pain")]
    assert text == "Noted your injury."
    assert "Noted your injury." in tokens


# ══════════════════════════════════════════════════════════════════════════════
# OpenAIBackend
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def mock_openai(mocker):
    return mocker.patch("strides_ai.backends.openai._openai.OpenAI")


def _oai_chunk(content=None, tool_calls=None):
    delta = MagicMock()
    delta.content = content
    delta.tool_calls = tool_calls or []
    choice = MagicMock()
    choice.delta = delta
    chunk = MagicMock()
    chunk.choices = [choice]
    return chunk


def _oai_tc_delta(index, call_id=None, fn_name=None, fn_args=None):
    """Single tool-call delta (one item in delta.tool_calls list)."""
    tc = MagicMock()
    tc.index = index
    tc.id = call_id
    fn = MagicMock()
    fn.name = fn_name
    fn.arguments = fn_args
    tc.function = fn
    return tc


def _oai_stream(chunks):
    """Context-manager wrapper around a list of chunks."""
    s = MagicMock()
    s.__enter__.return_value = s
    s.__exit__.return_value = False
    s.__iter__ = MagicMock(return_value=iter(chunks))
    return s


def test_openai_label(mock_openai):
    from strides_ai.backends.openai import OpenAIBackend

    assert OpenAIBackend("key", [], model="gpt-4o").label == "openai:gpt-4o"


def test_openai_supports_attachments(mock_openai):
    from strides_ai.backends.openai import OpenAIBackend

    assert OpenAIBackend("key", []).supports_attachments is False


def test_openai_stream_turn_rejects_attachments(mock_openai):
    from strides_ai.backends.openai import OpenAIBackend

    with pytest.raises(NotImplementedError):
        OpenAIBackend("key", []).stream_turn(
            "sys", "hi", lambda _: None, attachments=[{"type": "image"}]
        )


def test_openai_stream_turn_text(mock_openai):
    mock_openai.return_value.chat.completions.create.return_value = _oai_stream(
        [_oai_chunk("Hello"), _oai_chunk(" world")]
    )

    from strides_ai.backends.openai import OpenAIBackend

    on_token, tokens = _collect()
    text, memories = OpenAIBackend("key", []).stream_turn("sys", "hi", on_token)

    assert text == "Hello world"
    assert tokens == ["Hello", " world"]
    assert memories == []


def test_openai_stream_turn_appends_history(mock_openai):
    mock_openai.return_value.chat.completions.create.return_value = _oai_stream([_oai_chunk("ok")])

    from strides_ai.backends.openai import OpenAIBackend

    b = OpenAIBackend("key", [])
    b.stream_turn("sys", "hello", lambda _: None)

    assert b._history[0] == {"role": "user", "content": "hello"}
    assert b._history[1] == {"role": "assistant", "content": "ok"}


def test_openai_stream_turn_initial_history_preserved(mock_openai):
    mock_openai.return_value.chat.completions.create.return_value = _oai_stream([_oai_chunk("ok")])

    from strides_ai.backends.openai import OpenAIBackend

    prior = [
        {"role": "user", "content": "prev q"},
        {"role": "assistant", "content": "prev a"},
    ]
    b = OpenAIBackend("key", prior)
    assert b._history[0]["content"] == "prev q"
    assert b._history[1]["content"] == "prev a"


def test_openai_stream_turn_saves_memory(mock_openai, mocker):
    mock_db = mocker.patch("strides_ai.backends.openai.db.save_memory", return_value="saved")
    mock_client = mock_openai.return_value
    tc = _oai_tc_delta(
        0, "call_abc", "save_memory", json.dumps({"category": "goal", "content": "BQ 2025"})
    )
    mock_client.chat.completions.create.side_effect = [
        _oai_stream([_oai_chunk(tool_calls=[tc])]),
        _oai_stream([_oai_chunk("Memory saved.")]),
    ]

    from strides_ai.backends.openai import OpenAIBackend

    on_token, tokens = _collect()
    text, memories = OpenAIBackend("key", []).stream_turn("sys", "save goal", on_token)

    mock_db.assert_called_once_with("goal", "BQ 2025")
    assert memories == [("goal", "BQ 2025")]
    assert text == "Memory saved."
    assert "Memory saved." in tokens


def test_openai_tool_result_history_format(mock_openai, mocker):
    """After a tool call the history must include a 'tool' role message."""
    mocker.patch("strides_ai.backends.openai.db.save_memory", return_value="saved")
    mock_client = mock_openai.return_value
    tc = _oai_tc_delta(
        0,
        "call_xyz",
        "save_memory",
        json.dumps({"category": "preference", "content": "no track work"}),
    )
    mock_client.chat.completions.create.side_effect = [
        _oai_stream([_oai_chunk(tool_calls=[tc])]),
        _oai_stream([_oai_chunk("Got it.")]),
    ]

    from strides_ai.backends.openai import OpenAIBackend

    b = OpenAIBackend("key", [])
    b.stream_turn("sys", "remember pref", lambda _: None)

    # history: [user, assistant+tool_calls, tool_result, assistant_final]
    tool_msg = b._history[2]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "call_xyz"
    assert tool_msg["content"] == "saved"


def test_openai_assembles_split_tool_arguments(mock_openai, mocker):
    """Arguments arriving across multiple stream chunks are concatenated correctly."""
    mock_db = mocker.patch("strides_ai.backends.openai.db.save_memory", return_value="ok")
    mock_client = mock_openai.return_value
    part1 = _oai_tc_delta(0, "call_1", "save_memory", '{"category": "race"')
    part2 = _oai_tc_delta(0, None, None, ', "content": "Boston 2026"}')
    mock_client.chat.completions.create.side_effect = [
        _oai_stream([_oai_chunk(tool_calls=[part1]), _oai_chunk(tool_calls=[part2])]),
        _oai_stream([_oai_chunk("Saved.")]),
    ]

    from strides_ai.backends.openai import OpenAIBackend

    OpenAIBackend("key", []).stream_turn("sys", "remember race", lambda _: None)

    mock_db.assert_called_once_with("race", "Boston 2026")


# ══════════════════════════════════════════════════════════════════════════════
# OllamaBackend
# ══════════════════════════════════════════════════════════════════════════════


def _ollama_chunk(content="", done=False, tool_calls=None):
    msg: dict = {"content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return json.dumps({"message": msg, "done": done})


def _ollama_http_client(mocker, *stream_responses):
    """
    Patch httpx.Client so successive `with httpx.Client(...) as client:` blocks
    yield clients whose `client.stream(...)` returns the given responses in order.

    Each element of stream_responses is a list of NDJSON lines (strings).
    """
    mock_cls = mocker.patch("strides_ai.backends.ollama.httpx.Client")
    clients = []
    for lines in stream_responses:
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        resp.iter_lines.return_value = iter(lines)

        stream_ctx = MagicMock()
        stream_ctx.__enter__.return_value = resp
        stream_ctx.__exit__.return_value = False

        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        client.stream.return_value = stream_ctx
        clients.append(client)

    mock_cls.side_effect = clients
    return mock_cls


def test_ollama_label(mocker):
    _ollama_http_client(mocker)
    from strides_ai.backends.ollama import OllamaBackend

    assert OllamaBackend("llama3.1", []).label == "ollama:llama3.1"


def test_ollama_supports_attachments(mocker):
    _ollama_http_client(mocker)
    from strides_ai.backends.ollama import OllamaBackend

    assert OllamaBackend("llama3.1", []).supports_attachments is False


def test_ollama_stream_turn_rejects_attachments(mocker):
    _ollama_http_client(mocker)
    from strides_ai.backends.ollama import OllamaBackend

    with pytest.raises(NotImplementedError):
        OllamaBackend("llama3.1", []).stream_turn(
            "sys", "hi", lambda _: None, attachments=[{"type": "image"}]
        )


def test_ollama_stream_turn_text(mocker):
    _ollama_http_client(
        mocker,
        [_ollama_chunk("Hello"), _ollama_chunk(" world", done=True)],
    )

    from strides_ai.backends.ollama import OllamaBackend

    on_token, tokens = _collect()
    text, memories = OllamaBackend("llama3.1", []).stream_turn("sys", "hi", on_token)

    assert text == "Hello world"
    assert tokens == ["Hello", " world"]
    assert memories == []


def test_ollama_stream_turn_appends_history(mocker):
    _ollama_http_client(mocker, [_ollama_chunk("reply", done=True)])

    from strides_ai.backends.ollama import OllamaBackend

    b = OllamaBackend("llama3.1", [])
    b.stream_turn("sys", "hello", lambda _: None)

    assert b._history[0] == {"role": "user", "content": "hello"}
    assert b._history[1]["role"] == "assistant"


def test_ollama_stream_turn_saves_memory(mocker):
    mock_db = mocker.patch("strides_ai.backends.ollama.db.save_memory", return_value="ok")
    tool_call = {
        "function": {
            "name": "save_memory",
            "arguments": {"category": "training", "content": "80 km/week base"},
        }
    }
    _ollama_http_client(
        mocker,
        [_ollama_chunk("", done=True, tool_calls=[tool_call])],
        [_ollama_chunk("Saved.", done=True)],
    )

    from strides_ai.backends.ollama import OllamaBackend

    on_token, tokens = _collect()
    text, memories = OllamaBackend("llama3.1", []).stream_turn("sys", "save training", on_token)

    mock_db.assert_called_once_with("training", "80 km/week base")
    assert memories == [("training", "80 km/week base")]
    assert text == "Saved."
    assert "Saved." in tokens


def test_ollama_retries_without_tools_on_400(mocker):
    """When model returns 400 for a tools request, retry without tools."""
    mock_cls = mocker.patch("strides_ai.backends.ollama.httpx.Client")

    # First httpx.Client call: stream returns 400
    bad_resp = MagicMock()
    bad_resp.status_code = 400
    bad_stream_ctx = MagicMock()
    bad_stream_ctx.__enter__.return_value = bad_resp
    bad_stream_ctx.__exit__.return_value = False
    client1 = MagicMock()
    client1.__enter__.return_value = client1
    client1.__exit__.return_value = False
    client1.stream.return_value = bad_stream_ctx

    # Second httpx.Client call (retry without tools): stream returns text
    good_resp = MagicMock()
    good_resp.status_code = 200
    good_resp.raise_for_status = MagicMock()
    good_resp.iter_lines.return_value = iter([_ollama_chunk("ok", done=True)])
    good_stream_ctx = MagicMock()
    good_stream_ctx.__enter__.return_value = good_resp
    good_stream_ctx.__exit__.return_value = False
    client2 = MagicMock()
    client2.__enter__.return_value = client2
    client2.__exit__.return_value = False
    client2.stream.return_value = good_stream_ctx

    mock_cls.side_effect = [client1, client2]

    from strides_ai.backends.ollama import OllamaBackend

    b = OllamaBackend("llama3.1", [])
    text, _ = b.stream_turn("sys", "hi", lambda _: None)

    assert text == "ok"
    assert b._supports_tools is False
    # Retry request must NOT include 'tools'
    retry_body = client2.stream.call_args[1]["json"]
    assert "tools" not in retry_body


def test_ollama_stream_turn_initial_history_preserved(mocker):
    _ollama_http_client(mocker, [_ollama_chunk("ok", done=True)])

    from strides_ai.backends.ollama import OllamaBackend

    prior = [
        {"role": "user", "content": "prev q"},
        {"role": "assistant", "content": "prev a"},
    ]
    b = OllamaBackend("llama3.1", prior)
    assert b._history[0]["content"] == "prev q"
    assert b._history[1]["content"] == "prev a"
