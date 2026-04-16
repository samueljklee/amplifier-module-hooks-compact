#!/usr/bin/env python3
"""
hooks-compact A/B session analyzer — comprehensive output.

Compares two Amplifier sessions (A=with hook, B=without) and produces:
  1. Summary table: | Scenario | Input | Output | Savings | With Turns | Without Turns | With Calls | Without Calls | Verdict |
  2. Per-command compression detail
  3. Qualitative notes on model behavior

Usage:
    python3 eval/analyze_ab.py \\
        --scenario git-status-dirty \\
        --session-a <uuid> \\
        --session-b <uuid> \\
        --session-a-dir <path/to/session-a-dir> \\
        --session-b-dir <path/to/session-b-dir> \\
        --telemetry-db ~/.amplifier/hooks-compact/telemetry.db \\
        [--json]

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
    bash_call_details: list[dict] = []
    llm_input_tokens = 0
    llm_output_tokens = 0
    turn_count = 0
    compression_user_messages = 0
    commands_run: list[str] = []

    for event in events:
        event_type = event.get("event") or event.get("type") or ""
        data = event.get("data", event)

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
                    tool_input = data.get("tool_input") or event.get("tool_input") or {}
                    cmd = (
                        tool_input.get("command", "")
                        if isinstance(tool_input, dict)
                        else ""
                    )
                    commands_run.append(cmd)
                    bash_call_details.append(
                        {
                            "command": cmd[:100],
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

        # Count LLM token usage
        if event_type in ("llm:response", "assistant_message", "llm_response"):
            usage = data.get("usage") or event.get("usage") or {}
            if isinstance(usage, dict):
                llm_input_tokens += usage.get("input_tokens", 0) or 0
                llm_output_tokens += usage.get("output_tokens", 0) or 0

        # Count assistant turns
        if event_type in ("assistant_message", "llm:response"):
            turn_count += 1

        # Count compression messages
        if event_type in ("user_message", "hook:user_message"):
            msg_text = (
                data.get("message")
                or event.get("message")
                or event.get("content")
                or ""
            )
            if "bash compressed:" in str(msg_text) or "hooks-compact" in str(msg_text):
                compression_user_messages += 1

    # Session-level token fallback
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
        "commands_run": commands_run,
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
# Qualitative analysis
# ─────────────────────────────────────────────────────────────────────────────


def qualitative_notes(
    m_a: dict, m_b: dict, tel_a: list[dict], scenario: str
) -> list[str]:
    """Generate qualitative notes about model behavior."""
    notes = []
    delta_calls = m_a["bash_calls"] - m_b["bash_calls"]

    if delta_calls > 1:
        notes.append(
            f"⚠️  Model made {delta_calls} extra bash calls vs baseline — "
            "possible retry due to insufficient compressed output"
        )
    elif delta_calls == 0:
        notes.append("✅ Same number of bash calls — compression did not cause retries")
    else:
        notes.append(
            f"✅ Session A made {abs(delta_calls)} FEWER bash calls — "
            "compression may have reduced redundant checks"
        )

    delta_turns = m_a["turn_count"] - m_b["turn_count"]
    if delta_turns > 1:
        notes.append(
            f"⚠️  Model needed {delta_turns} extra turns vs baseline — "
            "may indicate confusion from compressed output"
        )
    elif delta_turns == 0:
        notes.append(
            "✅ Identical turn count — model understood compressed output equally well"
        )
    else:
        notes.append(
            f"✅ {abs(delta_turns)} fewer turns with compression — more efficient"
        )

    if tel_a:
        avg_savings = sum(r["savings_pct"] for r in tel_a) / len(tel_a)
        total_in = sum(r["input_chars"] for r in tel_a)
        total_out = sum(r["output_chars"] for r in tel_a)
        notes.append(
            f"📊 Compression: {total_in:,} → {total_out:,} chars "
            f"({avg_savings:.1f}% avg, {len(tel_a)} event{'s' if len(tel_a) != 1 else ''})"
        )
        # Check for over-compression (very small output)
        very_small = [
            r for r in tel_a if r["output_chars"] < 25 and r["input_chars"] > 200
        ]
        if very_small and delta_calls > 1:
            notes.append(
                f"⚠️  {len(very_small)} compression event(s) produced very small output "
                f"(<25 chars from >{200} chars) — may have stripped too much context"
            )
    else:
        notes.append(
            "ℹ️  No telemetry events — hook may not have fired for this scenario"
        )

    return notes


# ─────────────────────────────────────────────────────────────────────────────
# Verdict logic
# ─────────────────────────────────────────────────────────────────────────────


def compute_verdict(
    m_a: dict,
    m_b: dict,
    tel_a: list[dict],
) -> tuple[str, list[str]]:
    """Compute PASS or FAIL verdict with reasoning."""
    failures = []

    # Tool call regression (primary signal)
    delta_calls = m_a["bash_calls"] - m_b["bash_calls"]
    if delta_calls > 1:
        failures.append(
            f"Session A made {delta_calls} MORE bash calls than Session B "
            f"({m_a['bash_calls']} vs {m_b['bash_calls']}) — "
            "model may be retrying due to compressed output"
        )

    # Turn regression (secondary signal)
    delta_turns = m_a["turn_count"] - m_b["turn_count"]
    if delta_turns > 2:
        failures.append(
            f"Session A needed {delta_turns} MORE turns than Session B "
            f"({m_a['turn_count']} vs {m_b['turn_count']})"
        )

    return ("FAIL" if failures else "PASS"), failures


# ─────────────────────────────────────────────────────────────────────────────
# Table row builder
# ─────────────────────────────────────────────────────────────────────────────


def build_table_row(
    scenario: str,
    m_a: dict,
    m_b: dict,
    tel_a: list[dict],
    verdict: str,
) -> dict:
    """Build the data for one row of the results table."""
    total_in = sum(r["input_chars"] for r in tel_a) if tel_a else 0
    total_out = sum(r["output_chars"] for r in tel_a) if tel_a else 0
    savings_pct = (1 - total_out / total_in) * 100 if total_in > 0 else 0.0

    return {
        "scenario": scenario,
        "input_chars": total_in,
        "output_chars": total_out,
        "savings_pct": savings_pct,
        "with_turns": m_a["turn_count"],
        "without_turns": m_b["turn_count"],
        "with_calls": m_a["bash_calls"],
        "without_calls": m_b["bash_calls"],
        "verdict": verdict,
        "compression_events": len(tel_a),
        "session_a_tokens": m_a["llm_total_tokens"],
        "session_b_tokens": m_b["llm_total_tokens"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pretty printer
# ─────────────────────────────────────────────────────────────────────────────


def print_table_row(row: dict) -> None:
    """Print one row in the results table format."""
    savings_str = f"{row['savings_pct']:.1f}%" if row["input_chars"] > 0 else "—"
    print(
        f"| {row['scenario']:<28} "
        f"| {row['input_chars']:>9,} "
        f"| {row['output_chars']:>10,} "
        f"| {savings_str:>8} "
        f"| {row['with_turns']:>10} "
        f"| {row['without_turns']:>14} "
        f"| {row['with_calls']:>10} "
        f"| {row['without_calls']:>14} "
        f"| {row['verdict']:>7} |"
    )


def print_table_header() -> None:
    """Print the results table header."""
    sep = (
        "| " + "-" * 28 + " "
        "| " + "-" * 9 + " "
        "| " + "-" * 10 + " "
        "| " + "-" * 8 + " "
        "| " + "-" * 10 + " "
        "| " + "-" * 14 + " "
        "| " + "-" * 10 + " "
        "| " + "-" * 14 + " "
        "| " + "-" * 7 + " |"
    )
    print(sep)
    print(
        f"| {'Scenario':<28} "
        f"| {'Input (chars)':>9} "
        f"| {'Output (chars)':>10} "
        f"| {'Savings':>8} "
        f"| {'With Turns':>10} "
        f"| {'Without Turns':>14} "
        f"| {'With Calls':>10} "
        f"| {'Without Calls':>14} "
        f"| {'Verdict':>7} |"
    )
    print(sep)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze hooks-compact A/B sessions")
    parser.add_argument(
        "--scenario", default="unknown", help="Scenario name for display"
    )
    parser.add_argument("--session-a", required=True)
    parser.add_argument("--session-b", required=True)
    parser.add_argument("--session-a-dir", required=True, type=Path)
    parser.add_argument("--session-b-dir", required=True, type=Path)
    parser.add_argument(
        "--telemetry-db",
        default="~/.amplifier/hooks-compact/telemetry.db",
    )
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument(
        "--table-only",
        action="store_true",
        help="Print only the table row (for aggregation)",
    )
    args = parser.parse_args()

    events_a = load_events(args.session_a_dir)
    events_b = load_events(args.session_b_dir)

    if not events_a:
        print(f"ERROR: No events found in {args.session_a_dir}", file=sys.stderr)
        return 1
    if not events_b:
        print(f"ERROR: No events found in {args.session_b_dir}", file=sys.stderr)
        return 1

    m_a = extract_session_metrics(events_a)
    m_b = extract_session_metrics(events_b)
    tel_a = load_telemetry(args.telemetry_db, args.session_a)

    verdict, failures = compute_verdict(m_a, m_b, tel_a)
    row = build_table_row(args.scenario, m_a, m_b, tel_a, verdict)
    notes = qualitative_notes(m_a, m_b, tel_a, args.scenario)

    if args.json:
        result = {
            "scenario": args.scenario,
            "session_a": args.session_a,
            "session_b": args.session_b,
            "verdict": verdict,
            "failures": failures,
            "row": row,
            "notes": notes,
            "metrics_a": m_a,
            "metrics_b": m_b,
            "telemetry": tel_a,
        }
        print(json.dumps(result, indent=2))
        return 0 if verdict == "PASS" else 1

    if args.table_only:
        print_table_row(row)
        return 0 if verdict == "PASS" else 1

    # Full report
    print()
    print("=" * 72)
    print(f"  hooks-compact A/B Analysis: {args.scenario}")
    print("=" * 72)
    print(f"  Session A (WITH hook):  {args.session_a}")
    print(f"  Session B (WITHOUT):    {args.session_b}")
    print()

    # Table
    print_table_header()
    print_table_row(row)
    print()

    # Compression detail
    if tel_a:
        print("  COMPRESSION DETAIL (Session A)")
        print(
            f"  {'Command':<18} {'Filter':<18} {'Input':>8} {'Output':>8} {'Savings':>8}"
        )
        print("  " + "─" * 64)
        for r in tel_a:
            print(
                f"  {r['command'][:18]:<18} {r['filter_used']:<18} "
                f"{r['input_chars']:>8,} {r['output_chars']:>8,} {r['savings_pct']:>7.1f}%"
            )
        total_in = sum(r["input_chars"] for r in tel_a)
        total_out = sum(r["output_chars"] for r in tel_a)
        overall = (1 - total_out / total_in) * 100 if total_in > 0 else 0
        print(
            f"  {'TOTAL':<18} {'':<18} {total_in:>8,} {total_out:>8,} {overall:>7.1f}%"
        )
        print()

    # Bash commands
    print("  BASH COMMANDS")
    print("  Session A (with hook):")
    for i, d in enumerate(m_a["bash_call_details"], 1):
        print(f"    {i}. {d['command'][:70]}  [{d['stdout_chars']:,} chars]")
    print("  Session B (baseline):")
    for i, d in enumerate(m_b["bash_call_details"], 1):
        print(f"    {i}. {d['command'][:70]}  [{d['stdout_chars']:,} chars]")
    print()

    # Token comparison
    if m_a["llm_total_tokens"] > 0 and m_b["llm_total_tokens"] > 0:
        token_delta = (
            (m_a["llm_total_tokens"] - m_b["llm_total_tokens"])
            / m_b["llm_total_tokens"]
            * 100
        )
        print("  TOKEN USAGE")
        print(
            f"  Session A: {m_a['llm_total_tokens']:,} total  (in={m_a['llm_input_tokens']:,}, out={m_a['llm_output_tokens']:,})"
        )
        print(
            f"  Session B: {m_b['llm_total_tokens']:,} total  (in={m_b['llm_input_tokens']:,}, out={m_b['llm_output_tokens']:,})"
        )
        sign = "−" if token_delta < 0 else "+"
        print(f"  Delta: {sign}{abs(token_delta):.1f}%")
        print()

    # Qualitative notes
    print("  QUALITATIVE NOTES")
    for note in notes:
        print(f"  {note}")
    print()

    # Failure details
    if failures:
        print("  FAILURES")
        for f in failures:
            print(f"  ✗ {f}")
        print()

    print("=" * 72)
    print(f"  VERDICT: {verdict}")
    print("=" * 72)
    print()

    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
