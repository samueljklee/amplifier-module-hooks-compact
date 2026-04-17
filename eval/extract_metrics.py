#!/usr/bin/env python3
"""Extract key metrics from an Amplifier events.jsonl file."""
import json
import sys

def extract_metrics(events_path):
    metrics = {
        "session_id": None,
        "turns": 0,
        "bash_calls": 0,
        "total_tool_calls": 0,
        "total_stdout_chars": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "bash_outputs": [],
        "errors": [],
    }
    
    with open(events_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            
            event_type = event.get("event", "")
            data = event.get("data", {})
            session_id = event.get("session_id")
            if session_id and not metrics["session_id"]:
                metrics["session_id"] = session_id[:8]
            
            # LLM turns
            if event_type in ("llm:response", "llm:complete", "orchestrator:turn"):
                metrics["turns"] += 1
                usage = data.get("usage", {})
                metrics["total_input_tokens"] += usage.get("input_tokens", 0)
                metrics["total_output_tokens"] += usage.get("output_tokens", 0)
            
            # Tool calls
            if event_type == "tool:post":
                metrics["total_tool_calls"] += 1
                tool_name = data.get("tool_name", "")
                
                if tool_name == "bash":
                    metrics["bash_calls"] += 1
                    result = data.get("result", {})
                    output = result.get("output", {}) if isinstance(result, dict) else {}
                    stdout = output.get("stdout", "") if isinstance(output, dict) else ""
                    stdout_len = len(stdout) if isinstance(stdout, str) else 0
                    metrics["total_stdout_chars"] += stdout_len
                    
                    tool_input = data.get("tool_input", {})
                    cmd = tool_input.get("command", "???") if isinstance(tool_input, dict) else "???"
                    metrics["bash_outputs"].append((cmd[:80], stdout_len))
            
            if event_type == "tool:error":
                metrics["errors"].append(data.get("error", "unknown"))
    
    return metrics

def main():
    if len(sys.argv) < 2:
        print("Usage: extract_metrics.py <events_a.jsonl> [<events_b.jsonl>]")
        sys.exit(1)
    
    metrics_a = extract_metrics(sys.argv[1])
    print(f"=== Session A (WITH hook): {metrics_a['session_id']} ===")
    print(f"  Turns:            {metrics_a['turns']}")
    print(f"  Bash calls:       {metrics_a['bash_calls']}")
    print(f"  Total tool calls: {metrics_a['total_tool_calls']}")
    print(f"  Total stdout:     {metrics_a['total_stdout_chars']} chars")
    print(f"  Input tokens:     {metrics_a['total_input_tokens']}")
    print(f"  Output tokens:    {metrics_a['total_output_tokens']}")
    if metrics_a['bash_outputs']:
        print(f"  Bash commands:")
        for cmd, chars in metrics_a['bash_outputs']:
            print(f"    [{chars:>6} chars] {cmd}")
    
    if len(sys.argv) >= 3:
        metrics_b = extract_metrics(sys.argv[2])
        print(f"\n=== Session B (WITHOUT hook): {metrics_b['session_id']} ===")
        print(f"  Turns:            {metrics_b['turns']}")
        print(f"  Bash calls:       {metrics_b['bash_calls']}")
        print(f"  Total tool calls: {metrics_b['total_tool_calls']}")
        print(f"  Total stdout:     {metrics_b['total_stdout_chars']} chars")
        print(f"  Input tokens:     {metrics_b['total_input_tokens']}")
        print(f"  Output tokens:    {metrics_b['total_output_tokens']}")
        if metrics_b['bash_outputs']:
            print(f"  Bash commands:")
            for cmd, chars in metrics_b['bash_outputs']:
                print(f"    [{chars:>6} chars] {cmd}")
        
        print(f"\n=== COMPARISON ===")
        a_turns = metrics_a['turns']
        b_turns = metrics_b['turns']
        a_calls = metrics_a['bash_calls']
        b_calls = metrics_b['bash_calls']
        a_stdout = metrics_a['total_stdout_chars']
        b_stdout = metrics_b['total_stdout_chars']
        
        stdout_savings = ((b_stdout - a_stdout) / b_stdout * 100) if b_stdout > 0 else 0
        
        print(f"  Turns:        A={a_turns}, B={b_turns} (delta={a_turns-b_turns})")
        print(f"  Bash calls:   A={a_calls}, B={b_calls} (delta={a_calls-b_calls})")
        print(f"  Stdout chars: A={a_stdout}, B={b_stdout} (savings={stdout_savings:.1f}%)")
        
        if a_calls <= b_calls + 1 and a_turns <= b_turns + 1:
            print(f"  VERDICT: PASS")
        else:
            print(f"  VERDICT: FAIL (model regression - more turns/calls needed)")

if __name__ == "__main__":
    main()
