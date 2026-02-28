/**
 * Agent memory compliance check.
 *
 * Queries the Context Commander activity log to determine whether an agent
 * has been using memory tools recently. Returns a nudge string to inject
 * into the system prompt, or null if the agent is compliant.
 *
 * This is Tier 2 of the enforcement system — soft nudges, not hard gates.
 * Memory writes are NOT required; the nudge is informational.
 */

import { execFile } from "node:child_process";

const CC_PYTHON = "/usr/bin/python3";
const CC_SCRIPT = "/home/finalchrono/openclaw/skills/context-commander/scripts/cc.py";
const CC_DB = "/home/finalchrono/openclaw/skills/context-commander/db/context-commander.db";

export type ComplianceStatus = {
  /** Whether the agent has any recent activity */
  hasActivity: boolean;
  /** Whether the agent has recent read operations */
  hasReads: boolean;
  /** Whether the agent has recent write operations */
  hasWrites: boolean;
  /** Total operations in the period */
  totalOps: number;
  /** Nudge text to inject into the system prompt, or null if compliant */
  nudge: string | null;
};

/**
 * Check an agent's memory compliance over the last N days.
 *
 * Returns a nudge string if the agent should be reminded to use memory,
 * or null if they're doing fine. Designed to be fast and fire-safe —
 * if the check fails for any reason, returns null (no nudge).
 */
export async function checkAgentCompliance(agentId: string, days = 3): Promise<ComplianceStatus> {
  const noNudge: ComplianceStatus = {
    hasActivity: true,
    hasReads: true,
    hasWrites: true,
    totalOps: 0,
    nudge: null,
  };

  try {
    const result = await runComplianceCheck(agentId, days);
    return result;
  } catch {
    // Never let compliance checking break the agent
    return noNudge;
  }
}

function runComplianceCheck(agentId: string, days: number): Promise<ComplianceStatus> {
  return new Promise((resolve) => {
    const args = [CC_SCRIPT, "--db", CC_DB, "--json", "compliance", "--days", String(days)];
    execFile(CC_PYTHON, args, { timeout: 5000, maxBuffer: 256 * 1024 }, (error, stdout) => {
      if (error) {
        resolve({
          hasActivity: true,
          hasReads: true,
          hasWrites: true,
          totalOps: 0,
          nudge: null,
        });
        return;
      }

      try {
        const parsed = JSON.parse(stdout.trim());
        const compliance = parsed?.compliance;
        if (!compliance?.agents) {
          // No data yet — nudge to start using memory
          resolve(buildNudge(agentId, null));
          return;
        }

        const agentData = compliance.agents.find((a: { agent: string }) => a.agent === agentId);
        resolve(buildNudge(agentId, agentData ?? null));
      } catch {
        resolve({
          hasActivity: true,
          hasReads: true,
          hasWrites: true,
          totalOps: 0,
          nudge: null,
        });
      }
    });
  });
}

function buildNudge(
  agentId: string,
  agentData: {
    total_ops: number;
    reads: number;
    writes: number;
    cc_queries: number;
    cc_indexes: number;
    memory_searches: number;
    memory_gets: number;
    memory_writes: number;
  } | null,
): ComplianceStatus {
  // No data at all — agent has never used memory
  if (!agentData || agentData.total_ops === 0) {
    return {
      hasActivity: false,
      hasReads: false,
      hasWrites: false,
      totalOps: 0,
      nudge: [
        `Memory compliance: Agent "${agentId}" has no recent memory activity.`,
        "Before starting work, check memory files (MEMORY.md, memory/*.md) and Context Commander for relevant context.",
        "If you learn anything worth preserving during this session, consider updating memory files or indexing to Context Commander before finishing.",
        "This is a reminder, not a requirement — skip if the information is already indexed or the task is trivial.",
      ].join("\n"),
    };
  }

  const hasReads = agentData.reads > 0 || agentData.cc_queries > 0 || agentData.memory_searches > 0;
  const hasWrites = agentData.writes > 0 || agentData.cc_indexes > 0 || agentData.memory_writes > 0;

  // Good compliance — no nudge needed
  if (hasReads && hasWrites) {
    return {
      hasActivity: true,
      hasReads: true,
      hasWrites: true,
      totalOps: agentData.total_ops,
      nudge: null,
    };
  }

  // Partial compliance — gentle nudge
  const parts: string[] = [];
  if (!hasReads) {
    parts.push(
      "You have not checked memory or Context Commander recently. Before starting work, review memory files and CC for relevant context.",
    );
  }
  if (!hasWrites) {
    parts.push(
      "You have not written to memory recently. If you learn anything worth preserving, consider updating memory files or indexing to Context Commander.",
    );
  }
  parts.push(
    "This is a reminder, not a requirement — skip if the information is already indexed or the task is trivial.",
  );

  return {
    hasActivity: true,
    hasReads,
    hasWrites,
    totalOps: agentData.total_ops,
    nudge: `Memory compliance note for "${agentId}": ${parts.join(" ")}`,
  };
}
