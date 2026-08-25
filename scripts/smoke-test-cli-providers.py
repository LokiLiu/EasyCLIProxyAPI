#!/usr/bin/env python3
"""Smoke-test Qoder and Kiro providers without exposing the configured API key."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import urllib.error
import urllib.request
from pathlib import Path


def request_json(base_url: str, api_key: str, path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        base_url.rstrip("/") + path,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:1000]
        raise RuntimeError(f"HTTP {error.code}: {detail}") from error


def load_api_key(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    if path.suffix in {".yaml", ".yml"}:
        match = re.search(
            r"(?ms)^api-keys:\s*\n(?:\s*#.*\n)*\s*-\s*['\"]?([^'\"\s#]+)",
            content,
        )
        api_key = match.group(1) if match else ""
    else:
        api_key = content.strip()
    if not api_key:
        raise SystemExit(f"No API key found in {path}")
    return api_key


def chat_text(base_url: str, api_key: str, model: str, marker: str) -> None:
    response = request_json(
        base_url,
        api_key,
        "/v1/chat/completions",
        {
            "model": model,
            "messages": [{"role": "user", "content": f"Reply only with {marker}"}],
            "max_tokens": 32,
        },
    )
    content = response["choices"][0]["message"].get("content", "")
    if marker.lower() not in content.lower():
        raise RuntimeError(f"{model} returned unexpected text: {content[:160]!r}")
    print(f"PASS text {model}")


def chat_tool(base_url: str, api_key: str, model: str, value: int) -> None:
    response = request_json(
        base_url,
        api_key,
        "/v1/chat/completions",
        {
            "model": model,
            "messages": [
                {"role": "user", "content": f"Call echo_number with the integer {value}."}
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "echo_number",
                        "description": "Echo an integer",
                        "parameters": {
                            "type": "object",
                            "properties": {"value": {"type": "integer"}},
                            "required": ["value"],
                        },
                    },
                }
            ],
            "tool_choice": {"type": "function", "function": {"name": "echo_number"}},
        },
    )
    calls = response["choices"][0]["message"].get("tool_calls") or []
    if len(calls) != 1 or calls[0]["function"]["name"] != "echo_number":
        raise RuntimeError(f"{model} returned invalid tool calls: {calls!r}")
    arguments = json.loads(calls[0]["function"]["arguments"])
    if arguments.get("value") != value or not isinstance(arguments.get("value"), int):
        raise RuntimeError(f"{model} returned invalid arguments: {arguments!r}")
    print(f"PASS tool {model} value={value}")


def chat_stream(base_url: str, api_key: str, model: str) -> None:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(
            {
                "model": model,
                "messages": [{"role": "user", "content": "Reply only with stream works"}],
                "stream": True,
                "max_tokens": 32,
            }
        ).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    chunks = []
    with urllib.request.urlopen(request, timeout=180) as response:
        for raw_line in response:
            line = raw_line.decode(errors="replace").strip()
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            event = json.loads(line[6:])
            content = event.get("choices", [{}])[0].get("delta", {}).get("content")
            if content:
                chunks.append(content)
    if len(chunks) < 2 or "stream works" not in "".join(chunks).lower():
        raise RuntimeError(f"{model} did not produce incremental SSE chunks: {chunks!r}")
    print(f"PASS stream {model} chunks={len(chunks)}")


def claude_tool(base_url: str, api_key: str, model: str, value: int) -> None:
    response = request_json(
        base_url,
        api_key,
        "/v1/messages",
        {
            "model": model,
            "max_tokens": 64,
            "messages": [
                {"role": "user", "content": f"Call echo_number with the integer {value}."}
            ],
            "tools": [
                {
                    "name": "echo_number",
                    "description": "Echo an integer",
                    "input_schema": {
                        "type": "object",
                        "properties": {"value": {"type": "integer"}},
                        "required": ["value"],
                    },
                }
            ],
            "tool_choice": {"type": "tool", "name": "echo_number"},
        },
    )
    calls = [item for item in response.get("content", []) if item.get("type") == "tool_use"]
    if len(calls) != 1 or calls[0].get("name") != "echo_number":
        raise RuntimeError(f"{model} returned invalid Claude tool use: {calls!r}")
    if calls[0].get("input", {}).get("value") != value:
        raise RuntimeError(f"{model} returned invalid Claude tool input: {calls[0]!r}")
    print(f"PASS claude-tool {model} value={value}")


def claude_text(base_url: str, api_key: str, model: str, marker: str) -> None:
    response = request_json(
        base_url,
        api_key,
        "/v1/messages",
        {
            "model": model,
            "max_tokens": 32,
            "messages": [{"role": "user", "content": f"Reply only with {marker}"}],
        },
    )
    text = "".join(
        item.get("text", "")
        for item in response.get("content", [])
        if item.get("type") == "text"
    )
    if marker.lower() not in text.lower() or response.get("stop_reason") != "end_turn":
        raise RuntimeError(f"{model} returned unexpected Claude text: {response!r}")
    print(f"PASS claude-text {model}")


def claude_stream(base_url: str, api_key: str, model: str) -> None:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/v1/messages",
        data=json.dumps(
            {
                "model": model,
                "max_tokens": 32,
                "stream": True,
                "messages": [
                    {"role": "user", "content": "Reply only with stream works"}
                ],
            }
        ).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        },
    )
    event_types = []
    chunks = []
    with urllib.request.urlopen(request, timeout=180) as response:
        for raw_line in response:
            line = raw_line.decode(errors="replace").strip()
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            event_types.append(event.get("type"))
            if event.get("type") == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta" and delta.get("text"):
                    chunks.append(delta["text"])
    required = {"message_start", "content_block_start", "message_delta", "message_stop"}
    if not required.issubset(event_types) or "stream works" not in "".join(chunks).lower():
        raise RuntimeError(
            f"{model} returned invalid Claude stream: events={event_types!r}, chunks={chunks!r}"
        )
    print(f"PASS claude-stream {model} chunks={len(chunks)}")


def claude_tool_result(base_url: str, api_key: str, model: str, value: int) -> None:
    first = request_json(
        base_url,
        api_key,
        "/v1/messages",
        {
            "model": model,
            "max_tokens": 64,
            "messages": [
                {"role": "user", "content": f"Call echo_number with the integer {value}."}
            ],
            "tools": [
                {
                    "name": "echo_number",
                    "description": "Echo an integer",
                    "input_schema": {
                        "type": "object",
                        "properties": {"value": {"type": "integer"}},
                        "required": ["value"],
                    },
                }
            ],
            "tool_choice": {"type": "tool", "name": "echo_number"},
        },
    )
    calls = [item for item in first.get("content", []) if item.get("type") == "tool_use"]
    if len(calls) != 1:
        raise RuntimeError(f"{model} did not return exactly one Claude tool_use: {first!r}")
    call = calls[0]
    second = request_json(
        base_url,
        api_key,
        "/v1/messages",
        {
            "model": model,
            "max_tokens": 64,
            "messages": [
                {"role": "user", "content": f"Call echo_number with the integer {value}."},
                {"role": "assistant", "content": first["content"]},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": call["id"],
                            "content": str(value),
                        }
                    ],
                },
            ],
            "tools": [
                {
                    "name": "echo_number",
                    "description": "Echo an integer",
                    "input_schema": {
                        "type": "object",
                        "properties": {"value": {"type": "integer"}},
                        "required": ["value"],
                    },
                }
            ],
        },
    )
    text = "".join(
        item.get("text", "")
        for item in second.get("content", [])
        if item.get("type") == "text"
    )
    if str(value) not in text or second.get("stop_reason") != "end_turn":
        raise RuntimeError(f"{model} did not consume Claude tool_result: {second!r}")
    print(f"PASS claude-tool-result {model} value={value}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3081")
    parser.add_argument(
        "--api-key-file",
        type=Path,
        default=Path.home()
        / "Library/Application Support/com.cpa.gui/cpa-core/config.yaml",
    )
    args = parser.parse_args()
    api_key = load_api_key(args.api_key_file)

    claude_text(args.base_url, api_key, "qoder/Aria", "NATIVE_MESSAGES_OK")
    claude_text(args.base_url, api_key, "qoderwork/Aria", "WORK_MESSAGES_OK")
    claude_stream(args.base_url, api_key, "qoder/Aria")
    claude_tool(args.base_url, api_key, "qoder/Aria", 42)
    claude_tool_result(args.base_url, api_key, "qoder/Aria", 43)
    # Retain one OpenAI request as a compatibility guard for existing clients.
    chat_text(args.base_url, api_key, "qoder/Auto", "OPENAI_COMPAT_OK")
    chat_stream(args.base_url, api_key, "kiro/claude-opus-5")
    claude_tool(args.base_url, api_key, "kiro/claude-opus-5", 11)
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(chat_tool, args.base_url, api_key, "kiro/claude-opus-5", value)
            for value in (8, 9)
        ]
        for future in futures:
            future.result()
    print("PASS all provider smoke tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
