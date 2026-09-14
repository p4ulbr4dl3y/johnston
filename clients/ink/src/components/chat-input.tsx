import { useEffect, useState, type JSX } from "react";
import { useInput } from "ink";

interface ChatInputProps {
  disabled?: boolean;
  onSubmit: (value: string) => void;
}

/**
 * Single-line prompt. Enter submits, Ctrl+C is handled by the App level
 * (useInput is additive; both handlers see every keystroke).
 */
export function ChatInput({ disabled = false, onSubmit }: ChatInputProps): JSX.Element {
  const [value, setValue] = useState("");

  useInput((input, key) => {
    if (disabled) return;
    if (key.ctrl) return; // Ctrl+C handled at App level
    if (key.return) {
      const text = value.trim();
      if (text === "") return;
      onSubmit(text);
      setValue("");
      return;
    }
    if (key.backspace || key.delete) {
      setValue((v) => v.slice(0, -1));
      return;
    }
    if (input.length > 0) {
      setValue((v) => v + input);
    }
  });

  useEffect(() => {
    if (disabled) setValue("");
  }, [disabled]);

  return (
    <text color="green">
      {"> "}({value}
      <text color="gray">▌</text>)
    </text>
  );
}