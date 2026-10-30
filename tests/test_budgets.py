"""Deterministic contract tests shared across the four real provider adapters."""

import json
from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from strides_ai.backends.base import BaseBackend
from strides_ai.budget import BudgetExceeded, ContextPrompt, Limits, estimate
from strides_ai.coach import build_initial_history, older_activity_summary
from tests.test_backends import (
    _claude_stream,
    _claude_tool_block,
    _gemini_fc_chunk,
    _oai_stream,
    _oai_chunk,
    _oai_tc_delta,
    _ollama_chunk,
)


@pytest.fixture(params=["claude", "gemini", "openai", "ollama"])
def adapter(request, mocker):
    provider = request.param
    args = {"category": "goal", "content": "race"}
    counter = MagicMock()

    def make(batch=1):
        if provider == "claude":
            client = mocker.patch("strides_ai.backends.claude.anthropic.Anthropic").return_value

            def response(**kwargs):
                counter()
                return _claude_stream(
                    ["partial"],
                    "tool_use",
                    [_claude_tool_block("save_memory", args, f"t{i}") for i in range(batch)],
                )

            client.messages.stream.side_effect = response
            from strides_ai.backends.claude import ClaudeBackend

            backend = ClaudeBackend("fake", [])
        elif provider == "gemini":
            client = mocker.patch("strides_ai.backends.gemini.genai.Client").return_value

            def stream(**kwargs):
                counter()
                return iter([_gemini_fc_chunk("save_memory", args) for _ in range(batch)])

            def followup(**kwargs):
                counter()
                result = MagicMock()
                result.candidates = [_gemini_fc_chunk("save_memory", args).candidates[0]]
                result.candidates[0].content.parts *= batch
                return result

            client.models.generate_content_stream.side_effect = stream
            client.models.generate_content.side_effect = followup
            from strides_ai.backends.gemini import GeminiBackend

            backend = GeminiBackend("fake", [])
        elif provider == "openai":
            client = mocker.patch("strides_ai.backends.openai._openai.OpenAI").return_value

            def response(**kwargs):
                counter()
                return _oai_stream(
                    [
                        _oai_chunk("partial"),
                        _oai_chunk(
                            tool_calls=[
                                _oai_tc_delta(i, f"t{i}", "save_memory", json.dumps(args))
                                for i in range(batch)
                            ]
                        ),
                    ]
                )

            client.chat.completions.create.side_effect = response
            from strides_ai.backends.openai import OpenAIBackend

            backend = OpenAIBackend("fake", [])
        else:
            client = mocker.patch("strides_ai.backends.ollama.httpx.Client").return_value
            client.__enter__.return_value = client

            def response(*a, **kw):
                counter()
                resp = MagicMock()
                resp.status_code = 200
                resp.iter_lines.return_value = iter(
                    [
                        _ollama_chunk(
                            "partial",
                            True,
                            [
                                {"function": {"name": "save_memory", "arguments": args}}
                                for _ in range(batch)
                            ],
                        )
                    ]
                )
                manager = MagicMock()
                manager.__enter__.return_value = resp
                manager.__exit__.return_value = False
                return manager

            client.stream.side_effect = response
            from strides_ai.backends.ollama import OllamaBackend

            backend = OllamaBackend("fake", [])
        return backend, counter

    return make


@pytest.mark.parametrize(
    "batch,rounds,tools,expected_requests,expected_writes",
    [
        (1, 2, 16, 2, 2),
        (4, 6, 2, 1, 2),
    ],
)
def test_equivalent_limits(
    adapter, monkeypatch, mocker, batch, rounds, tools, expected_requests, expected_writes
):
    monkeypatch.setattr(
        BaseBackend, "limits", property(lambda _: Limits(rounds=rounds, tools=tools))
    )
    write = mocker.patch("strides_ai.backends.base.db.save_memory", return_value="saved")
    backend, requests = adapter(batch)
    chunks = []
    text, memories, changes = backend.stream_turn("mandatory", "hello", chunks.append)
    assert requests.call_count == expected_requests
    assert write.call_count == expected_writes
    assert len(memories) == expected_writes
    assert "Turn stopped" in text
    assert "".join(chunks) == text
    assert changes == []


def test_tool_results_rebudgeted_before_request(adapter, mocker):
    write = mocker.patch("strides_ai.backends.base.db.save_memory", return_value="x" * 30000)
    backend, requests = adapter()
    text, memories, _ = backend.stream_turn("mandatory", "hello", lambda _: None)
    assert requests.call_count == write.call_count == 1
    assert len(memories) == 1
    assert "Input context limit" in text


@pytest.mark.parametrize("attachment", [False, True])
def test_oversized_submission_never_saved(adapter, tmp_db, attachment):
    from strides_ai.api.conversations import ConversationCoordinator
    from strides_ai import db
    from fastapi import HTTPException

    backend, requests = adapter()
    coordinator = ConversationCoordinator(lambda _: backend)
    turn = coordinator.acquire("running")
    blocks = [{"type": "text", "text": "x" * 30000}] if attachment else None
    with pytest.raises(HTTPException):
        coordinator.start(turn, "mandatory", "hi" if attachment else "x" * 30000, "saved", blocks)
    coordinator.release(turn)
    assert not requests.called
    assert db.get_recent_messages(mode="running") == []


def test_stop_preserves_changes_and_releases_slot(adapter, tmp_db, monkeypatch):
    from strides_ai.api.conversations import ConversationCoordinator
    from strides_ai import db

    monkeypatch.setattr(BaseBackend, "limits", property(lambda _: Limits(rounds=1)))
    backend, _ = adapter()
    coordinator = ConversationCoordinator(lambda _: backend)
    turn = coordinator.acquire("running")
    coordinator.start(turn, "mandatory", "hello", "hello", None)
    turn.worker.join(5)
    assert not turn.worker.is_alive()
    assert db.get_all_memories()[0]["content"] == "race"
    assert "Turn stopped" in db.get_recent_messages(mode="running")[-1]["content"]
    chunks = list(turn.tokens.queue)
    assert any(str(chunk).startswith("[MEMORIES]") for chunk in chunks)
    coordinator.release(coordinator.acquire("running"))


def test_history_selection_is_complete_ordered_and_bounded(adapter):
    backend, _ = adapter()
    prior = [{"role": "assistant", "content": "orphan"}]
    for i in range(100):
        prior.extend(
            [{"role": "user", "content": f"q{i}"}, {"role": "assistant", "content": f"a{i}"}]
        )
    # Convert neutral history using the adapter's existing constructor conversion for Gemini.
    if backend.label.startswith("gemini:"):
        from google.genai import types

        backend._history = [
            types.Content(
                role="model" if m["role"] == "assistant" else "user",
                parts=[types.Part.from_text(text=m["content"])],
            )
            for m in prior
        ]
    else:
        backend._history = prior
    system = backend.prepare_turn(ContextPrompt("mandatory", ["profile"], ["old" * 30000]), "now")
    assert backend._retained_messages == 40
    assert backend._retained_activities == 0
    assert len(backend._history) == 40
    assert "oldold" not in system
    head = backend._history[0]
    assert (head.parts[0].text if hasattr(head, "parts") else head["content"]) == "q80"
    assert estimate([system, backend._history, backend._tool_definitions()]) < 24000


def test_archive_summary_totals_and_bound():
    today = date(2026, 10, 15)
    rows = []
    for i in range(10000):
        rows.append(
            {
                "date": (today - timedelta(days=i)).isoformat(),
                "sport_type": "Run",
                "distance_m": 1000,
                "moving_time_s": 600,
            }
        )
    summary = older_activity_summary(rows, today)
    assert len(summary.splitlines()) < 45
    assert "earlier (coarsened)" in summary
    assert "1999-" in summary
    counts = [
        int(line.split("count=")[1].split(" |")[0])
        for line in summary.splitlines()
        if "count=" in line
    ]
    assert sum(counts) == 10000
    assert "km=4.00 | minutes=40.0" in summary
    assert build_initial_history(rows, []) == []


def test_context_window_validation():
    with pytest.raises(ValueError, match="context window"):
        Limits(context_window=1000)


def test_retries_do_not_replay_completed_writes(adapter, mocker, monkeypatch):
    """Transport retries surround provider setup, never the encompassing tool loop."""
    write = mocker.patch("strides_ai.backends.base.db.save_memory", return_value="saved")
    backend, requests = adapter()
    monkeypatch.setattr(BaseBackend, "limits", property(lambda _: Limits(rounds=2)))
    monkeypatch.setattr("time.sleep", lambda _: None)
    if backend.label.startswith("gemini:"):
        from google.genai.errors import ClientError

        original = backend._client.models.generate_content.side_effect
        attempts = [0]

        def flaky(**kwargs):
            attempts[0] += 1
            if attempts[0] < 3:
                raise ClientError(429, {"error": {"message": "retry"}})
            return original(**kwargs)

        backend._client.models.generate_content.side_effect = flaky
    else:
        original = backend._transport_call
        attempts = [0]

        def wrapped(call):
            def flaky():
                attempts[0] += 1
                if attempts[0] in (2, 3):
                    raise TimeoutError("retry")
                return call()

            return original(flaky)

        backend._transport_call = wrapped
    text, memories, _ = backend.stream_turn("mandatory", "hello", lambda _: None)
    assert requests.call_count == write.call_count == len(memories) == 2
    assert backend._budget.rounds == 2
    assert "Turn stopped" in text


def test_output_and_tool_arguments_share_turn_budget(adapter, mocker, monkeypatch):
    monkeypatch.setattr(BaseBackend, "limits", property(lambda _: Limits(total_output_tokens=12)))
    write = mocker.patch("strides_ai.backends.base.db.save_memory", return_value="saved")
    backend, requests = adapter()
    text, memories, _ = backend.stream_turn("mandatory", "hello", lambda _: None)
    assert "Turn stopped" in text
    assert backend._budget.rounds <= 2
    assert write.call_count <= 1
    assert len(memories) == write.call_count


def test_measurement_includes_reasoning():
    from strides_ai.budget import TurnBudget

    budget = TurnBudget(Limits(total_output_tokens=5000))
    budget.request("sys", [], [])
    budget.output("short")
    budget.usage(3900)
    assert budget.output_remaining == 1100
    budget.request("sys", [], [])
    with pytest.raises(BudgetExceeded):
        budget.output("x" * 4800)


def test_summary_distinguishes_sports_and_dates():
    rows = [
        dict(
            date="2026-10-01",
            sport_type=s,
            distance_m=1000,
            moving_time_s=600,
            total_sets=sets,
            total_volume_kg=volume,
        )
        for s, sets, volume in [("Run", 0, 0), ("Ride", 0, 0), ("WeightTraining", 4, 200)]
    ]
    text = older_activity_summary(rows, date(2026, 10, 15))
    assert "running" in text and "cycling" in text and "strength" in text
    assert text.count("2026-10-01..2026-10-01 | count=1") == 3
    assert "sets=4 | volume_kg=200.0" in text


def test_tool_sequences_are_not_split(adapter):
    backend, _ = adapter()
    if backend.label.startswith("gemini:"):
        from google.genai import types

        backend._history = [
            types.Content(role="user", parts=[types.Part.from_text(text="q")]),
            types.Content(
                role="model",
                parts=[types.Part(function_call=types.FunctionCall(name="save_memory", args={}))],
            ),
        ]
    else:
        backend._history = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "x"}]},
            {"role": "tool", "content": "result"},
            {"role": "assistant", "content": "done"},
        ]
    backend.prepare_turn("mandatory", "now")
    assert backend._history == []


def test_retry_exhaustion_stops_without_replaying_writes(adapter, mocker, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    backend, requests = adapter()
    write = mocker.patch("strides_ai.backends.base.db.save_memory", return_value="saved")
    attempts = [0]
    if backend.label.startswith("gemini:"):
        from google.genai.errors import ClientError

        def fail(**kwargs):
            attempts[0] += 1
            raise ClientError(429, {"error": {"message": "retry"}})

        backend._client.models.generate_content.side_effect = fail
    else:
        original = backend._transport_call

        def wrapped(call):
            if requests.call_count == 0:
                return original(call)

            def fail():
                attempts[0] += 1
                raise TimeoutError("retry")

            return original(fail)

        backend._transport_call = wrapped
    text, memories, _ = backend.stream_turn("mandatory", "hello", lambda _: None)
    assert attempts[0] == 3
    assert requests.call_count == write.call_count == len(memories) == 1
    assert "Transport retry limit" in text
    assert backend._budget.rounds == 2


def test_cancellation_before_provider_and_tool(adapter, mocker):
    import threading

    backend, requests = adapter()
    write = mocker.patch("strides_ai.backends.base.db.save_memory")
    backend.cancel_event = threading.Event()
    backend.cancel_event.set()
    with pytest.raises(InterruptedError):
        backend.stream_turn("mandatory", "hello", lambda _: None)
    assert not requests.called and not write.called


def test_huge_archive_and_history_fit_shared_budget(adapter, tmp_db):
    from strides_ai.coach import build_system
    from google.genai import types

    backend, _ = adapter()
    history = build_initial_history(
        [],
        [
            {"role": role, "content": f"{i} " + "history " * 100}
            for i in range(1000)
            for role in ("user", "assistant")
        ],
    )
    if backend.label.startswith("gemini:"):
        backend._history = [
            types.Content(
                role="model" if m["role"] == "assistant" else "user",
                parts=[types.Part.from_text(text=m["content"])],
            )
            for m in history
        ]
    else:
        backend._history = history
    from strides_ai.db.models import Activity

    today = date.today()
    rows = [
        Activity(
            id=i,
            date=(today - timedelta(days=i)).isoformat(),
            sport_type="Run",
            distance_m=1000,
            moving_time_s=600,
            elapsed_time_s=600,
            elevation_gain_m=10,
            name="run",
            avg_pace_s_per_km=600,
        ).model_dump()
        for i in range(10000)
    ]
    system = backend.prepare_turn(build_system("## Profile\nAthlete", [], activities=rows), "now")
    assert (
        estimate([system, backend._submission_history("now", None), backend._tool_definitions()])
        <= 24000
    )
    assert backend._retained_messages <= 40
    assert backend._retained_activities <= 30
    assert "omitted" in system.lower()
    assert "complete training log" not in system.lower()
