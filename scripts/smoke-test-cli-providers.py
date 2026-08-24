#!/usr/bin/env python3
"""Smoke-test Qoder and Kiro providers without exposing the configured API key."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:3081")
    parser.add_argument(
        "--api-key-file",
        type=Path,
        default=Path.home() / "Library/Application Support/Agent Gateway/api-key",
    )
    args = parser.parse_args()
    api_key = args.api_key_file.read_text(encoding="utf-8").strip()
    if not api_key:
        raise SystemExit("API key file is empty")

    chat_text(args.base_url, api_key, "qoder/Auto", "QODER_OK")
    chat_text(args.base_url, api_key, "qoderwork/Auto", "QODERWORK_OK")
    chat_tool(args.base_url, api_key, "qoder/Auto", 42)
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
