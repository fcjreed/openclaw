import type { GatewayBrowserClient } from "../gateway.ts";

export type CCTag = {
  name: string;
  ref_count: number;
};

export type CCRefTag = {
  name: string;
  score: number;
};

export type CCRef = {
  id: number;
  type: string;
  location: string | null;
  range_start: number | null;
  range_end: number | null;
  fingerprint: string | null;
  snippet: string | null;
  stale: boolean;
  created_at: string | null;
  last_validated: string | null;
  tags: CCRefTag[];
};

export type CCScoreDistribution = {
  low: number;
  medium: number;
  good: number;
  high: number;
  critical: number;
};

export type CCTopTag = {
  name: string;
  ref_count: number;
};

export type CCRecentActivity = {
  day: string;
  count: number;
};

export type CCStats = {
  total_refs: number;
  refs_by_type: Record<string, number>;
  total_tags: number;
  total_tag_assignments: number;
  orphan_tags: number;
  stale_count: number;
  fresh_count: number;
  avg_score: number | null;
  min_score: number | null;
  max_score: number | null;
  score_distribution: CCScoreDistribution;
  oldest_ref: string | null;
  newest_ref: string | null;
  top_tags: CCTopTag[];
  recent_activity: CCRecentActivity[];
  db_size_bytes: number | null;
};

export type CCActivityEntry = {
  id: number;
  operation: string;
  agent_id: string | null;
  session_key: string | null;
  details: Record<string, unknown> | null;
  created_at: string;
};

export type CCAgentCompliance = {
  agent: string;
  total_ops: number;
  reads: number;
  writes: number;
  cc_queries: number;
  cc_indexes: number;
  memory_searches: number;
  memory_gets: number;
  memory_writes: number;
  last_active: string | null;
};

export type CCComplianceData = {
  agents: CCAgentCompliance[];
  period_days: number;
  total_operations: number;
  timeline: { day: string; agent: string; count: number }[];
};

export type CCState = {
  client: GatewayBrowserClient | null;
  connected: boolean;
  ccLoading: boolean;
  ccTags: CCTag[];
  ccRefs: CCRef[];
  ccError: string | null;
  ccSelectedRefId?: number | null;
  ccQueryTags: string;
  ccQueryMinScore: string;
  ccQueryExact: boolean;
  ccValidateResult: string | null;
  ccStats: CCStats | null;
  ccActivity: CCActivityEntry[];
  ccActivityLoading: boolean;
  ccCompliance: CCComplianceData | null;
  ccComplianceLoading: boolean;
  ccComplianceDays: number;
};

export async function loadCCStats(state: CCState) {
  if (!state.client || !state.connected) {
    return;
  }
  try {
    const res = await state.client.request<{ ok?: boolean; stats?: CCStats }>(
      "context-commander.stats",
      {},
    );
    state.ccStats = res.stats ?? null;
  } catch {
    // Stats are non-critical; don't surface errors
    state.ccStats = null;
  }
}

export async function loadCCTags(state: CCState) {
  if (!state.client || !state.connected) {
    return;
  }
  if (state.ccLoading) {
    return;
  }
  state.ccLoading = true;
  state.ccError = null;
  try {
    const res = await state.client.request<{ ok?: boolean; tags?: CCTag[] }>(
      "context-commander.tags",
      {},
    );
    state.ccTags = Array.isArray(res.tags) ? res.tags : [];
  } catch (err) {
    state.ccError = String(err);
  } finally {
    state.ccLoading = false;
  }
}

export async function queryCCRefs(state: CCState) {
  if (!state.client || !state.connected) {
    return;
  }
  const tags = state.ccQueryTags
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
  if (tags.length === 0) {
    state.ccError = "Enter at least one tag to query.";
    return;
  }
  state.ccLoading = true;
  state.ccError = null;
  try {
    const minScore = parseFloat(state.ccQueryMinScore) || 0;
    const res = await state.client.request<{ ok?: boolean; refs?: CCRef[] }>(
      "context-commander.query",
      {
        tags,
        minScore,
        limit: 50,
        includeStale: true,
        exact: state.ccQueryExact,
      },
    );
    state.ccRefs = Array.isArray(res.refs) ? res.refs : [];
  } catch (err) {
    state.ccError = String(err);
  } finally {
    state.ccLoading = false;
  }
}

export async function validateCC(state: CCState) {
  if (!state.client || !state.connected) {
    return;
  }
  state.ccLoading = true;
  state.ccError = null;
  state.ccValidateResult = null;
  try {
    const res = await state.client.request<{
      ok?: boolean;
      total?: number;
      fresh?: number;
      stale?: number;
    }>("context-commander.validate", {});
    state.ccValidateResult = `Validated ${res.total ?? 0} file refs: ${res.fresh ?? 0} fresh, ${res.stale ?? 0} stale.`;
  } catch (err) {
    state.ccError = String(err);
  } finally {
    state.ccLoading = false;
  }
}

export async function pruneCC(state: CCState) {
  if (!state.client || !state.connected) {
    return;
  }
  state.ccLoading = true;
  state.ccError = null;
  state.ccValidateResult = null;
  try {
    const res = await state.client.request<{ ok?: boolean; pruned?: number }>(
      "context-commander.prune",
      {},
    );
    state.ccValidateResult = `Pruned ${res.pruned ?? 0} stale reference(s).`;
    await loadCCTags(state);
  } catch (err) {
    state.ccError = String(err);
  } finally {
    state.ccLoading = false;
  }
}

export async function deleteRef(state: CCState, refId: number) {
  if (!state.client || !state.connected) {
    return;
  }
  state.ccError = null;
  try {
    await state.client.request("context-commander.delete", { id: refId });
    state.ccRefs = state.ccRefs.filter((r) => r.id !== refId);
    await loadCCTags(state);
  } catch (err) {
    state.ccError = String(err);
  }
}

export async function loadCCActivity(state: CCState, limit = 50) {
  if (!state.client || !state.connected) {
    return;
  }
  state.ccActivityLoading = true;
  try {
    const res = await state.client.request<{
      ok?: boolean;
      entries?: CCActivityEntry[];
    }>("context-commander.activity", { limit });
    state.ccActivity = Array.isArray(res.entries) ? res.entries : [];
  } catch {
    state.ccActivity = [];
  } finally {
    state.ccActivityLoading = false;
  }
}

export async function loadCCCompliance(state: CCState, days?: number) {
  if (!state.client || !state.connected) {
    return;
  }
  state.ccComplianceLoading = true;
  try {
    const res = await state.client.request<{
      ok?: boolean;
      compliance?: CCComplianceData;
    }>("context-commander.compliance", { days: days ?? state.ccComplianceDays ?? 7 });
    state.ccCompliance = res.compliance ?? null;
  } catch {
    state.ccCompliance = null;
  } finally {
    state.ccComplianceLoading = false;
  }
}
