import { spawn, type ChildProcess } from "node:child_process";
import { createInterface, type Interface } from "node:readline";

/**
 * Minimal JSON-RPC 2.0 transport speaking to the Johnston daemon
 * (`python -m johnston serve`) over stdio, one JSON object per line.
 */

export interface RpcErrorData {
  kind?: string;
  [key: string]: unknown;
}

export class RpcError extends Error {
  readonly code: number;
  readonly data: RpcErrorData | undefined;

  constructor(code: number, message: string, data?: RpcErrorData) {
    super(message);
    this.name = "RpcError";
    this.code = code;
    this.data = data ?? {};
  }
}

/** Server → client notification (`{"method":"event","params":{...}}`). */
export interface RpcNotification {
  method: string;
  params: Record<string, unknown>;
}

type NotificationHandler = (notification: RpcNotification) => void;

interface PendingRequest {
  resolve: (result: unknown) => void;
  reject: (error: unknown) => void;
  timer: NodeJS.Timeout;
}

const DEFAULT_TIMEOUT_MS = 120_000;
const LONG_TIMEOUT_MS = 600_000;

/** Spec §1: `prompt.*` and `compact` get the long timeout. */
function timeoutFor(method: string): number {
  return method.startsWith("prompt.") || method === "compact" ? LONG_TIMEOUT_MS : DEFAULT_TIMEOUT_MS;
}

export class RpcClient {
  readonly child: ChildProcess;
  private readonly rl: Interface;
  private nextId = 1;
  private readonly pending = new Map<number, PendingRequest>();
  private readonly notificationHandlers = new Set<NotificationHandler>();
  private onClosed: (() => void) | null = null;
  private closed = false;

  constructor(command = "python", args = ["-m", "johnston", "serve"]) {
    this.child = spawn(command, args, {
      stdio: ["pipe", "pipe", "pipe"],
    });

    const stdout = this.child.stdout;
    if (!stdout) {
      throw new Error("daemon stdout unavailable");
    }
    this.rl = createInterface({ input: stdout, crlfDelay: Infinity });
    this.rl.on("line", (line) => this.handleLine(line));
    this.rl.on("error", (err) => {
      console.error(`[rpc-client] stdout read error: ${String(err)}`);
    });

    this.child.stderr?.on("data", (chunk: Buffer) => {
      process.stderr.write(chunk);
    });

    this.child.on("error", (err) => {
      console.error(`[rpc-client] spawn error: ${String(err)}`);
      this.close();
    });

    this.child.on("exit", (code, signal) => {
      if (!this.closed) {
        process.stderr.write(
          `[rpc-client] daemon exited (code=${code}, signal=${signal ?? "none"})\n`,
        );
      }
      this.close();
    });
  }

  /** Subscribe to server notifications (e.g. `event`). Returns an unsubscribe fn. */
  onNotification(handler: NotificationHandler): () => void {
    this.notificationHandlers.add(handler);
    return () => this.notificationHandlers.delete(handler);
  }

  /** Invoked once when the transport disconnects (EOF / process exit). */
  onClose(handler: () => void): () => void {
    this.onClosed = handler;
    return () => {
      if (this.onClosed === handler) this.onClosed = null;
    };
  }

  /** Send a request and await its response. Rejects after the spec timeout. */
  call(method: string, params?: Record<string, unknown>, timeoutMs = timeoutFor(method)): Promise<unknown> {
    if (this.closed) {
      return Promise.reject(new Error(`daemon not running; cannot call "${method}"`));
    }
    const id = this.nextId++;
    const request = { jsonrpc: "2.0", id, method, ...(params ? { params } : {}) };

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        // Spec §1: daemon is wedged — never re-send; close stdin, kill the process.
        process.stderr.write(
          `[rpc-client] timeout after ${(timeoutMs / 1000).toFixed(0)}s for "${method}" (id ${id}); treating daemon as wedged\n`,
        );
        try {
          this.child.stdin?.end();
          this.child.kill();
        } catch {
          /* process already gone */
        }
        reject(
          new Error(
            `timeout after ${(timeoutMs / 1000).toFixed(0)}s waiting for response to "${method}" (id ${id}); daemon was wedged and has been shut down`,
          ),
        );
      }, timeoutMs);

      this.pending.set(id, { resolve, reject, timer });
      this.write(request);
    });
  }

  /** Send a notification (no id, no response expected). */
  notify(method: string, params?: Record<string, unknown>): void {
    if (this.closed) return;
    const message = { jsonrpc: "2.0", method, ...(params ? { params } : {}) };
    this.write(message);
  }

  /** Suggest closing stdin so the daemon persists sessions and exits cleanly. */
  requestShutdown(): void {
    this.notify("daemon.shutdown");
    this.child.stdin?.end();
  }

  private write(message: unknown): void {
    const stdin = this.child.stdin;
    if (this.closed || !stdin || !stdin.writable) {
      process.stderr.write(`[rpc-client] dropping message, stdin not writable: ${JSON.stringify(message)}\n`);
      return;
    }
    stdin.write(`${JSON.stringify(message)}\n`);
  }

  private handleLine(line: string): void {
    if (line.trim() === "") return;
    let msg: unknown;
    try {
      msg = JSON.parse(line);
    } catch (err) {
      process.stderr.write(`[rpc-client] parse error, skipping line: ${String(err)}\n`);
      return;
    }
    if (typeof msg !== "object" || msg === null) {
      process.stderr.write("[rpc-client] ignoring non-object message\n");
      return;
    }
    const envelope = msg as { id?: unknown; method?: unknown; result?: unknown; error?: unknown };
    if (envelope.id === undefined || envelope.id === null) {
      this.dispatchNotification(envelope);
      return;
    }
    this.resolveResponse(envelope);
  }

  private dispatchNotification(envelope: { method?: unknown; params?: unknown }): void {
    if (typeof envelope.method !== "string") {
      process.stderr.write("[rpc-client] notification without a method, skipping\n");
      return;
    }
    const notification: RpcNotification = {
      method: envelope.method,
      params: (envelope.params ?? {}) as Record<string, unknown>,
    };
    for (const handler of this.notificationHandlers) {
      try {
        handler(notification);
      } catch (err) {
        process.stderr.write(`[rpc-client] notification handler error: ${String(err)}\n`);
      }
    }
  }

  private resolveResponse(envelope: { id?: unknown; result?: unknown; error?: unknown }): void {
    if (typeof envelope.id !== "number") {
      process.stderr.write(`[rpc-client] response with non-numeric id "${String(envelope.id)}", skipping\n`);
      return;
    }
    const pending = this.pending.get(envelope.id);
    if (!pending) {
      process.stderr.write(`[rpc-client] response for unknown id ${envelope.id}, skipping\n`);
      return;
    }
    this.pending.delete(envelope.id);
    clearTimeout(pending.timer);

    if (envelope.error !== undefined && envelope.error !== null) {
      const errObj = envelope.error as { code?: unknown; message?: unknown; data?: unknown };
      pending.reject(
        new RpcError(
          typeof errObj.code === "number" ? errObj.code : -32603,
          typeof errObj.message === "string" ? errObj.message : "RPC error",
          typeof errObj.data === "object" && errObj.data !== null
            ? (errObj.data as RpcErrorData)
            : {},
        ),
      );
      return;
    }
    pending.resolve(envelope.result);
  }

  private close(): void {
    if (this.closed) return;
    this.closed = true;
    for (const [id, pending] of this.pending) {
      clearTimeout(pending.timer);
      pending.reject(new Error(`daemon disconnected; in-flight request ${id} aborted`));
    }
    this.pending.clear();
    this.rl.close();
    this.onClosed?.();
  }
}