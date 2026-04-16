#!/usr/bin/env python3
"""
hooks-compact session analyzer.

Compares two Amplifier sessions (A=with hook, B=without) and produces
a PASS/FAIL verdict based on compression effectiveness and model behavior.

Usage:
    python3 analyze_sessions.py \
        --session-a <uuid> \
        --session-b <uuid> \
        --session-a-dir <path> \
        --session-b-dir <path> \
        --telemetry-db <path>

Exit codes:
    0 = PASS
    1 = FAIL
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# Events parser
# ─────────────────────────────────────────────────────────────────────────────


def load_events(session_dir: Path) -> list[dict]:
    """Load all events from a session's events.jsonl file."""
    events_file = session_dir / "events.jsonl"
    if not events_file.exists():
        return []
    events = []
    with open(events_file) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return events


def extract_session_metrics(events: list[dict]) -> dict:
    """Extract key metrics from a session's events."""
    bash_calls = 0
    bash_stdout_total = 0
    bash_call_details = []
    llm_input_tokens = 0
    llm_output_tokens = 0
    turn_count = 0
    compression_user_messages = 0

    for event in events:
        event_type = event.get("event") or event.get("type") or ""
        data = event.get("data", event)  # some events are flat

        # Count bash tool calls and their output sizes
        if event_type in ("tool:post", "tool_result"):
            tool_name = data.get("tool_name") or event.get("tool_name") or ""
            if tool_name == "bash":
                bash_calls += 1
                result = data.get("result") or event.get("result") or {}
                output_obj = (
                    result.get("output", {}) if isinstance(result, dict) else {}
                )
                if isinstance(output_obj, dict):
                    stdout = output_obj.get("stdout", "") or ""
                    stdout_chars = len(stdout)
                    bash_stdout_total += stdout_chars
                    # Extract command from tool_input
                    tool_input = data.get("tool_input") or event.get("tool_input") or {}
                    cmd = (
                        tool_input.get("command", "")
                        if isinstance(tool_input, dict)
                        else ""
                    )
                    bash_call_details.append(
                        {
                            "command": cmd[:80],
                            "stdout_chars": stdout_chars,
                            "returncode": output_obj.get("returncode"),
                        }
                    )
                elif isinstance(output_obj, str):
                    bash_stdout_total += len(output_obj)
                    bash_call_details.append(
                        {
                            "command": "",
                            "stdout_chars": len(output_obj),
                            "returncode": None,
                        }
                    )

        # Count LLM token usage from response events
        if event_type in ("llm:response", "assistant_message", "llm_response"):
            usage = data.get("usage") or event.get("usage") or {}
            if isinstance(usage, dict):
                llm_input_tokens += usage.get("input_tokens", 0) or 0
                llm_output_tokens += usage.get("output_tokens", 0) or 0

        # Count assistant turns
        if event_type in ("assistant_message", "llm:response"):
            turn_count += 1

        # Count hooks-compact compression messages
        if event_type in ("user_message", "hook:user_message"):
            msg_text = (
                data.get("message")
                or event.get("message")
                or event.get("content")
                or ""
            )
            if "bash compressed:" in str(msg_text) or "hooks-compact" in str(msg_text):
                compression_user_messages += 1

    # Also look for token usage in session-level events
    for event in events:
        event_type = event.get("event") or event.get("type") or ""
        if event_type in ("session:end", "orchestrator:complete"):
            data = event.get("data", event)
            usage = data.get("usage") or data.get("token_usage") or {}
            if isinstance(usage, dict) and not llm_input_tokens:
                llm_input_tokens += (
                    usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0) or 0
                )
                llm_output_tokens += (
                    usage.get("output_tokens", 0)
                    or usage.get("completion_tokens", 0)
                    or 0
                )

    return {
        "bash_calls": bash_calls,
        "bash_stdout_total_chars": bash_stdout_total,
        "bash_call_details": bash_call_details,
        "llm_input_tokens": llm_input_tokens,
        "llm_output_tokens": llm_output_tokens,
        "llm_total_tokens": llm_input_tokens + llm_output_tokens,
        "turn_count": turn_count,
        "compression_messages": compression_user_messages,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Telemetry reader
# ─────────────────────────────────────────────────────────────────────────────


def load_telemetry(db_path: str, session_id: str) -> list[dict]:
    """Load compression events for a specific session from telemetry.db."""
    path = Path(db_path).expanduser()
    if not path.exists():
        return []
    try:
        conn = sqlite3.connect(str(path))
        cursor = conn.execute(
            """
            SELECT command, filter_used, input_chars, output_chars, savings_pct, exit_code
            FROM compression_log
            WHERE session_id = ?
            ORDER BY id
            """,
            (session_id,),
        )
        rows = []
        for row in cursor.fetchall():
            rows.append(
                {
                    "command": row[0],
                    "filter_used": row[1],
                    "input_chars": row[2],
                    "output_chars": row[3],
                    "savings_pct": row[4],
                    "exit_code": row[5],
                }
            )
        conn.close()
        return rows
    except Exception as e:
        print(f"  [telemetry] Could not read DB: {e}", file=sys.stderr)
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Verdict logic
# ─────────────────────────────────────────────────────────────────────────────


def compute_verdict(
    metrics_a: dict,
    metrics_b: dict,
    telemetry_a: list[dict],
) -> tuple[str, list[str]]:
    """Compute PASS or FAIL verdict with reasoning.

    Returns (verdict, reasons_list).
    """
    reasons = []
    failures = []

    # ── 1. Compression happened (if any bash commands ran) ──────────────────
    if metrics_b["bash_calls"] > 0 and telemetry_a:
        total_in = sum(r["input_chars"] for r in telemetry_a)
        total_out = sum(r["output_chars"] for r in telemetry_a)
        avg_savings = (
            sum(r["savings_pct"] for r in telemetry_a) / len(telemetry_a)
            if telemetry_a
            else 0.0
        )
        reasons.append(
            f"Compression: {total_in:,} → {total_out:,} chars "
            f"({avg_savings:.1f}% avg, {len(telemetry_a)} events)"
        )
    elif metrics_b["bash_calls"] > 0 and not telemetry_a:
        reasons.append(
            "No compression events recorded (hook may not have fired or commands below threshold)"
        )

    # ── 2. Tool call count (key regression signal) ───────────────────────────
    delta_calls = metrics_a["bash_calls"] - metrics_b["bash_calls"]
    if delta_calls > 1:
        failures.append(
            f"Session A made {delta_calls} MORE bash calls than Session B "
            f"({metrics_a['bash_calls']} vs {metrics_b['bash_calls']}) — "
            f"model may be retrying due to compressed output"
        )
    elif delta_calls > 0:
        reasons.append(
            f"Tool calls: A={metrics_a['bash_calls']}, B={metrics_b['bash_calls']} "
            f"(+{delta_calls} in A — within tolerance)"
        )
    else:
        reasons.append(
            f"Tool calls: A={metrics_a['bash_calls']}, B={metrics_b['bash_calls']} "
            f"({'same' if delta_calls == 0 else str(delta_calls)})"
        )

    # ── 3. stdout chars comparison ───────────────────────────────────────────
    if metrics_b["bash_stdout_total_chars"] > 0:
        stdout_reduction_pct = (
            1
            - metrics_a["bash_stdout_total_chars"]
            / metrics_b["bash_stdout_total_chars"]
        ) * 100
        reasons.append(
            f"Stdout chars: A={metrics_a['bash_stdout_total_chars']:,}, "
            f"B={metrics_b['bash_stdout_total_chars']:,} "
            f"({'−' if stdout_reduction_pct > 0 else '+'}{abs(stdout_reduction_pct):.1f}%)"
        )
        if stdout_reduction_pct < 0:
            # Session A had MORE stdout than B — something is wrong
            # (could be hook overhead in edge cases — not a hard failure)
            reasons.append(
                "  ↳ Note: Session A has more stdout chars. "
                "May be due to different model choices or commands."
            )

    # ── 4. Token comparison (informational) ──────────────────────────────────
    if metrics_a["llm_total_tokens"] > 0 and metrics_b["llm_total_tokens"] > 0:
        token_delta_pct = (
            (metrics_a["llm_total_tokens"] - metrics_b["llm_total_tokens"])
            / metrics_b["llm_total_tokens"]
        ) * 100
        reasons.append(
            f"LLM tokens: A={metrics_a['llm_total_tokens']:,}, "
            f"B={metrics_b['llm_total_tokens']:,} "
            f"({'−' if token_delta_pct < 0 else '+'}{abs(token_delta_pct):.1f}%)"
        )
        if token_delta_pct > 10:
            reasons.append(
                f"  ↳ Note: Session A used {token_delta_pct:.1f}% more tokens. "
                "This can happen when the model needs more turns to understand compressed output."
            )

    verdict = "FAIL" if failures else "PASS"
    all_messages = reasons + (["FAILURES:"] + failures if failures else [])
    return verdict, all_messages


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze hooks-compact A/B sessions")
    parser.add_argument("--session-a", required=True)
    parser.add_argument("--session-b", required=True)
    parser.add_argument("--session-a-dir", required=True, type=Path)
    parser.add_argument("--session-b-dir", required=True, type=Path)
    parser.add_argument("--telemetry-db", required=True)
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  hooks-compact A/B Analysis")
    print("=" * 60)
    print(f"  Session A (WITH hook):  {args.session_a}")
    print(f"  Session B (WITHOUT):    {args.session_b}")
    print()

    # Load events
    events_a = load_events(args.session_a_dir)
    events_b = load_events(args.session_b_dir)

    if not events_a:
        print(f"ERROR: No events found in {args.session_a_dir}")
        print("VERDICT: FAIL (no events)")
        return 1
    if not events_b:
        print(f"ERROR: No events found in {args.session_b_dir}")
        print("VERDICT: FAIL (no events)")
        return 1

    # Extract metrics
    m_a = extract_session_metrics(events_a)
    m_b = extract_session_metrics(events_b)

    # Load telemetry
    tel_a = load_telemetry(args.telemetry_db, args.session_a)

    # ── Print metrics table ──
    print("  METRICS COMPARISON")
    print(f"  {'Metric':<35} {'Session A (hook)':>16} {'Session B (base)':>16}")
    print("  " + "─" * 69)
    rows = [
        ("Bash tool calls", m_a["bash_calls"], m_b["bash_calls"]),
        (
            "Bash stdout (chars)",
            m_a["bash_stdout_total_chars"],
            m_b["bash_stdout_total_chars"],
        ),
        ("LLM input tokens", m_a["llm_input_tokens"], m_b["llm_input_tokens"]),
        ("LLM output tokens", m_a["llm_output_tokens"], m_b["llm_output_tokens"]),
        ("LLM total tokens", m_a["llm_total_tokens"], m_b["llm_total_tokens"]),
        ("LLM turns", m_a["turn_count"], m_b["turn_count"]),
        ("Compression events", len(tel_a), 0),
    ]
    for label, val_a, val_b in rows:
        delta = ""
        if isinstance(val_a, int) and isinstance(val_b, int) and val_b > 0:
            pct = (val_a - val_b) / val_b * 100
            delta = f"{'−' if pct < 0 else '+'}{abs(pct):.0f}%"
        print(f"  {label:<35} {val_a:>16,} {val_b:>16,}  {delta}")

    # ── Print telemetry detail ──
    if tel_a:
        print()
        print("  COMPRESSION DETAIL (Session A)")
        print(
            f"  {'Command':<20} {'Filter':<18} {'Input':>8} {'Output':>8} {'Savings':>8}"
        )
        print("  " + "─" * 66)
        for row in tel_a:
            print(
                f"  {row['command'][:20]:<20} {row['filter_used']:<18} "
                f"{row['input_chars']:>8,} {row['output_chars']:>8,} "
                f"{row['savings_pct']:>7.1f}%"
            )
        total_in = sum(r["input_chars"] for r in tel_a)
        total_out = sum(r["output_chars"] for r in tel_a)
        overall_savings = (1 - total_out / total_in) * 100 if total_in > 0 else 0
        print(
            f"  {'TOTAL':<20} {'':<18} {total_in:>8,} {total_out:>8,} {overall_savings:>7.1f}%"
        )

    # ── Print bash call details ──
    if m_a["bash_call_details"] or m_b["bash_call_details"]:
        print()
        print("  BASH COMMANDS (Session A)")
        for i, detail in enumerate(m_a["bash_call_details"], 1):
            print(
                f"  {i}. {detail['command'][:60]}  [{detail['stdout_chars']:,} chars out]"
            )
        if m_b["bash_call_details"]:
            print()
            print("  BASH COMMANDS (Session B)")
            for i, detail in enumerate(m_b["bash_call_details"], 1):
                print(
                    f"  {i}. {detail['command'][:60]}  [{detail['stdout_chars']:,} chars out]"
                )

    # ── Compute verdict ──
    verdict, reasons = compute_verdict(m_a, m_b, tel_a)

    print()
    print("  VERDICT REASONING")
    for reason in reasons:
        print(f"  • {reason}")

    print()
    print("=" * 60)
    print(f"  VERDICT: {verdict}")
    print("=" * 60)
    print()

    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
