import { execFile } from "node:child_process";
import { ErrorCodes, errorShape } from "../protocol/index.js";
import type { GatewayRequestHandlers } from "./types.js";

const PYTHON_PATH = "C:\\Python314\\python.exe";
const CC_SCRIPT = "S:\\AIStuff\\claudeworkspace\\skills\\context-commander\\scripts\\cc.py";
const CC_DB = "S:\\AIStuff\\claudeworkspace\\skills\\context-commander\\db\\context-commander.db";

function runCC(args: string[]): Promise<{ ok: boolean; data: unknown }> {
  return new Promise((resolve, reject) => {
    execFile(
      PYTHON_PATH,
      [CC_SCRIPT, "--db", CC_DB, "--json", ...args],
      { timeout: 30_000, maxBuffer: 1024 * 1024 },
      (error, stdout, stderr) => {
        if (error) {
          reject(new Error(stderr?.trim() || error.message));
          return;
        }
        try {
          const parsed = JSON.parse(stdout.trim());
          resolve(parsed);
        } catch {
          reject(new Error(`Failed to parse cc.py output: ${stdout.slice(0, 200)}`));
        }
      },
    );
  });
}

export const contextCommanderHandlers: GatewayRequestHandlers = {
  "context-commander.tags": async ({ respond }) => {
    try {
      const result = await runCC(["tags"]);
      respond(true, result, undefined);
    } catch (err) {
      respond(
        false,
        undefined,
        errorShape(ErrorCodes.UNAVAILABLE, `context-commander.tags failed: ${String(err)}`),
      );
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
      respond(
        false,
        undefined,
        errorShape(ErrorCodes.UNAVAILABLE, `context-commander.query failed: ${String(err)}`),
      );
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
      respond(
        false,
        undefined,
        errorShape(ErrorCodes.UNAVAILABLE, `context-commander.show failed: ${String(err)}`),
      );
    }
  },

  "context-commander.validate": async ({ respond }) => {
    try {
      const result = await runCC(["validate"]);
      respond(true, result, undefined);
    } catch (err) {
      respond(
        false,
        undefined,
        errorShape(ErrorCodes.UNAVAILABLE, `context-commander.validate failed: ${String(err)}`),
      );
    }
  },

  "context-commander.prune": async ({ respond }) => {
    try {
      const result = await runCC(["prune", "--stale"]);
      respond(true, result, undefined);
    } catch (err) {
      respond(
        false,
        undefined,
        errorShape(ErrorCodes.UNAVAILABLE, `context-commander.prune failed: ${String(err)}`),
      );
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
      respond(
        false,
        undefined,
        errorShape(ErrorCodes.UNAVAILABLE, `context-commander.delete failed: ${String(err)}`),
      );
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
      const result = await runCC(args);
      respond(true, result, undefined);
    } catch (err) {
      respond(
        false,
        undefined,
        errorShape(ErrorCodes.UNAVAILABLE, `context-commander.index failed: ${String(err)}`),
      );
    }
  },
};
