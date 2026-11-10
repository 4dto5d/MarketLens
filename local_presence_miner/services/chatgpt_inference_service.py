"""Narrow, tools-off Responses transport for explicitly authorized ChatGPT usage."""
from __future__ import annotations

import json
import time
from threading import Event, Thread

import requests

from local_presence_miner.domain.opportunity_intelligence import canonical
from local_presence_miner.services.chatgpt_auth_service import RESOURCE, ChatGPTAuth


class InferenceError(ValueError):
    """Only bounded, allowlisted error details may reach the UI or receipts."""
    def __init__(self, code: str, status: int = 0):
        self.code, self.status = code, status
        messages = {
            "quota": "ChatGPT plan use reached a limit. Review this app in ChatGPT Settings → Usage; retry explicitly.",
            "auth": "ChatGPT access was rejected. Reconnect explicitly before another request.",
            "unavailable": "ChatGPT plan use is temporarily unavailable. Retry explicitly later.",
            "unsupported": "The selected ChatGPT model or request capability is unavailable. Review model selection.",
            "incomplete": "ChatGPT did not complete an eligible answer. Partial text cannot be adopted.",
            "processing_limit": "ChatGPT exceeded a local processing limit. Partial text cannot be adopted; review mode before retrying.",
            "timeout": "ChatGPT reached the local deadline. Partial text cannot be adopted; remote usage may have occurred.",
            "cancelled": "ChatGPT request was cancelled. Partial text cannot be adopted; remote usage may have occurred.",
        }
        super().__init__(messages.get(code, "ChatGPT request failed. No automatic retry was sent."))


def response_error(value: object, status: int = 0) -> InferenceError:
    error = value.get("error", value) if isinstance(value, dict) else {}
    code = error.get("code", "") if isinstance(error, dict) else ""
    if code == "subscription_sharing_usage_limit_exceeded" or status == 429:
        return InferenceError("quota", status)
    if code == "subscription_sharing_usage_unavailable" or status == 503:
        return InferenceError("unavailable", status)
    if code in {"user_not_eligible", "invalid_token"} or status in {401, 403}:
        return InferenceError("auth", status)
    if code in {"unsupported_capability", "model_not_found"} or status in {400, 404}:
        return InferenceError("unsupported", status)
    return InferenceError("incomplete", status)


def bounded_lines(response, max_bytes: int):
    """Bound wire processing independently of accepted generated text.

    SSE repeats metadata on each token delta; its envelope can be far larger than
    the generated text. The separate 256x wire bound remains finite (about 4MiB
    for Focused) without rejecting ordinary token-sized events as oversized text.
    """
    pending = b""
    total = 0
    for chunk in response.iter_content(chunk_size=4096):
        total += len(chunk)
        if total > max_bytes * 256 + 65536:
            raise InferenceError("processing_limit")
        pending += chunk
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            if len(line) > max_bytes * 2 + 65536:
                raise InferenceError("processing_limit")
            yield line.rstrip(b"\r")
        if len(pending) > max_bytes * 2 + 65536:
            raise InferenceError("processing_limit")
    if pending:
        yield pending.rstrip(b"\r")


class ChatGPTInference:
    def __init__(self, auth: ChatGPTAuth, *, http=None):
        self.auth = auth
        self.http = http or requests.Session()

    def models(self) -> list[dict[str, str]]:
        try:
            with self.http.get(RESOURCE + "/models", headers={"Authorization": "Bearer " + self.auth.access_token()},
                               timeout=15, allow_redirects=False) as response:
                if response.status_code != 200:
                    raise response_error({}, response.status_code)
                entries = response.json()["models"]
                if not isinstance(entries, list):
                    raise ValueError("Invalid ChatGPT model catalog.")
                return [{"slug": row["slug"], "display_name": row["display_name"]} for row in entries
                        if row.get("visibility") == "list" and isinstance(row.get("slug"), str)
                        and isinstance(row.get("display_name"), str)]
        except (requests.RequestException, KeyError, TypeError) as exc:
            raise ValueError("ChatGPT model catalog could not be loaded.") from exc

    def run(self, body: dict, cancel: Event, timeout: int, max_bytes: int, *, expected_binding: str | None = None) -> dict:
        allowed = {"model", "input", "instructions", "store", "stream"}
        if (set(body) - allowed or body.get("store") is not False or body.get("stream") is not True
                or not isinstance(body.get("input"), list) or not body.get("model")):
            raise ValueError("Unsupported ChatGPT request. No request was sent.")
        if timeout <= 0 or max_bytes <= 0 or cancel.is_set():
            raise InferenceError("cancelled")
        deadline = time.monotonic() + timeout
        output: list[str] = []
        size = 0
        try:
            token = self.auth.access_token(expected_binding=expected_binding) if expected_binding is not None else self.auth.access_token()
            if cancel.is_set():
                raise InferenceError("cancelled")
            if time.monotonic() >= deadline:
                raise InferenceError("timeout")
            with self.http.post(RESOURCE + "/responses", headers={"Authorization": "Bearer " + token,
                                "Content-Type": "application/json"},
                                data=canonical(body).encode(),
                                stream=True, timeout=(min(15, timeout), timeout), allow_redirects=False) as response:
                if response.status_code != 200:
                    raise response_error({}, response.status_code)
                finished = Event()

                def watch():
                    while not finished.wait(0.1):
                        if cancel.is_set() or time.monotonic() >= deadline:
                            response.close()
                            return

                watchdog = Thread(target=watch, daemon=True)
                watchdog.start()
                request_id = response.headers.get("x-request-id", "")[:200]
                data: list[str] = []
                for line in bounded_lines(response, max_bytes):
                    if cancel.is_set():
                        raise InferenceError("cancelled")
                    if time.monotonic() >= deadline:
                        raise InferenceError("timeout")
                    if line.startswith(b"data:"):
                        data.append(line[5:].strip().decode("utf-8"))
                    elif not line and data:
                        payload = "\n".join(data)
                        data = []
                        if payload == "[DONE]":
                            break
                        event = json.loads(payload)
                        kind = event.get("type")
                        if kind == "response.output_text.delta":
                            delta = event["delta"]
                            size += len(delta.encode())
                            if size > max_bytes:
                                raise InferenceError("processing_limit")
                            output.append(delta)
                        elif kind == "response.completed":
                            result = event.get("response", {})
                            if cancel.is_set() or result.get("status") not in {None, "completed"}:
                                raise ValueError("ChatGPT response was not completed.")
                            finished.set()
                            return {"text": "".join(output), "usage": result.get("usage"), "request_id": request_id}
                        elif kind in {"response.failed", "response.incomplete", "error", "response.refusal.delta"}:
                            raise response_error(event.get("response", event))
                finished.set()
                raise ValueError("ChatGPT stream ended without completed inference; partial text cannot be adopted.")
        except (requests.RequestException, json.JSONDecodeError, UnicodeError, KeyError, TypeError, AttributeError) as exc:
            # Closing a requests response from the cancellation watchdog can
            # clear urllib3/http.client's file object during an in-progress read.
            # That close race is a terminal cancellation/deadline, not an app crash.
            if cancel.is_set():
                raise InferenceError("cancelled") from exc
            if time.monotonic() >= deadline:
                raise InferenceError("timeout") from exc
            raise ValueError("ChatGPT inference was interrupted or malformed. No automatic retry was sent.") from exc
        finally:
            if "finished" in locals():
                finished.set()
