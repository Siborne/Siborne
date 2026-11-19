#!/usr/bin/env python3
"""Generate WakaTime time-range analysis tables for README.md."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API_BASE = "https://api.wakatime.com/api/v1"
DEFAULT_RANGES = [
    ("last_7_days", "7 days"),
    ("last_30_days", "30 days"),
    ("last_6_months", "6 months"),
    ("last_year", "1 year"),
    ("all_time", "All time"),
]
START_MARKER = "<!--START_SECTION:waka-ranges-->"
END_MARKER = "<!--END_SECTION:waka-ranges-->"
README_PATH = Path("README.md")


def api_get(url: str, token: str | None) -> dict[str, Any]:
    headers = {
        "Accept": "application/json",
        "User-Agent": "Siborne-profile-readme",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {error.code} for {url}: {body}") from error


def fetch_stats(user: str, range_name: str, token: str | None) -> dict[str, Any]:
    url = f"{API_BASE}/users/{user}/stats/{range_name}"
    for attempt in range(5):
        payload = api_get(url, token).get("data", {})
        if payload.get("is_up_to_date") is not False:
            return payload
        time.sleep(3 * (attempt + 1))
    return payload


def intcomma(value: Any) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "—"


def percent(part: Any, whole: Any) -> float:
    try:
        whole_value = float(whole)
        return float(part) / whole_value * 100.0 if whole_value else 0.0
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def humanize_seconds(value: Any) -> str:
    try:
        seconds = max(0, int(round(float(value))))
    except (TypeError, ValueError):
        return "—"
    if not seconds:
        return "0 secs"
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours} hrs {minutes} mins"
    if minutes:
        return f"{minutes} mins"
    return f"{secs} secs"


def find_ai_category(data: dict[str, Any]) -> dict[str, Any] | None:
    for category in data.get("categories") or []:
        if str(category.get("name", "")).strip().lower() == "ai coding":
            return category
    return None


def ai_time_text(data: dict[str, Any]) -> str:
    category = find_ai_category(data)
    if category:
        text = category.get("text") or humanize_seconds(category.get("total_seconds"))
        value = category.get("percent")
        if isinstance(value, (int, float)):
            return f"{text} ({value:.1f}%)"
        return text

    ai_seconds = sum(
        float(editor.get("ai_coding_seconds") or 0)
        for editor in (data.get("editors") or [])
    )
    if ai_seconds:
        return f"{humanize_seconds(ai_seconds)} ({percent(ai_seconds, data.get('total_seconds')):.1f}%)"
    return "—"


def ai_lines_text(data: dict[str, Any]) -> str:
    ai_additions = data.get("ai_additions") or 0
    human_additions = data.get("human_additions") or 0
    if not ai_additions and not human_additions:
        return "—"
    return (
        f"{intcomma(ai_additions)} / {intcomma(human_additions)} "
        f"({percent(ai_additions, ai_additions + human_additions):.1f}% AI)"
    )


def token_text(data: dict[str, Any]) -> str:
    tokens_in = data.get("ai_input_tokens") or 0
    tokens_out = data.get("ai_output_tokens") or 0
    if not tokens_in and not tokens_out:
        return "—"
    return f"{intcomma(tokens_in)} / {intcomma(tokens_out)}"


def cost_text(data: dict[str, Any]) -> str:
    cost = data.get("ai_model_total_cost") or 0
    if not cost:
        return "—"
    return f"${float(cost):,.2f}"


def session_text(data: dict[str, Any]) -> str:
    sessions = data.get("ai_sessions") or 0
    prompts = data.get("ai_prompt_events_total") or 0
    if not sessions and not prompts:
        return "—"
    return f"{intcomma(sessions)} / {intcomma(prompts)}"


def top_model_text(data: dict[str, Any]) -> str:
    models = data.get("ai_model_breakdown") or []
    if not models:
        changes = data.get("ai_model_line_changes") or {}
        models = [{"name": name, "lines": lines} for name, lines in changes.items()]
    if not models:
        return "—"

    models = sorted(
        models,
        key=lambda item: float(item.get("lines") or 0),
        reverse=True,
    )
    total_lines = sum(float(item.get("lines") or 0) for item in models)
    top = models[0]
    share = percent(top.get("lines"), total_lines)
    return f"{top.get('name', '—')} ({share:.1f}%)"


def prompt_style_text(data: dict[str, Any]) -> str:
    length = data.get("ai_prompt_length_avg") or 0
    if not length:
        return "—"
    if length > 1500:
        style = "Verbose"
    elif length >= 500:
        style = "Detailed"
    else:
        style = "Concise"

    prompts_per_session = data.get("ai_prompt_events_avg_per_session") or 0
    if prompts_per_session:
        session_style = "Iterative" if prompts_per_session > 1.5 else "One-Shot"
        return f"{style} / {session_style}"
    return style


def best_day_text(data: dict[str, Any]) -> str:
    best_day = data.get("best_day") or {}
    text = best_day.get("text")
    if not text:
        return "—"
    date = best_day.get("date")
    return f"{date} · {text}" if date else text


def build_section(rows: list[tuple[str, dict[str, Any]]]) -> str:
    time_rows = []
    ai_rows = []

    for label, data in rows:
        total = (
            data.get("human_readable_total_including_other_language")
            or data.get("human_readable_total")
            or "—"
        )
        daily = (
            data.get("human_readable_daily_average_including_other_language")
            or data.get("human_readable_daily_average")
            or "—"
        )
        days = data.get("days_minus_holidays")
        total_days = data.get("days_including_holidays")
        if days is None:
            days_text = "—"
        elif total_days is None:
            days_text = intcomma(days)
        else:
            days_text = f"{intcomma(days)} / {intcomma(total_days)}"

        time_rows.append(
            f"| {label} | {total} | {daily} | {best_day_text(data)} | {days_text} |"
        )
        ai_rows.append(
            "| {label} | {ai_time} | {lines} | {tokens} | {cost} | {sessions} | {model} | {style} |".format(
                label=label,
                ai_time=ai_time_text(data),
                lines=ai_lines_text(data),
                tokens=token_text(data),
                cost=cost_text(data),
                sessions=session_text(data),
                model=top_model_text(data),
                style=prompt_style_text(data),
            )
        )

    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return "\n".join(
        [
            "**⏱️ Coding Time by Range**",
            "",
            "| Range | Total | Daily average | Best day | Days coded |",
            "|---|---|---|---|---|",
            *time_rows,
            "",
            "**🤖 AI Coding by Range**",
            "",
            "| Range | AI time | AI / human written lines | Tokens (in / out) | Est. cost | Sessions / prompts | Top model | Prompt / session style |",
            "|---|---|---|---|---|---|---|---|",
            *ai_rows,
            "",
            f"_Last updated: {updated}_",
        ]
    )


def replace_section(readme: str, section: str) -> str:
    pattern = re.compile(
        re.escape(START_MARKER) + r"[\s\S]*?" + re.escape(END_MARKER)
    )
    if not pattern.search(readme):
        raise RuntimeError(
            f"README markers not found. Add {START_MARKER} and {END_MARKER}."
        )
    replacement = f"{START_MARKER}\n{section}\n{END_MARKER}"
    return pattern.sub(lambda _: replacement, readme, count=1)


def main() -> int:
    token = os.environ.get("WAKATIME_API_KEY", "").strip() or None
    user = os.environ.get("WAKATIME_USER", "current").strip() or "current"
    requested = {
        item.strip()
        for item in os.environ.get("WAKATIME_RANGES", "").split(",")
        if item.strip()
    }
    ranges = [item for item in DEFAULT_RANGES if not requested or item[0] in requested]

    if not token and user == "current":
        raise RuntimeError("WAKATIME_API_KEY is required for users/current.")

    rows: list[tuple[str, dict[str, Any]]] = []
    for range_name, label in ranges:
        try:
            rows.append((label, fetch_stats(user, range_name, token)))
        except Exception as error:
            print(f"Failed to load {range_name}: {error}", file=sys.stderr)
            raise

    with README_PATH.open("r", encoding="utf-8", newline="") as handle:
        readme = handle.read()
    newline = "\r\n" if "\r\n" in readme else "\n"
    section = build_section(rows).replace("\n", newline)
    updated = replace_section(readme, section)

    with README_PATH.open("w", encoding="utf-8", newline="") as handle:
        handle.write(updated)

    print(f"Updated {README_PATH} with {len(rows)} range(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
