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

export type CCState = {
  client: GatewayBrowserClient | null;
  connected: boolean;
  ccLoading: boolean;
  ccTags: CCTag[];
  ccRefs: CCRef[];
  ccError: string | null;
  ccSelectedRefId: number | null;
  ccQueryTags: string;
  ccQueryMinScore: string;
  ccQueryExact: boolean;
  ccValidateResult: string | null;
};

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
