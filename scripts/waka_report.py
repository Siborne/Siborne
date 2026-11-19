#!/usr/bin/env python3
"""Build a compact README summary and a detailed WakaTime report."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API_BASE = "https://api.wakatime.com/api/v1"
RANGES = [
    ("last_7_days", "7 days"),
    ("last_30_days", "30 days"),
    ("last_6_months", "6 months"),
    ("last_year", "1 year"),
    ("all_time", "All time"),
]
SUMMARY_START = "<!--START_SECTION:waka-summary-->"
SUMMARY_END = "<!--END_SECTION:waka-summary-->"
README_PATH = Path("README.md")
REPORT_PATH = Path("WAKATIME.md")


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


def model_entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    models = data.get("ai_model_breakdown") or []
    if not models:
        changes = data.get("ai_model_line_changes") or {}
        models = [{"name": name, "lines": lines} for name, lines in changes.items()]
    return models


def top_model_text(data: dict[str, Any]) -> str:
    models = model_entries(data)
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


def format_bar(value: float, width: int = 25) -> str:
    filled = max(0, min(width, int(round(value / 100.0 * width))))
    return "█" * filled + "░" * (width - filled)


def format_items(
    items: list[dict[str, Any]],
    limit: int,
    name_width: int = 24,
) -> str:
    lines = []
    for item in sorted(
        items,
        key=lambda entry: float(entry.get("total_seconds") or 0),
        reverse=True,
    )[:limit]:
        name = str(item.get("name") or "—")[:name_width]
        text = item.get("text") or humanize_seconds(item.get("total_seconds"))
        value = float(item.get("percent") or 0)
        lines.append(
            f"{name:<{name_width}} {text:<20} {format_bar(value)}   {value:>5.2f} %"
        )
    return "\n".join(lines)


def weekly_block(data: dict[str, Any]) -> str:
    parts: list[str] = []
    languages = format_items(data.get("languages") or [], 5)
    if languages:
        parts.extend(["💬 Programming Languages:", languages, ""])
    editors = format_items(data.get("editors") or [], 3)
    if editors:
        parts.extend(["🔥 Editors:", editors, ""])
    systems = format_items(data.get("operating_systems") or [], 2)
    if systems:
        parts.extend(["💻 Operating System:", systems])
    return "\n".join(parts).rstrip() or "No coding activity tracked this week."


def ai_models_block(data: dict[str, Any], limit: int = 5) -> str:
    models = model_entries(data)
    if not models:
        return ""

    total_lines = sum(float(item.get("lines") or 0) for item in models)
    models = sorted(
        models,
        key=lambda item: float(item.get("lines") or 0),
        reverse=True,
    )[:limit]
    lines = []
    for item in models:
        name = str(item.get("name") or "—")[:24]
        count = float(item.get("lines") or 0)
        value = percent(count, total_lines)
        lines.append(
            f"{name:<24} {intcomma(count) + ' lines':<20} {format_bar(value)}   {value:>5.2f} %"
        )
    return "\n".join(lines)


def ai_weekly_block(data: dict[str, Any]) -> str:
    category = find_ai_category(data)
    sessions = data.get("ai_sessions") or 0
    if not category or not sessions:
        return "No AI Coding Activity Tracked This Week"

    ai_additions = data.get("ai_additions") or 0
    human_additions = data.get("human_additions") or 0
    ai_deletions = data.get("ai_deletions") or 0
    human_deletions = data.get("human_deletions") or 0
    ai_written = percent(ai_additions, ai_additions + human_additions)
    manual_touch = percent(
        human_additions + human_deletions,
        ai_additions + ai_deletions + human_additions + human_deletions,
    )
    prompt_length = float(data.get("ai_prompt_length_avg") or 0)
    prompts_per_session = float(data.get("ai_prompt_events_avg_per_session") or 0)

    reliance = (
        "AI-Driven"
        if ai_written >= 66
        else "Balanced with AI"
        if ai_written >= 33
        else "Mostly Hands-On"
    )
    prompt_style = (
        "Verbose Prompter"
        if prompt_length > 1500
        else "Detailed Prompter"
        if prompt_length >= 500
        else "Concise Prompter"
    )
    session_style = (
        "Iterative Prompter" if prompts_per_session > 1.5 else "One-Shot Prompter"
    )
    review_style = (
        "Hands-On Reviewer" if manual_touch >= 50 else "High AI Trust"
    )

    lines = [
        f"⏱ AI Coding Time: {category.get('text', '—')} ({float(category.get('percent') or 0):.2f}%)",
        "",
        f"✍️ {intcomma(ai_additions)} lines written by AI, {intcomma(human_additions)} lines written by hand ({ai_written:.2f}% AI-written)",
        "",
        f"🔤 {intcomma(data.get('ai_input_tokens'))} Input Tokens, {intcomma(data.get('ai_output_tokens'))} Output Tokens",
        "",
        f"💵 ${float(data.get('ai_model_total_cost') or 0):,.2f} Estimated AI Cost This Week",
        "",
        f"🧠 {intcomma(sessions)} AI Sessions, {intcomma(data.get('ai_prompt_events_total'))} AI Prompts",
    ]
    models = ai_models_block(data)
    if models:
        lines.extend(["", models])
    lines.extend(
        [
            "",
            "🔎 AI Coding Insights:",
            f"🤖 {reliance} — {ai_written:.2f}% of written lines came from AI",
            f"📝 {prompt_style} — average {intcomma(round(prompt_length))} characters per prompt",
            f"🔁 {session_style} — average {prompts_per_session:.1f} prompts per session",
            f"🔍 {review_style} — {manual_touch:.2f}% of changed lines were hand-edited",
        ]
    )
    return "\n".join(lines)


def range_tables(stats: dict[str, dict[str, Any]]) -> tuple[str, str]:
    time_rows = []
    ai_rows = []
    for range_name, label in RANGES:
        data = stats[range_name]
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

    time_table = "\n".join(
        [
            "| Range | Total | Daily average | Best day | Days coded |",
            "|---|---|---|---|---|",
            *time_rows,
        ]
    )
    ai_table = "\n".join(
        [
            "| Range | AI time | AI / human written lines | Tokens (in / out) | Est. cost | Sessions / prompts | Top model / tool | Prompt / session style |",
            "|---|---|---|---|---|---|---|---|",
            *ai_rows,
        ]
    )
    return time_table, ai_table


def build_summary(stats: dict[str, dict[str, Any]]) -> str:
    all_data = stats["all_time"]
    code_time = (
        all_data.get("human_readable_total_including_other_language")
        or all_data.get("human_readable_total")
        or "No data"
    )
    ai_category = find_ai_category(all_data)
    ai_code_time = ai_category.get("text") if ai_category else "No data"

    def badge(label: str, value: str) -> str:
        return (
            "https://img.shields.io/badge/"
            f"{urllib.parse.quote(label, safe='')}-"
            f"{urllib.parse.quote(value, safe='')}-blue?style=flat"
        )

    return "\n".join(
        [
            '<p align="center">',
            f'  <img src="{badge("Code Time", code_time)}" alt="Code Time" />',
            f'  <img src="{badge("AI Code Time", ai_code_time)}" alt="AI Code Time" />',
            "</p>",
            "",
            "**📊 This Week I Spent My Time On**",
            "",
            "```text",
            weekly_block(stats["last_7_days"]),
            "```",
            "",
            "[View full WakaTime analytics →](WAKATIME.md)",
        ]
    )


def build_report(stats: dict[str, dict[str, Any]]) -> str:
    all_data = stats["all_time"]
    week = stats["last_7_days"]
    username = all_data.get("username") or week.get("username")
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    links = "[← Back to profile](README.md)"
    if username:
        links += f" · [WakaTime profile](https://wakatime.com/@{username})"
    time_table, ai_table = range_tables(stats)

    return "\n".join(
        [
            "# WakaTime Analytics",
            "",
            links,
            "",
            f"_Last updated: {updated}_",
            "",
            "## Coding Time by Range",
            "",
            time_table,
            "",
            "## AI Coding by Range",
            "",
            ai_table,
            "",
            "## This Week I Spent My Time On",
            "",
            "```text",
            weekly_block(week),
            "```",
            "",
            "## AI Coding This Week",
            "",
            "```text",
            ai_weekly_block(week),
            "```",
            "",
            "> AI model/tool names are reported by WakaTime. Some tools report the editor name when the model is unavailable.",
        ]
    )


def update_readme(readme: str, summary: str) -> str:
    readme = re.sub(
        r"<!--START_SECTION:waka-ranges-->[\s\S]*?<!--END_SECTION:waka-ranges-->\s*",
        "",
        readme,
    )
    readme = re.sub(
        r"<!--START_SECTION:waka-->[\s\S]*?<!--END_SECTION:waka-->\s*",
        "",
        readme,
    )

    block = f"{SUMMARY_START}\n{summary}\n{SUMMARY_END}"
    pattern = re.compile(
        re.escape(SUMMARY_START) + r"[\s\S]*?" + re.escape(SUMMARY_END)
    )
    if pattern.search(readme):
        readme = pattern.sub(lambda _: block, readme, count=1)
    else:
        heading = "### ⏱️ Coding & AI Analytics"
        if heading not in readme:
            raise RuntimeError(f"README heading not found: {heading}")
        readme = readme.replace(heading, f"{heading}\n\n{block}", 1)

    return re.sub(r"\n{3,}", "\n\n", readme)


def main() -> int:
    token = os.environ.get("WAKATIME_API_KEY", "").strip() or None
    user = os.environ.get("WAKATIME_USER", "current").strip() or "current"
    if not token and user == "current":
        raise RuntimeError("WAKATIME_API_KEY is required for users/current.")

    stats: dict[str, dict[str, Any]] = {}
    for range_name, _ in RANGES:
        try:
            stats[range_name] = fetch_stats(user, range_name, token)
        except Exception as error:
            print(f"Failed to load {range_name}: {error}", file=sys.stderr)
            raise

    summary = build_summary(stats)
    report = build_report(stats)

    with README_PATH.open("r", encoding="utf-8", newline="") as handle:
        readme = handle.read()
    newline = "\r\n" if "\r\n" in readme else "\n"
    updated_readme = update_readme(readme, summary.replace("\n", newline))
    with README_PATH.open("w", encoding="utf-8", newline="") as handle:
        handle.write(updated_readme)

    REPORT_PATH.write_text(report + "\n", encoding="utf-8")
    print(f"Updated {README_PATH} and {REPORT_PATH}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
