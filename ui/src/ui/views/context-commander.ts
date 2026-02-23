import { html, nothing } from "lit";
import type { CCRef, CCTag } from "../controllers/context-commander.ts";

export type ContextCommanderProps = {
  loading: boolean;
  tags: CCTag[];
  refs: CCRef[];
  error: string | null;
  queryTags: string;
  queryMinScore: string;
  queryExact: boolean;
  validateResult: string | null;
  onQueryTagsChange: (value: string) => void;
  onQueryMinScoreChange: (value: string) => void;
  onQueryExactChange: (value: boolean) => void;
  onRefresh: () => void;
  onQuery: () => void;
  onValidate: () => void;
  onPrune: () => void;
  onDelete: (refId: number) => void;
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
  if (!value) return "";
  return value.length > max ? value.slice(0, max) + "..." : value;
}

export function renderContextCommander(props: ContextCommanderProps) {
  const tagGroups = groupTagsByPrefix(props.tags);

  return html`
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
            ? html`<div class="muted" style="margin-top: 12px;">No tags found.</div>`
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
              @input=${(e: Event) =>
                props.onQueryTagsChange((e.target as HTMLInputElement).value)}
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
          ? html`<div class="muted" style="margin-top: 12px;">No results. Run a query above.</div>`
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
                          <td>${ref.stale ? html`<span class="chip chip-danger">stale</span>` : "—"}</td>
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
