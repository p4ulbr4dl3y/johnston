#!/usr/bin/env python3
"""Script to inspect/debug the main agent's full composite system prompt."""

import os
import sys

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.prompt_builder import DEFAULT_SYSTEM_PROMPT, PromptBuilder


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "action"
    model_name = sys.argv[2] if len(sys.argv) > 2 else "claude-3-5-sonnet"

    builder = PromptBuilder(
        base_system_prompt=DEFAULT_SYSTEM_PROMPT,
        base_tools=[],
        mode=mode,
        model_name=model_name,
    )
    prompt = builder.build_system_prompt()

    print("=" * 80)
    print(f" MAIN AGENT SYSTEM PROMPT (mode='{mode}', model='{model_name}')")
    print("=" * 80)
    print(prompt)
    print("=" * 80)
    print(f"Total length: {len(prompt)} characters (~{len(prompt) // 4} tokens)")
    print("=" * 80)


if __name__ == "__main__":
    main()
