"""Two native Alma behavior probes; private receipts prevent automatic replay.

Run on the VPS with the existing Python websockets dependency. Test threads are
incognito so neither probe becomes personal memory. No platform messages.
"""
import asyncio
import json
import re
from pathlib import Path
import time
import sys
import urllib.request
import uuid

import websockets


BASE = "http://127.0.0.1:23001"


def api(path, method="GET", body=None):
    request = urllib.request.Request(BASE + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return None if response.status == 204 else json.load(response)


def complete_reads(value):
    if isinstance(value, dict):
        return int(value.get("read_complete") is True) + sum(
            complete_reads(v) for v in value.values())
    if isinstance(value, list):
        return sum(complete_reads(v) for v in value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            decoder, count, offset = json.JSONDecoder(), 0, 0
            while offset < len(value):
                positions = [p for p in (value.find("{", offset), value.find("[", offset)) if p >= 0]
                if not positions:
                    break
                begin = min(positions)
                try:
                    parsed, length = decoder.raw_decode(value[begin:])
                except ValueError:
                    offset = begin + 1
                    continue
                count += complete_reads(parsed)
                offset = begin + length
            return count
        return complete_reads(parsed) if not isinstance(parsed, str) else 0
    return 0


async def probe(home, name, prompt, expect_source, native_auto=False):
    receipt = home / (name + ".json")
    if receipt.exists():
        raise RuntimeError("probe_already_reserved_do_not_repeat")
    state = {"state": "reserved", "started_at": time.time()}
    save = lambda: receipt.write_text(json.dumps(state))
    save()
    thread = api("/api/threads", "POST", {"title": "Retrieval behavior probe: " + name})
    thread = api("/api/threads/" + thread["id"], "PUT", {"isIncognito": True})
    if not thread.get("isIncognito"):
        raise RuntimeError("incognito_not_enabled")
    tid = thread["id"]
    state.update(thread_id=tid, incognito=True)
    save()
    async with websockets.connect(BASE.replace("http:", "ws:") + "/ws/threads",
            proxy=None, open_timeout=15, max_size=32 * 1024 * 1024) as ws:
        state["state"] = "sent_or_unknown"
        save()
        data = {
            "threadId": tid, "userMessage": {"id": str(uuid.uuid4()), "role": "user",
                "parts": [{"type": "text", "text": prompt}]}}
        if native_auto:
            servers = api("/api/mcp-servers")
            data.update(tools=["__auto__"], enabledMCPServerIds=[
                s["id"] for s in servers if s.get("enabled")])
        await ws.send(json.dumps({"type": "generate_response", "data": data}))
        print(json.dumps({"probe_started": name, "incognito": True}), flush=True)
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            try:
                event = json.loads(await asyncio.wait_for(ws.recv(), timeout=25))
            except asyncio.TimeoutError:
                print(json.dumps({"probe_waiting": name}), flush=True)
                continue
            data = event.get("data") or {}
            if isinstance(data, dict) and data.get("threadId") not in (None, tid):
                continue
            if event.get("type") == "error":
                state["state"] = "native_error_no_retry"
                save()
                raise RuntimeError("native_probe_error")
            if event.get("type") == "generation_completed":
                break
        else:
            await ws.send(json.dumps({"type": "stop_generation", "data": {"threadId": tid}}))
            state["state"] = "test_cancelled_after_timeout_no_retry"
            save()
            raise RuntimeError("probe_timeout")
    messages = api("/api/threads/" + tid + "/messages")
    (home / (name + "-messages.json")).write_text(json.dumps(messages))
    parts = [p for row in messages for p in row.get("message", row).get("parts", [])]
    tools = [p for p in parts if p.get("type", "").startswith("tool-")]
    source_tools = [p for p in tools if "shared_knowledge" in (
        p.get("type", "") + json.dumps(p.get("input", {})))]
    personal_lookups = [p for p in tools if any(token in (
        p.get("type", "") + json.dumps(p.get("input", {}))) for token in (
            "shared_knowledge", "wucai_read", "memory search", "memory list", "/api/memories"))]
    complete = sum(complete_reads(p.get("output")) for p in tools)
    passed = bool(source_tools) and complete > 0 if expect_source else not personal_lookups
    answer = "\n".join(p.get("text", "") for p in parts if p.get("type") == "text")
    state.update(state="passed" if passed else "failed_behavior", tool_calls=len(tools),
        source_tool_calls=len(source_tools), complete_read_markers=complete,
        personal_lookup_tool_calls=len(personal_lookups),
        elapsed_seconds=round(time.time() - state["started_at"], 2))
    save()
    print(json.dumps({"probe": name, **state, "answer_excerpt": answer[-1800:]},
        ensure_ascii=False), flush=True)
    return passed


async def main():
    home = sorted(Path("/var/backups/alma-work").glob("retrieval-policy-*"))[-1]
    native_auto = "--without-auto-tools" not in sys.argv
    suffix = "-native-auto" if native_auto else ""
    revision = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--revision=")), "")
    if revision:
        if not re.fullmatch(r"[a-z0-9-]{1,40}", revision):
            raise ValueError("invalid_probe_revision")
        suffix += "-" + revision
    personal = await probe(home, "personal-advice" + suffix,
        "结合我之前说过的英语目标，我接下来该怎么安排口语练习？简短给两点建议。", True, native_auto)
    generic = await probe(home, "generic-translation" + suffix,
        "把‘明天见’翻译成英语。", False, native_auto)
    print(json.dumps({"personal_retrieval": personal, "generic_no_retrieval": generic,
        "incognito_probes": True, "native_auto_tools": native_auto, "platform_messages": 0}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
