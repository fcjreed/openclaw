import { html, nothing } from "lit";
import type {
  CCRef,
  CCTag,
  CCStats,
  CCActivityEntry,
  CCComplianceData,
  CCAgentCompliance,
} from "../controllers/context-commander.ts";

export type ContextCommanderProps = {
  loading: boolean;
  tags: CCTag[];
  refs: CCRef[];
  error: string | null;
  stats: CCStats | null;
  queryTags: string;
  queryMinScore: string;
  queryExact: boolean;
  validateResult: string | null;
  activity: CCActivityEntry[];
  activityLoading: boolean;
  compliance: CCComplianceData | null;
  complianceLoading: boolean;
  complianceDays: number;
  onQueryTagsChange: (value: string) => void;
  onQueryMinScoreChange: (value: string) => void;
  onQueryExactChange: (value: boolean) => void;
  onRefresh: () => void;
  onQuery: () => void;
  onValidate: () => void;
  onPrune: () => void;
  onDelete: (refId: number) => void;
  onRefreshActivity: () => void;
  onRefreshCompliance: (days?: number) => void;
};

function groupTagsByPrefix(tags: CCTag[]): Map<string, CCTag[]> {
  const groups = new Map<string, CCTag[]>();
  for (const tag of tags) {
    const slash = tag.name.indexOf("/");
    const prefix = slash > 0 ? tag.name.slice(0, slash) : "(other)";
    const list = groups.get(prefix) ?? [];
    list.push(tag);
    groups.set(prefix, list);
  }
  return groups;
}

function truncate(value: string | null | undefined, max: number): string {
  if (!value) {
    return "";
  }
  return value.length > max ? value.slice(0, max) + "..." : value;
}

function formatBytes(bytes: number | null): string {
  if (bytes == null) {
    return "—";
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function renderScoreBar(label: string, count: number, total: number, color: string) {
  const pct = total > 0 ? (count / total) * 100 : 0;
  return html`
    <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 4px;">
      <span style="width: 60px; font-size: 11px; text-transform: uppercase; opacity: 0.7;">${label}</span>
      <div style="flex: 1; height: 14px; background: var(--bg-secondary, #222); border-radius: 3px; overflow: hidden;">
        <div style="width: ${pct}%; height: 100%; background: ${color}; border-radius: 3px; transition: width 0.3s;"></div>
      </div>
      <span class="muted" style="width: 28px; text-align: right; font-size: 12px;">${count}</span>
    </div>
  `;
}

function complianceColor(agent: CCAgentCompliance): string {
  // Green: active reads + writes. Yellow: some activity but low. Red: nothing.
  if (agent.total_ops === 0) {
    return "var(--danger, #e55)";
  }
  if (agent.reads > 0 && agent.writes > 0) {
    return "var(--success, #4c4)";
  }
  if (agent.reads > 0 || agent.writes > 0) {
    return "var(--warning, #f90)";
  }
  return "var(--danger, #e55)";
}

function complianceLabel(agent: CCAgentCompliance): string {
  if (agent.total_ops === 0) {
    return "Inactive";
  }
  if (agent.reads > 0 && agent.writes > 0) {
    return "Active";
  }
  if (agent.reads > 0) {
    return "Read-only";
  }
  if (agent.writes > 0) {
    return "Write-only";
  }
  return "Low";
}

function operationIcon(op: string): string {
  if (op.startsWith("cc_query")) {
    return "🔍";
  }
  if (op.startsWith("cc_index")) {
    return "📥";
  }
  if (op.startsWith("cc_delete")) {
    return "🗑️";
  }
  if (op.startsWith("cc_validate")) {
    return "✅";
  }
  if (op.startsWith("cc_prune")) {
    return "✂️";
  }
  if (op === "memory_search") {
    return "🧠";
  }
  if (op === "memory_get") {
    return "📖";
  }
  if (op === "memory_read") {
    return "📖";
  }
  if (op === "memory_write") {
    return "✏️";
  }
  return "⚙️";
}

function formatTimeAgo(isoStr: string): string {
  const now = Date.now();
  const then = new Date(isoStr + (isoStr.endsWith("Z") ? "" : "Z")).getTime();
  const diffMs = now - then;
  const mins = Math.floor(diffMs / 60000);
  if (mins < 1) {
    return "just now";
  }
  if (mins < 60) {
    return `${mins}m ago`;
  }
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) {
    return `${hrs}h ago`;
  }
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

function renderCompliance(
  compliance: CCComplianceData | null,
  loading: boolean,
  days: number,
  onRefresh: (days?: number) => void,
) {
  if (!compliance && !loading) {
    return html`
      <section class="card" style="margin-bottom: 18px;">
        <div class="card-title">🏥 Agent Memory Compliance</div>
        <div class="muted" style="margin-top: 8px;">No compliance data available.</div>
        <button class="btn" style="margin-top: 8px;" @click=${() => onRefresh()}>Load</button>
      </section>
    `;
  }

  const agents = compliance?.agents ?? [];
  const totalOps = compliance?.total_operations ?? 0;

  return html`
    <section class="card" style="margin-bottom: 18px;">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <div>
          <div class="card-title">🏥 Agent Memory Compliance</div>
          <div class="card-sub">Who's using memory? Last ${days} days · ${totalOps} total operations</div>
        </div>
        <div style="display: flex; gap: 6px; align-items: center;">
          ${[7, 14, 30].map(
            (d) => html`
              <button
                class="btn ${d === days ? "primary" : ""}"
                style="padding: 2px 8px; font-size: 11px;"
                ?disabled=${loading}
                @click=${() => onRefresh(d)}
              >${d}d</button>
            `,
          )}
        </div>
      </div>

      ${
        loading
          ? html`
              <div class="muted" style="margin-top: 12px">Loading compliance data...</div>
            `
          : nothing
      }

      ${
        agents.length === 0 && !loading
          ? html`<div class="muted" style="margin-top: 12px; padding: 20px; text-align: center;">
              <div style="font-size: 24px; margin-bottom: 8px;">👻</div>
              <div>No agents have logged any memory activity in the last ${days} days.</div>
              <div style="font-size: 12px; margin-top: 4px; opacity: 0.7;">
                Agents need --agent/--session flags when calling CC, and gateway hooks for memory_search/memory_get.
              </div>
            </div>`
          : nothing
      }

      ${
        agents.length > 0
          ? html`
              <div style="margin-top: 14px; display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px;">
                ${agents.map(
                  (agent) => html`
                    <div style="
                      border: 1px solid var(--border, #333);
                      border-radius: 8px;
                      padding: 14px;
                      border-left: 4px solid ${complianceColor(agent)};
                    ">
                      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <div style="font-weight: 600; font-size: 14px;">${agent.agent}</div>
                        <span style="
                          font-size: 11px;
                          padding: 2px 8px;
                          border-radius: 4px;
                          background: ${complianceColor(agent)}22;
                          color: ${complianceColor(agent)};
                          font-weight: 600;
                        ">${complianceLabel(agent)}</span>
                      </div>
                      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 12px;">
                        <div>
                          <span class="muted">CC Queries</span>
                          <div style="font-weight: 600;">${agent.cc_queries}</div>
                        </div>
                        <div>
                          <span class="muted">CC Indexes</span>
                          <div style="font-weight: 600;">${agent.cc_indexes}</div>
                        </div>
                        <div>
                          <span class="muted">Mem Searches</span>
                          <div style="font-weight: 600;">${agent.memory_searches}</div>
                        </div>
                        <div>
                          <span class="muted">Mem Writes</span>
                          <div style="font-weight: 600;">${agent.memory_writes}</div>
                        </div>
                      </div>
                      <div style="margin-top: 8px; font-size: 11px; opacity: 0.6;">
                        ${agent.last_active ? html`Last active: ${formatTimeAgo(agent.last_active)}` : "Never active"}
                        · ${agent.total_ops} total ops
                      </div>
                    </div>
                  `,
                )}
              </div>
            `
          : nothing
      }
    </section>
  `;
}

function renderActivityFeed(activity: CCActivityEntry[], loading: boolean, onRefresh: () => void) {
  return html`
    <section class="card" style="margin-bottom: 18px;">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <div>
          <div class="card-title">📋 Activity Feed</div>
          <div class="card-sub">Recent memory operations across all agents</div>
        </div>
        <button class="btn" style="padding: 2px 10px; font-size: 12px;" ?disabled=${loading} @click=${onRefresh}>
          ${loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      ${
        activity.length === 0 && !loading
          ? html`
              <div class="muted" style="margin-top: 12px; text-align: center; padding: 16px">
                No activity recorded yet.
              </div>
            `
          : nothing
      }

      ${
        activity.length > 0
          ? html`
              <div style="margin-top: 12px; max-height: 400px; overflow-y: auto;">
                ${activity.map(
                  (entry) => html`
                    <div style="
                      display: flex;
                      align-items: flex-start;
                      gap: 10px;
                      padding: 8px 6px;
                      border-bottom: 1px solid var(--border, #333);
                      font-size: 12px;
                    ">
                      <span style="font-size: 14px; flex-shrink: 0;">${operationIcon(entry.operation)}</span>
                      <div style="flex: 1; min-width: 0;">
                        <div style="display: flex; gap: 6px; align-items: center; flex-wrap: wrap;">
                          <span style="
                            font-weight: 600;
                            padding: 1px 6px;
                            border-radius: 3px;
                            background: var(--bg-secondary, #222);
                          ">${entry.agent_id ?? "(unknown)"}</span>
                          <span class="muted">${entry.operation}</span>
                        </div>
                        ${
                          entry.details
                            ? html`<div class="muted" style="margin-top: 2px; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                                ${truncate(JSON.stringify(entry.details), 120)}
                              </div>`
                            : nothing
                        }
                      </div>
                      <span class="muted" style="flex-shrink: 0; font-size: 11px; white-space: nowrap;">
                        ${entry.created_at ? formatTimeAgo(entry.created_at) : "?"}
                      </span>
                    </div>
                  `,
                )}
              </div>
            `
          : nothing
      }
    </section>
  `;
}

function renderStats(stats: CCStats) {
  const dist = stats.score_distribution;
  const totalAssignments = stats.total_tag_assignments || 1;

  return html`
    <section class="card" style="margin-bottom: 18px;">
      <div style="display: flex; gap: 24px; justify-content: space-around; text-align: center;">
        <div>
          <div style="font-size: 28px; font-weight: 700;">${stats.total_refs}</div>
          <div class="muted" style="font-size: 12px;">Total Refs</div>
          <div style="margin-top: 4px; font-size: 11px; opacity: 0.6;">
            ${Object.entries(stats.refs_by_type).map(([t, c]) => html`<span style="margin-right: 6px;">${t}: ${c}</span>`)}
          </div>
        </div>
        <div>
          <div style="font-size: 28px; font-weight: 700;">${stats.total_tags}</div>
          <div class="muted" style="font-size: 12px;">Tags</div>
          <div style="margin-top: 4px; font-size: 11px; opacity: 0.6;">
            ${
              stats.orphan_tags > 0
                ? html`<span style="color: var(--warning, #f90);">${stats.orphan_tags} orphan</span>`
                : html`
                    <span>no orphans</span>
                  `
            }
          </div>
        </div>
        <div>
          <div style="font-size: 28px; font-weight: 700; color: ${stats.stale_count > 0 ? "var(--danger, #e55)" : "var(--success, #4c4)"};">
            ${stats.fresh_count}<span style="opacity: 0.4; font-size: 16px;"> / ${stats.total_refs}</span>
          </div>
          <div class="muted" style="font-size: 12px;">Fresh</div>
          ${stats.stale_count > 0 ? html`<div style="margin-top: 4px; font-size: 11px; color: var(--danger, #e55);">${stats.stale_count} stale</div>` : nothing}
        </div>
        <div>
          <div style="font-size: 28px; font-weight: 700;">${stats.avg_score != null ? stats.avg_score.toFixed(2) : "—"}</div>
          <div class="muted" style="font-size: 12px;">Avg Score</div>
          <div style="margin-top: 4px; font-size: 11px; opacity: 0.6;">
            ${stats.min_score != null ? html`${stats.min_score} — ${stats.max_score}` : "—"}
          </div>
        </div>
      </div>
    </section>

    <section class="grid grid-cols-3" style="margin-bottom: 18px;">
      <div class="card">
        <div class="card-title" style="font-size: 13px;">Score Distribution</div>
        <div style="margin-top: 8px;">
          ${renderScoreBar("critical", dist.critical, totalAssignments, "#4caf50")}
          ${renderScoreBar("high", dist.high, totalAssignments, "#8bc34a")}
          ${renderScoreBar("good", dist.good, totalAssignments, "#ffeb3b")}
          ${renderScoreBar("medium", dist.medium, totalAssignments, "#ff9800")}
          ${renderScoreBar("low", dist.low, totalAssignments, "#f44336")}
        </div>
      </div>
      <div class="card">
        <div class="card-title" style="font-size: 13px;">Top Tags</div>
        <div style="margin-top: 8px;">
          ${
            stats.top_tags.length === 0
              ? html`
                  <div class="muted">No tags yet.</div>
                `
              : stats.top_tags.slice(0, 8).map(
                  (t) => html`
                  <div style="display: flex; justify-content: space-between; padding: 2px 0; font-size: 12px;">
                    <span>${t.name}</span>
                    <span class="muted">${t.ref_count}</span>
                  </div>
                `,
                )
          }
        </div>
      </div>
      <div class="card">
        <div class="card-title" style="font-size: 13px;">Activity & Storage</div>
        <div style="margin-top: 8px;">
          ${
            stats.recent_activity.length === 0
              ? html`
                  <div class="muted" style="font-size: 12px">No recent activity.</div>
                `
              : stats.recent_activity.map(
                  (a) => html`
                  <div style="display: flex; justify-content: space-between; padding: 2px 0; font-size: 12px;">
                    <span>${a.day}</span>
                    <span class="muted">+${a.count} ref${a.count !== 1 ? "s" : ""}</span>
                  </div>
                `,
                )
          }
          <div style="margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--border, #333);">
            <div style="display: flex; justify-content: space-between; font-size: 12px;">
              <span class="muted">DB size</span>
              <span>${formatBytes(stats.db_size_bytes)}</span>
            </div>
            <div style="display: flex; justify-content: space-between; font-size: 12px;">
              <span class="muted">Tag links</span>
              <span>${stats.total_tag_assignments}</span>
            </div>
            ${
              stats.oldest_ref
                ? html`
              <div style="display: flex; justify-content: space-between; font-size: 12px;">
                <span class="muted">Since</span>
                <span>${stats.oldest_ref.split("T")[0] ?? stats.oldest_ref.split(" ")[0]}</span>
              </div>
            `
                : nothing
            }
          </div>
        </div>
      </div>
    </section>
  `;
}

export function renderContextCommander(props: ContextCommanderProps) {
  const tagGroups = groupTagsByPrefix(props.tags);

  return html`
    ${props.stats ? renderStats(props.stats) : nothing}

    ${renderCompliance(props.compliance, props.complianceLoading, props.complianceDays, props.onRefreshCompliance)}

    ${renderActivityFeed(props.activity, props.activityLoading, props.onRefreshActivity)}

    <section class="grid grid-cols-2">
      <div class="card">
        <div class="card-title">Tags</div>
        <div class="card-sub">Hierarchical tag index. Click a tag to populate the query field.</div>
        <div style="margin-top: 12px;">
          <button class="btn" ?disabled=${props.loading} @click=${props.onRefresh}>
            ${props.loading ? "Loading..." : "Refresh Tags"}
          </button>
        </div>
        ${
          props.tags.length === 0
            ? html`
                <div class="muted" style="margin-top: 12px">No tags found.</div>
              `
            : html`
                <div style="margin-top: 12px; max-height: 400px; overflow-y: auto;">
                  ${[...tagGroups.entries()].map(
                    ([prefix, groupTags]) => html`
                      <div style="margin-bottom: 8px;">
                        <div style="font-weight: 600; font-size: 11px; text-transform: uppercase; opacity: 0.6; margin-bottom: 4px;">
                          ${prefix}
                        </div>
                        ${groupTags.map(
                          (tag) => html`
                            <div
                              class="list-item list-item-clickable"
                              style="padding: 4px 8px; cursor: pointer;"
                              @click=${() => props.onQueryTagsChange(tag.name)}
                            >
                              <span style="flex: 1;">${tag.name}</span>
                              <span class="muted">${tag.ref_count} refs</span>
                            </div>
                          `,
                        )}
                      </div>
                    `,
                  )}
                </div>
              `
        }
      </div>

      <div class="card">
        <div class="card-title">Query</div>
        <div class="card-sub">Search the reference index by tags.</div>
        <div class="form-grid" style="margin-top: 16px;">
          <label class="field">
            <span>Tags (comma-separated)</span>
            <input
              .value=${props.queryTags}
              @input=${(e: Event) => props.onQueryTagsChange((e.target as HTMLInputElement).value)}
            />
          </label>
          <label class="field">
            <span>Min Score</span>
            <input
              type="number"
              min="0"
              max="1"
              step="0.1"
              .value=${props.queryMinScore}
              @input=${(e: Event) =>
                props.onQueryMinScoreChange((e.target as HTMLInputElement).value)}
            />
          </label>
          <label class="field checkbox">
            <span>Exact match</span>
            <input
              type="checkbox"
              .checked=${props.queryExact}
              @change=${(e: Event) =>
                props.onQueryExactChange((e.target as HTMLInputElement).checked)}
            />
          </label>
        </div>
        <div class="row" style="margin-top: 14px;">
          <button class="btn primary" ?disabled=${props.loading} @click=${props.onQuery}>
            ${props.loading ? "Querying..." : "Query"}
          </button>
          ${props.error ? html`<span class="muted" style="color: var(--danger, #e55);">${props.error}</span>` : nothing}
        </div>
      </div>
    </section>

    <section class="card" style="margin-top: 18px;">
      <div class="card-title">Results</div>
      <div class="card-sub">References matching the current query.</div>
      ${
        props.refs.length === 0
          ? html`
              <div class="muted" style="margin-top: 12px">No results. Run a query above.</div>
            `
          : html`
              <div style="margin-top: 12px; overflow-x: auto;">
                <table class="table" style="width: 100%; font-size: 13px;">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Type</th>
                      <th>Location / Snippet</th>
                      <th>Tags</th>
                      <th>Score</th>
                      <th>Stale</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    ${props.refs.map(
                      (ref) => html`
                        <tr>
                          <td>${ref.id}</td>
                          <td>${ref.type}</td>
                          <td style="max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                            ${truncate(ref.location ?? ref.snippet, 80)}
                            ${ref.range_start != null ? html` <span class="muted">L${ref.range_start}-${ref.range_end}</span>` : nothing}
                          </td>
                          <td>
                            ${ref.tags.map(
                              (t) => html`<span class="chip" style="margin: 1px;">${t.name}</span>`,
                            )}
                          </td>
                          <td>${ref.tags.length > 0 ? ref.tags[0].score.toFixed(2) : "—"}</td>
                          <td>${
                            ref.stale
                              ? html`
                                  <span class="chip chip-danger">stale</span>
                                `
                              : "—"
                          }</td>
                          <td>
                            <button
                              class="btn danger"
                              style="padding: 2px 8px; font-size: 12px;"
                              @click=${() => props.onDelete(ref.id)}
                            >
                              Delete
                            </button>
                          </td>
                        </tr>
                      `,
                    )}
                  </tbody>
                </table>
              </div>
            `
      }
    </section>

    <section class="card" style="margin-top: 18px;">
      <div class="card-title">Maintenance</div>
      <div class="card-sub">Validate file references and prune stale entries.</div>
      <div class="row" style="margin-top: 12px; gap: 8px;">
        <button class="btn" ?disabled=${props.loading} @click=${props.onValidate}>
          ${props.loading ? "Validating..." : "Validate File Refs"}
        </button>
        <button class="btn danger" ?disabled=${props.loading} @click=${props.onPrune}>
          ${props.loading ? "Pruning..." : "Prune Stale"}
        </button>
      </div>
      ${props.validateResult ? html`<div class="muted" style="margin-top: 8px;">${props.validateResult}</div>` : nothing}
    </section>
  `;
}
