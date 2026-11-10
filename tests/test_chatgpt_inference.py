"""Responses transport contracts. No model or account is contacted."""
import json
from threading import Event

import pytest

from local_presence_miner.services.chatgpt_inference_service import ChatGPTInference


class Auth:
    def access_token(self):
        return "synthetic-token"


class Stream:
    status_code = 200
    headers = {"x-request-id": "synthetic-request"}

    def __init__(self, events=(), payload=None):
        self.events, self.payload, self.closed = events, payload, False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self):
        self.closed = True

    def json(self):
        return self.payload

    def iter_lines(self, **_kwargs):
        for event in self.events:
            yield b"data: " + json.dumps(event).encode()
            yield b""

    def iter_content(self, **_kwargs):
        for line in self.iter_lines():
            yield line + b"\n"


class HTTP:
    def __init__(self, stream):
        self.stream, self.calls = stream, []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.stream

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.stream


def body():
    return {"model": "catalog-selected", "store": False, "stream": True, "input": [{"role": "user", "content": "synthetic"}]}


def test_completed_stream_and_exact_request_bytes():
    stream = Stream([{"type": "response.output_text.delta", "delta": '{"hello":"world"}'},
                     {"type": "response.completed", "response": {"status": "completed", "usage": {"output_tokens": 3}}}])
    http = HTTP(stream)
    value = ChatGPTInference(Auth(), http=http).run(body(), Event(), 5, 100)
    assert json.loads(value["text"]) == {"hello": "world"}
    assert value["usage"] == {"output_tokens": 3} and value["request_id"] == "synthetic-request"
    assert len(http.calls) == 1 and http.calls[0][0] == "https://api.openai.com/v1/responses"
    assert json.loads(http.calls[0][1]["data"]) == body() and stream.closed


@pytest.mark.parametrize("terminal", ["response.failed", "response.incomplete", "error", "response.refusal.delta", None])
def test_partial_text_is_not_a_completed_response(terminal):
    events = [{"type": "response.output_text.delta", "delta": "partial"}]
    if terminal:
        events.append({"type": terminal})
    http = HTTP(Stream(events))
    with pytest.raises(ValueError):
        ChatGPTInference(Auth(), http=http).run(body(), Event(), 5, 100)
    assert len(http.calls) == 1


@pytest.mark.parametrize("bad", [{"max_output_tokens": 20}, {"tools": []}, {"store": True}, {"stream": False}])
def test_unsupported_request_not_sent(bad):
    http = HTTP(Stream())
    with pytest.raises(ValueError, match="Unsupported"):
        ChatGPTInference(Auth(), http=http).run(body() | bad, Event(), 5, 100)
    assert not http.calls


def test_pre_cancel_and_size_limit():
    http = HTTP(Stream([{"type": "response.output_text.delta", "delta": "123456789"}]))
    cancel = Event()
    cancel.set()
    with pytest.raises(ValueError, match="cancelled"):
        ChatGPTInference(Auth(), http=http).run(body(), cancel, 5, 5)
    assert not http.calls
    with pytest.raises(ValueError, match="local processing limit"):
        ChatGPTInference(Auth(), http=http).run(body(), Event(), 5, 5)
    assert http.stream.closed


def test_catalog_uses_models_and_visibility_in_server_order():
    http = HTTP(Stream(payload={"models": [{"slug": "first", "display_name": "First", "visibility": "list"},
        {"slug": "hidden", "display_name": "Hidden", "visibility": "hide"},
        {"slug": "last", "display_name": "Last", "visibility": "list"}]}))
    assert ChatGPTInference(Auth(), http=http).models() == [
        {"slug": "first", "display_name": "First"}, {"slug": "last", "display_name": "Last"}]


def test_late_cancellation_is_not_adoptable():
    cancel = Event()

    class CancelStream(Stream):
        def iter_lines(self, **_kwargs):
            cancel.set()
            yield b'data: {"type":"response.completed"}'
            yield b""

    with pytest.raises(ValueError, match="cancelled"):
        ChatGPTInference(Auth(), http=HTTP(CancelStream())).run(body(), cancel, 5, 100)


@pytest.mark.parametrize('status,code', [(429, 'quota'), (401, 'auth'), (403, 'auth'), (503, 'unavailable'), (400, 'unsupported')])
def test_http_failures_are_distinguished_without_raw_error_text(status, code):
    stream = Stream()
    stream.status_code = status
    http = HTTP(stream)
    with pytest.raises(ValueError) as error:
        ChatGPTInference(Auth(), http=http).run(body(), Event(), 5, 100)
    assert error.value.code == code
    assert len(http.calls) == 1


def test_unterminated_sse_line_is_bounded():
    class Hostile(Stream):
        def iter_content(self, **_kwargs):
            for _ in range(20):
                yield b'x' * 4096

    stream = Hostile()
    with pytest.raises(ValueError, match='processing limit'):
        ChatGPTInference(Auth(), http=HTTP(stream)).run(body(), Event(), 5, 100)
    assert stream.closed


def test_late_quota_error_has_specific_status():
    http = HTTP(Stream([{'type': 'response.output_text.delta', 'delta': 'partial'},
                        {'type': 'response.failed', 'response': {'error': {'code': 'subscription_sharing_usage_limit_exceeded'}}}]))
    with pytest.raises(ValueError) as error:
        ChatGPTInference(Auth(), http=http).run(body(), Event(), 5, 100)
    assert error.value.code == 'quota'
    assert len(http.calls) == 1


def test_token_sized_events_fit_within_text_limit_despite_envelope_overhead():
    # A real stream repeats item/sequence metadata on every tiny token delta.
    # 10KiB of text is valid under Focused's 16KiB output limit.
    events = [{"type": "response.output_text.delta", "sequence_number": i,
               "item_id": "msg_synthetic_stream_overhead", "output_index": 0,
               "content_index": 0, "delta": "word", "logprobs": []} for i in range(2500)]
    events.append({"type": "response.completed", "response": {"status": "completed"}})
    result = ChatGPTInference(Auth(), http=HTTP(Stream(events))).run(body(), Event(), 60, 16384)
    assert result["text"] == "word" * 2500


def test_wire_bound_still_rejects_excessive_complete_comment_lines():
    class ExcessiveWire(Stream):
        def iter_content(self, **_kwargs):
            for _ in range(2000):
                yield b":" + b"x" * 4094 + b"\n"

    stream = ExcessiveWire()
    with pytest.raises(ValueError, match="processing limit"):
        ChatGPTInference(Auth(), http=HTTP(stream)).run(body(), Event(), 60, 16384)
    assert stream.closed


def test_local_limit_has_distinct_safe_error_code():
    stream = Stream([{"type": "response.output_text.delta", "delta": "too much"}])
    with pytest.raises(ValueError) as error:
        ChatGPTInference(Auth(), http=HTTP(stream)).run(body(), Event(), 60, 1)
    assert error.value.code == "processing_limit"


@pytest.mark.parametrize('ending', ['cancelled', 'timeout'])
def test_watchdog_socket_close_race_is_normalized(monkeypatch, ending):
    from types import SimpleNamespace

    import local_presence_miner.services.chatgpt_inference_service as module
    clock = [0.0]
    monkeypatch.setattr(module, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    cancel = Event()

    class ClosedSocket(Stream):
        def iter_content(self, **_kwargs):
            if ending == 'cancelled':
                cancel.set()
            else:
                clock[0] = 61
            raise AttributeError("read on closed response file")
            yield b''

    with pytest.raises(ValueError) as error:
        module.ChatGPTInference(Auth(), http=HTTP(ClosedSocket())).run(body(), cancel, 60, 16384)
    assert error.value.code == ending
