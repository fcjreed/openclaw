import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { ErrorCodes, errorShape } from "../protocol/index.js";
import type { GatewayRequestHandlers } from "./types.js";

// ---------------------------------------------------------------------------
// Resolve paths dynamically — look for CC in the skills directory relative
// to the project root, falling back to an absolute path for WSL setups.
// ---------------------------------------------------------------------------
function findCCPaths(): { script: string; db: string } | null {
  const candidates = [
    // Relative to project root (npm global install or git checkout)
    resolve(import.meta.dirname ?? __dirname, "../../../skills/context-commander"),
    // WSL / home directory fallback
    resolve(process.env.HOME ?? "/root", "openclaw/skills/context-commander"),
  ];
  for (const base of candidates) {
    const script = resolve(base, "scripts/cc.py");
    const db = resolve(base, "db/context-commander.db");
    if (existsSync(script)) {
      return { script, db };
    }
  }
  return null;
}

let cachedPaths: { script: string; db: string } | null | undefined;

function getCCPaths(): { script: string; db: string } | null {
  if (cachedPaths === undefined) {
    cachedPaths = findCCPaths();
  }
  return cachedPaths;
}

function findPython(): string {
  // Prefer python3, fall back to python
  for (const candidate of ["/usr/bin/python3", "/usr/local/bin/python3", "python3", "python"]) {
    try {
      if (candidate.startsWith("/") && existsSync(candidate)) {
        return candidate;
      }
    } catch {
      // ignore
    }
  }
  return "python3";
}

function runCC(args: string[]): Promise<Record<string, unknown>> {
  const paths = getCCPaths();
  if (!paths) {
    return Promise.reject(new Error("Context Commander skill not found"));
  }
  const python = findPython();
  return new Promise((resolve, reject) => {
    execFile(
      python,
      [paths.script, "--db", paths.db, "--json", ...args],
      { timeout: 30_000, maxBuffer: 1024 * 1024 },
      (error, stdout, stderr) => {
        if (error) {
          reject(new Error(stderr?.trim() || error.message));
          return;
        }
        try {
          const parsed = JSON.parse(stdout.trim());
          resolve(parsed as Record<string, unknown>);
        } catch {
          reject(new Error(`Failed to parse cc.py output: ${stdout.slice(0, 200)}`));
        }
      },
    );
  });
}

function runCCWithAgent(
  args: string[],
  agentId?: string,
  sessionKey?: string,
): Promise<Record<string, unknown>> {
  const fullArgs = [...args];
  if (agentId) {
    fullArgs.unshift("--agent", agentId);
  }
  if (sessionKey) {
    fullArgs.unshift("--session", sessionKey);
  }
  return runCC(fullArgs);
}

function ccUnavailable(method: string, err: unknown) {
  return errorShape(ErrorCodes.UNAVAILABLE, `${method} failed: ${String(err)}`);
}

export const contextCommanderHandlers: GatewayRequestHandlers = {
  "context-commander.tags": async ({ respond }) => {
    try {
      const result = await runCC(["tags"]);
      respond(true, result, undefined);
    } catch (err) {
      respond(false, undefined, ccUnavailable("context-commander.tags", err));
    }
  },

  "context-commander.query": async ({ params, respond }) => {
    const p = params as {
      tags?: string[];
      minScore?: number;
      limit?: number;
      includeStale?: boolean;
      exact?: boolean;
    };
    if (!p.tags || !Array.isArray(p.tags) || p.tags.length === 0) {
      respond(
        false,
        undefined,
        errorShape(ErrorCodes.INVALID_REQUEST, "context-commander.query requires tags[]"),
      );
      return;
    }
    const args = ["query", "--tags", p.tags.join(",")];
    if (typeof p.minScore === "number") {
      args.push("--min-score", String(p.minScore));
    }
    if (typeof p.limit === "number") {
      args.push("--limit", String(p.limit));
    }
    if (p.includeStale) {
      args.push("--include-stale");
    }
    if (p.exact) {
      args.push("--exact");
    }
    try {
      const result = await runCC(args);
      respond(true, result, undefined);
    } catch (err) {
      respond(false, undefined, ccUnavailable("context-commander.query", err));
    }
  },

  "context-commander.show": async ({ params, respond }) => {
    const p = params as { id?: number };
    if (typeof p.id !== "number") {
      respond(
        false,
        undefined,
        errorShape(ErrorCodes.INVALID_REQUEST, "context-commander.show requires id (number)"),
      );
      return;
    }
    try {
      const result = await runCC(["show", String(p.id)]);
      respond(true, result, undefined);
    } catch (err) {
      respond(false, undefined, ccUnavailable("context-commander.show", err));
    }
  },

  "context-commander.validate": async ({ respond }) => {
    try {
      const result = await runCC(["validate"]);
      respond(true, result, undefined);
    } catch (err) {
      respond(false, undefined, ccUnavailable("context-commander.validate", err));
    }
  },

  "context-commander.prune": async ({ respond }) => {
    try {
      const result = await runCC(["prune", "--stale"]);
      respond(true, result, undefined);
    } catch (err) {
      respond(false, undefined, ccUnavailable("context-commander.prune", err));
    }
  },

  "context-commander.delete": async ({ params, respond }) => {
    const p = params as { id?: number };
    if (typeof p.id !== "number") {
      respond(
        false,
        undefined,
        errorShape(ErrorCodes.INVALID_REQUEST, "context-commander.delete requires id (number)"),
      );
      return;
    }
    try {
      const result = await runCC(["delete", String(p.id)]);
      respond(true, result, undefined);
    } catch (err) {
      respond(false, undefined, ccUnavailable("context-commander.delete", err));
    }
  },

  "context-commander.stats": async ({ respond }) => {
    try {
      const result = await runCC(["stats"]);
      respond(true, result, undefined);
    } catch (err) {
      respond(false, undefined, ccUnavailable("context-commander.stats", err));
    }
  },

  "context-commander.index": async ({ params, respond }) => {
    const p = params as {
      type?: string;
      location?: string;
      range?: string;
      snippet?: string;
      tags?: string;
      score?: number;
      agentId?: string;
      sessionKey?: string;
    };
    if (!p.type || !["file", "web", "snippet"].includes(p.type)) {
      respond(
        false,
        undefined,
        errorShape(
          ErrorCodes.INVALID_REQUEST,
          "context-commander.index requires type (file|web|snippet)",
        ),
      );
      return;
    }
    const args = ["index", "--type", p.type];
    if (p.location) {
      args.push("--location", p.location);
    }
    if (p.range) {
      args.push("--range", p.range);
    }
    if (p.snippet) {
      args.push("--snippet", p.snippet);
    }
    if (p.tags) {
      args.push("--tag", p.tags);
    }
    if (typeof p.score === "number") {
      args.push("--score", String(p.score));
    }
    try {
      const result = await runCCWithAgent(args, p.agentId, p.sessionKey);
      respond(true, result, undefined);
    } catch (err) {
      respond(false, undefined, ccUnavailable("context-commander.index", err));
    }
  },

  "context-commander.log": async ({ params, respond }) => {
    const p = params as {
      operation?: string;
      agentId?: string;
      sessionKey?: string;
      details?: Record<string, unknown>;
    };
    if (!p.operation) {
      respond(
        false,
        undefined,
        errorShape(ErrorCodes.INVALID_REQUEST, "context-commander.log requires operation"),
      );
      return;
    }
    const args = ["log", p.operation];
    if (p.details) {
      args.push("--details", JSON.stringify(p.details));
    }
    try {
      const result = await runCCWithAgent(args, p.agentId, p.sessionKey);
      respond(true, result, undefined);
    } catch (err) {
      respond(false, undefined, ccUnavailable("context-commander.log", err));
    }
  },

  "context-commander.activity": async ({ params, respond }) => {
    const p = params as {
      agentId?: string;
      operation?: string;
      since?: string;
      limit?: number;
    };
    const args = ["activity"];
    if (p.agentId) {
      args.push("--filter-agent", p.agentId);
    }
    if (p.operation) {
      args.push("--filter-op", p.operation);
    }
    if (p.since) {
      args.push("--since", p.since);
    }
    if (typeof p.limit === "number") {
      args.push("--limit", String(p.limit));
    }
    try {
      const result = await runCC(args);
      respond(true, result, undefined);
    } catch (err) {
      respond(false, undefined, ccUnavailable("context-commander.activity", err));
    }
  },

  "context-commander.compliance": async ({ params, respond }) => {
    const p = params as { days?: number };
    const args = ["compliance"];
    if (typeof p.days === "number") {
      args.push("--days", String(p.days));
    }
    try {
      const result = await runCC(args);
      respond(true, result, undefined);
    } catch (err) {
      respond(false, undefined, ccUnavailable("context-commander.compliance", err));
    }
  },
};
