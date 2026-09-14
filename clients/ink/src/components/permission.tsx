import { useState, type JSX } from "react";
import { useInput, Box, Text } from "ink";

export interface PermissionRequestData {
  tool_name: string;
  args: Record<string, unknown>;
  risk_level: string;
  reason: string;
  id?: string;
}

interface PermissionDialogProps {
  request: PermissionRequestData;
  onResolve: (allowed: boolean) => void;
}

/**
 * Inline permission dialog. y/Enter = allow, n = deny.
 * The dialog is already mounted when the decision is rendered, so a
 * follow-up keypress just re-emits the same decision (idempotent).
 */
export function PermissionDialog({ request, onResolve }: PermissionDialogProps): JSX.Element {
  const [resolved, setResolved] = useState(false);

  useInput((_input, key) => {
    if (resolved) return;
    if (key.return) {
      setResolved(true);
      onResolve(true);
    }
  });

  useInput((input) => {
    if (resolved) return;
    const ch = input.toLowerCase();
    if (ch === "y") {
      setResolved(true);
      onResolve(true);
    } else if (ch === "n") {
      setResolved(true);
      onResolve(false);
    }
  });

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="yellow" paddingX={1}>
      <Text color="yellow" bold>
        ⚠ Permission requested
      </Text>
      <Text>
        <Text color="cyan">tool:</Text> {request.tool_name}
      </Text>
      <Text wrap="wrap">
        <Text color="cyan">args:</Text> {JSON.stringify(request.args)}
      </Text>
      <Text>
        <Text color="cyan">risk:</Text> {request.risk_level}
      </Text>
      <Text wrap="wrap">
        <Text color="cyan">reason:</Text> {request.reason}
      </Text>
      <Text color="yellow">Allow? [y]es / [n]o — </Text>
    </Box>
  );
}