#!/usr/bin/env python3
"""Configure Work via Alma's native API, using approved VPS model accounts.

Run on the VPS as its existing administrator. No credentials in arguments,
stdout or intermediate files. Does not edit AstrBot, or scan/import accounts.
"""
import argparse
import json
from pathlib import Path
import urllib.request

BASE = "http://127.0.0.1:23001"
# Official MiMo V2.6 Flash and DeepSeek Flash APIs both advertise 1M context.
# This is model capacity, not an instruction to fill every request to 1M.
MODEL_CONTEXT_TOKENS = 1_000_000


def api(path, method="GET", body=None):
    request = urllib.request.Request(BASE + path, method=method,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def configure_providers():
    current = api("/api/providers")
    configured = {}
    catalog = [
        ("xiaomi", "MiMo", "Work MiMo (existing VPS account)", "custom",
            "https://api.xiaomimimo.com/v1", "mimo-v2.6-flash", "MiMo 2.6 Flash"),
        ("deepseek", "DeepSeek", "DeepSeek", "deepseek",
            "https://api.deepseek.com/v1", "deepseek-v4-flash", "DeepSeek V4 Flash"),
    ]
    for source_id, name, legacy, kind, url, model, label in catalog:
        matching = [p for p in current if p.get("name") in {name, legacy}
            and p.get("baseURL") == url]
        if len(matching) > 1:
            raise SystemExit("duplicate_work_provider")
        if matching:
            provider = api(f"/api/providers/{matching[0]['id']}", "PUT",
                {"name": name, "enabled": True})
        else:
            cfg = json.loads(Path("/home/mac/astrbot/data/cmd_config.json").read_text(encoding="utf-8-sig"))
            source = next(p for p in cfg["provider_sources"] if p["id"] == source_id)
            if source.get("api_base") != url or len(source.get("key", [])) != 1:
                raise SystemExit("unexpected_approved_source")
            provider = api("/api/providers", "POST", dict(name=name, type=kind,
                apiKey=source["key"][0], baseURL=url, enabled=True))
        enabled = [m if isinstance(m, str) else m["id"] for m in provider.get("models", [])]
        available = [m for m in provider.get("availableModels", []) if m.get("id") != model]
        api(f"/api/providers/{provider['id']}/models", "PUT", {"models": list(dict.fromkeys([*enabled, model])), "availableModels": [*available, {
            "id": model, "name": label, "isManual": True, "apiFormat": "openai-chat",
            "capabilityOverrides": {"functionCalling": True, "streaming": True, "vision": False,
                "contextWindow": MODEL_CONTEXT_TOKENS, "maxOutputTokens": 4096},
        }]})
        configured[source_id] = {"id": provider["id"], "model": model, "name": name}
    return configured


def configure():
    # The separate native personal-agent module defaults to proactive check-ins;
    # memory.enabled=false alone does not disable that background generation.
    personal = api("/api/personal")["settings"]
    personal["proactive"] = False
    personal["routing"] = {**personal.get("routing", {}), "email": False,
        "telegram": False, "notifications": False, "autoHandle": False}
    api("/api/personal/settings", "PUT", personal)
    heartbeat = api("/api/heartbeat/config")
    heartbeat["enabled"] = False
    api("/api/heartbeat/config", "PUT", heartbeat)
    providers = configure_providers()
    provider = providers["xiaomi"]
    model = provider["model"]
    workspaces = api("/api/workspaces")
    workspace = next((w for w in workspaces if w.get("path") == "/srv/alma-work"), None)
    if workspace is None:
        workspace = api("/api/workspaces", "POST", {"name": "默认工作区", "path": "/srv/alma-work"})
    settings = api("/api/settings")
    settings.pop("needsEmbeddingRebuild", None)
    updates = {
        "general": {"language": "zh", "defaultWorkspaceId": workspace["id"]},
        "chat": {"defaultModel": f"{provider['id']}:{model}", "maxTokens": 4096,
            "streamResponse": True, "autoSaveHistory": True,
            "defaultToolSelection": "auto", "defaultSkillSelection": "auto"},
        "memory": {"enabled": False, "autoSummarize": False, "autoRetrieve": False,
            "queryRewriting": False},
        "network": {"retryAttempts": 0, "requestLog": False,
            "llmTimeout": 120000, "timeout": 30000},
        "security": {"autoApproveToolRequests": False, "enableLogging": False},
        "agents": {"enabled": True, "allowSubagentDelegation": True},
        "toolModel": {"model": f"{provider['id']}:{model}"},
        "whisper": {"enabled": False},
        "onboarding": {"dismissed": True},
    }
    for key, values in updates.items():
        settings[key] = {**settings.get(key, {}), **values}
    api("/api/settings", "PUT", settings)
    # Report only non-secret readiness fields.
    check = api("/api/settings")
    assert check["security"]["autoApproveToolRequests"] is False
    assert check["network"]["retryAttempts"] == 0
    assert check["memory"]["enabled"] is False
    assert api("/api/personal")["settings"]["proactive"] is False
    print(json.dumps({"configured": True, "model": model, "memory": False,
        "automatic_network_retries": 0, "workspace_tool_policy": "native_auto"}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--providers-only", action="store_true",
        help="Add/enable approved providers without changing user settings or current models")
    args = parser.parse_args()
    try:
        if args.providers_only:
            providers = configure_providers()
            print(json.dumps({"configured_providers": [
                {"name": p["name"], "model": p["model"]} for p in providers.values()]}))
        else:
            configure()
    except Exception as error:
        # Never print an upstream response, config object, or credential.
        raise SystemExit("configuration_failed:" + type(error).__name__) from None
