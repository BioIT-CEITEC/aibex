# /// script
# requires-python = ">=3.11"
# dependencies = ["openai>=1.40", "python-dotenv>=1.0", "jsonpatch>=1.33"]
# ///
"""Compare LLMs on the e-INFRA CZ service (or any OpenAI-compatible endpoint) for Aibex View.

Usage (from the repo root, with LLM_BASE_URL / LLM_API_KEY in .env):
    uv run scripts/llm_eval.py                 # list models + test the default candidates
    uv run scripts/llm_eval.py --models agentic,coder,Qwen3.8-flash-next
    uv run scripts/llm_eval.py --list          # only list available models

For each model and each test prompt it checks:
  - does the model return a tool call (native function calling)?
  - if not, does the text contain a usable JSON patch (fallback)?
  - does the patch apply to the example spec and produce the expected change?
  - latency
The key is read from the environment and never printed.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import time
from pathlib import Path

import jsonpatch
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DEFAULT_CANDIDATES = [
    "agentic",
    "coder",
    "mini",
    "Qwen3.8-flash-next",
    "Glm-5.3-flash",
    "Kimi-k3.1-pro",
    "Glm-5.3",
    "Gpt-oss-120b",
]

EXAMPLE_SPEC = {
    "version": 1,
    "title": "Example: KO vs WT",
    "bundle": "example",
    "filters": [],
    "panels": [
        {
            "id": "volcano",
            "type": "plot",
            "title": "Volcano",
            "table": "de",
            "kind": "scatter",
            "x": {"field": "log2FoldChange"},
            "y": {"expr": "-log10(padj)"},
            "color": {"field": "significant"},
            "label": {"field": "gene_name", "values": []},
        },
        {
            "id": "genes",
            "type": "table",
            "title": "Genes",
            "table": "de",
            "columns": ["gene_name", "log2FoldChange", "padj"],
        },
    ],
    "layout": [{"i": "volcano", "x": 0, "y": 0, "w": 6, "h": 9}, {"i": "genes", "x": 6, "y": 0, "w": 6, "h": 9}],
}

BUNDLE_SCHEMA = {
    "tables": {
        "de": {
            "columns": {
                "gene_id": "string",
                "gene_name": "string",
                "baseMean": "float",
                "log2FoldChange": "float",
                "padj": "float",
                "significant": "bool",
            }
        }
    }
}

UPDATE_VIEW_TOOL = {
    "type": "function",
    "function": {
        "name": "update_view",
        "description": "Change the dashboard by applying an RFC 6902 JSON Patch to the current view spec.",
        "parameters": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "array",
                    "description": "RFC 6902 operations (op, path, value).",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {"type": "string", "enum": ["add", "remove", "replace", "move", "copy", "test"]},
                            "path": {"type": "string"},
                            "from": {"type": "string"},
                            "value": {},
                        },
                        "required": ["op", "path"],
                    },
                },
                "summary": {"type": "string", "description": "One short sentence describing the change."},
            },
            "required": ["patch", "summary"],
        },
    },
}

SYSTEM = (
    "You are the assistant inside Aibex View, a dashboard for bioinformatics results. "
    "The UI is fully described by a JSON view spec. To change the UI, call the tool update_view with a "
    "JSON Patch (RFC 6902) against the current spec. Address panels by index (/panels/<i>/...). "
    "Only use tables and columns from the bundle schema. Keep the summary short. "
    "If you cannot call tools, reply with ONLY a JSON object {\"patch\": [...], \"summary\": \"...\"}."
)


def check_label(spec: dict) -> bool:
    vals = spec["panels"][0].get("label", {}).get("values", [])
    return {"Fkbp5", "Tsc22d3"} <= {v.capitalize() for v in vals}


def check_filter(spec: dict) -> bool:
    return any(
        f.get("field") == "padj" and str(f.get("op")) in {"<=", "<"} and float(f.get("value", 1)) <= 0.011
        for f in spec.get("filters", [])
    )


def check_color(spec: dict) -> bool:
    return spec["panels"][0].get("color", {}).get("field") == "log2FoldChange"


TESTS = [
    ("label", "Label the genes Fkbp5 and Tsc22d3 in the volcano plot.", check_label),
    ("filter", "Only show genes with padj below 0.01 everywhere.", check_filter),
    ("color", "Colour the volcano points by log2 fold change instead.", check_color),
]


def extract_patch(msg) -> tuple[list | None, str]:
    """Return (patch, mode) from a chat completion message."""
    if getattr(msg, "tool_calls", None):
        for tc in msg.tool_calls:
            if tc.function.name == "update_view":
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    return args.get("patch"), "tool"
                except json.JSONDecodeError:
                    return None, "tool-badjson"
    text = msg.content or ""
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict) and "patch" in obj:
                return obj["patch"], "json-text"
        except json.JSONDecodeError:
            pass
    return None, "none"


def run_one(client: OpenAI, model: str, prompt: str, check) -> dict:
    user = (
        f"Bundle schema:\n{json.dumps(BUNDLE_SCHEMA)}\n\nCurrent spec:\n{json.dumps(EXAMPLE_SPEC)}\n\n"
        f"Request: {prompt}"
    )
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
            tools=[UPDATE_VIEW_TOOL],
            tool_choice="auto",
            temperature=0,
            timeout=120,
        )
    except Exception as exc:  # noqa: BLE001 – report any provider error
        return {"ok": False, "mode": "error", "latency": time.time() - t0, "note": str(exc)[:120]}
    latency = time.time() - t0
    patch, mode = extract_patch(resp.choices[0].message)
    if patch is None:
        return {"ok": False, "mode": mode, "latency": latency, "note": "no patch"}
    try:
        new_spec = jsonpatch.apply_patch(copy.deepcopy(EXAMPLE_SPEC), patch)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "mode": mode, "latency": latency, "note": f"patch failed: {exc}"[:120]}
    ok = bool(check(new_spec))
    return {"ok": ok, "mode": mode, "latency": latency, "note": "" if ok else "applied, wrong result"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", help="comma-separated model ids/aliases")
    ap.add_argument("--list", action="store_true", help="only list available models")
    args = ap.parse_args()

    base_url = os.getenv("LLM_BASE_URL", "https://llm.ai.e-infra.cz/v1")
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        print("LLM_API_KEY is not set (put it in .env, see .env.example).", file=sys.stderr)
        return 2
    client = OpenAI(base_url=base_url, api_key=api_key)

    try:
        available = sorted(m.id for m in client.models.list().data)
    except Exception as exc:  # noqa: BLE001
        print(f"Could not list models at {base_url}: {exc}", file=sys.stderr)
        return 1
    print(f"Endpoint: {base_url}\nAvailable models ({len(available)}):")
    for m in available:
        print(f"  - {m}")
    if args.list:
        return 0

    wanted = args.models.split(",") if args.models else DEFAULT_CANDIDATES
    lower = {m.lower(): m for m in available}
    models = [lower.get(w.lower(), w) for w in wanted]

    print("\nmodel                          test     ok   mode        latency  note")
    print("-" * 90)
    summary = {}
    for model in models:
        if model not in available:
            print(f"{model:30} (not listed by the endpoint – skipped)")
            continue
        score, total_lat = 0, 0.0
        for name, prompt, check in TESTS:
            r = run_one(client, model, prompt, check)
            score += r["ok"]
            total_lat += r["latency"]
            print(f"{model:30} {name:8} {'yes' if r['ok'] else 'NO ':4} {r['mode']:11} {r['latency']:6.1f}s  {r['note']}")
        summary[model] = (score, total_lat / len(TESTS))
    print("\nSummary (passed / 3, mean latency):")
    for model, (score, lat) in sorted(summary.items(), key=lambda kv: (-kv[1][0], kv[1][1])):
        print(f"  {model:30} {score}/3  {lat:5.1f}s")
    print("\nPut the best fast model in LLM_MODEL_FAST and the best overall in LLM_MODEL_CODE (.env).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
