import { useEffect, useRef, useState, type JSX } from "react";
import { Box, Text, useApp, useInput } from "ink";
import { RpcClient } from "./rpc-client.js";
import { ChatInput } from "./components/chat-input.js";
import { PermissionDialog, type PermissionRequestData } from "./components/permission.js";

/** One entry in the scrolling chat log. */
type LogEntry =
  | { kind: "user"; text: string }
  | { kind: "assistant"; text: string }
  | { kind: "tool"; text: string }
  | { kind: "error"; text: string }
  | { kind: "system"; text: string };

export type { LogEntry };

interface AppProps {
  /** Exposed for tests / embedding; defaults to "python". */
  command?: string;
  args?: string[];
}

interface EventParams {
  type: string;
  data?: Record<string, unknown>;
}

export function App({ command = "python", args = ["-m", "johnston", "serve"] }: AppProps): JSX.Element {
  const { exit } = useApp();
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [turning, setTurning] = useState(false);
  const [pendingPermission, setPendingPermission] = useState<PermissionRequestData | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const clientRef = useRef<RpcClient | null>(null);
  const sessionRef = useRef<string | null>(null);
  const turningRef = useRef(false);
  const permissionRef = useRef<PermissionRequestData | null>(null);

  const append = (entry: LogEntry) => setLogs((prev) => [...prev, entry]);
  const patchLastAssistant = (patch: (text: string) => string) =>
    setLogs((prev) => {
      const next = [...prev];
      for (let i = next.length - 1; i >= 0; i--) {
        if (next[i].kind === "assistant") {
          next[i] = { ...next[i], text: patch(next[i].text) };
          return next;
        }
      }
      // No assistant message yet: the streamed turn opens with a fresh one.
      next.push({ kind: "assistant", text: patch("") });
      return next;
    });

  // Key bindings: Ctrl+C quits. Unmount runs the cleanup that tells the
  // daemon to persist sessions and shut down.
  useInput((_input, key) => {
    if ((key.ctrl && key.return) || (key.ctrl && key.c)) {
      exit();
    }
  });

  const resolvePermission = (request: PermissionRequestData, allowed: boolean) => {
    if (permissionRef.current !== request) return;
    const client = clientRef.current;
    if (!client) return;
    setPendingPermission(null);
    permissionRef.current = null;
    append({ kind: "system", text: allowed ? "→ allowed" : "→ denied" });
    client
      .call("interaction.resolve", { id: request.id ?? "", allowed })
      .then(() => {})
      .catch((err) => append({ kind: "error", text: `resolve failed: ${String(err)}` }));
  };

  // Spawn the daemon once on mount; tear down on unmount.
  useEffect(() => {
    const client = new RpcClient(command, args);
    clientRef.current = client;
    append({ kind: "system", text: "connecting to daemon…" });

    const unsubscribe = client.onNotification((notification) => {
      if (notification.method !== "event") return;
      const params = notification.params as unknown as EventParams;
      const data = (params.data ?? {}) as Record<string, unknown>;
      switch (params.type) {
        case "content_delta": {
          const text = typeof data.text === "string" ? data.text : "";
          if (data.is_reset === true) {
            patchLastAssistant(() => text);
          } else {
            patchLastAssistant((cur) => cur + text);
          }
          break;
        }
        case "tool_call": {
          const name = String(data.tool_name ?? "?");
          append({ kind: "tool", text: `[running: ${name}]` });
          break;
        }
        case "tool_result": {
          const name = String(data.tool_name ?? "?");
          const content = typeof data.content === "string" ? data.content : JSON.stringify(data.content ?? "");
          append({ kind: "tool", text: `[result: ${name}] ${content}` });
          break;
        }
        case "turn_completed": {
          const text = typeof data.text === "string" ? data.text : "";
          patchLastAssistant(() => text);
          append({ kind: "system", text: "✓ turn completed" });
          setTurning(false);
          turningRef.current = false;
          break;
        }
        case "permission_request": {
          const req: PermissionRequestData = {
            tool_name: String(data.tool_name ?? "?"),
            args: (data.args ?? {}) as Record<string, unknown>,
            risk_level: String(data.risk_level ?? "unknown"),
            reason: String(data.reason ?? ""),
            ...(typeof data.id === "string" ? { id: data.id } : {}),
          };
          append({ kind: "system", text: `⛔ permission requested: ${req.tool_name}` });
          setPendingPermission(req);
          permissionRef.current = req;
          break;
        }
        case "error": {
          append({ kind: "error", text: String(data.message ?? "unknown error") });
          if (data.fatal === true) {
            setTurning(false);
            turningRef.current = false;
          }
          break;
        }
        default:
          // Unknown event types: skip without aborting the turn (§7).
          break;
      }
    });

    // Handshake + session setup.
    (async () => {
      try {
        const info = (await client.call("daemon.info")) as Record<string, unknown>;
        const version = String(info.protocol_version ?? "?");
        append({ kind: "system", text: `daemon.info → protocol ${version} (${String(info.implementation ?? "?")})` });

        const sessions = (await client.call("session.list")) as { sessions?: unknown[] };
        append({ kind: "system", text: `session.list → ${sessions.sessions?.length ?? 0} session(s)` });

        const created = (await client.call("session.create", {})) as { session?: Record<string, unknown> };
        const id = created.session?.id;
        if (typeof id === "string") {
          sessionRef.current = id;
          setSessionId(id);
          append({ kind: "system", text: `session.create → ${id}` });
        } else {
          throw new Error("session.create returned no session.id");
        }
        setConnected(true);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        append({ kind: "error", text: `startup failed: ${message}` });
        setError(message);
      }
    })();

    client.onClose(() => {
      append({ kind: "system", text: "daemon disconnected" });
    });

    return () => {
      unsubscribe();
      if (client && clientRef.current === client) {
        try {
          client.requestShutdown();
        } catch {
          /* already gone */
        }
        clientRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSubmit = (prompt: string) => {
    const client = clientRef.current;
    if (!client || turningRef.current || !sessionRef.current) return;
    append({ kind: "user", text: prompt });
    setTurning(true);
    turningRef.current = true;
    client
      .call("prompt.stream", { prompt, session_id: sessionRef.current })
      .catch((err: unknown) => {
        append({ kind: "error", text: `prompt.stream failed: ${err instanceof Error ? err.message : String(err)}` });
        setTurning(false);
        turningRef.current = false;
      });
  };

  // Ctrl+C quits: handled by App's useInput handler above.

  if (error) {
    return (
      <Box flexDirection="column">
        <Text color="red" bold>
          fatal: {error}
        </Text>
        <Text color="gray">press Ctrl+C to quit</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" minWidth={40}>
      <Box borderStyle="single" borderColor="cyan" paddingX={1}>
        <Text bold color="cyan">
          Johnston
        </Text>
        {sessionId ? <Text color="gray"> · session {sessionId}</Text> : null}
        <Text color={connected ? "green" : "yellow"}> · {connected ? "connected" : "connecting…"}</Text>
      </Box>

      <Box flexDirection="column" minHeight={10} marginY={1}>
        {logs.map((entry, i) => <LogRow key={i} entry={entry} />)}
      </Box>

      {pendingPermission ? (
        <PermissionDialog request={pendingPermission} onResolve={(allowed) => resolvePermission(pendingPermission, allowed)} />
      ) : null}

      <ChatInput disabled={turning || pendingPermission !== null} onSubmit={handleSubmit} />
    </Box>
  );
}

function LogRow({ entry }: { entry: LogEntry }): JSX.Element {
  switch (entry.kind) {
    case "user":
      return (
        <Text color="green" bold>
          you: {entry.text}
        </Text>
      );
    case "assistant":
      return <Text wrap="wrap">{entry.text}</Text>;
    case "tool":
      return <Text color="magenta">{entry.text}</Text>;
    case "error":
      return <Text color="red">{entry.text}</Text>;
    case "system":
      return <Text color="gray">{entry.text}</Text>;
  }
}