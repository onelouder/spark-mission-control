/** Briefing page — loads /api/briefing/today and renders core blocks. */

const BLOCK_LABELS = {
  decisions: "Decisions waiting on you",
  people_waiting: "People waiting",
  stale: "Stale / aging",
  snoozed_now_awake: "Snoozed — now awake",
};

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderRunway(runway) {
  const nowEl = document.getElementById("runway-now");
  const timelineEl = document.getElementById("runway-timeline");
  const tasksEl = document.getElementById("runway-tasks");
  if (!runway) {
    nowEl.textContent = "Runway unavailable";
    return;
  }

  nowEl.textContent = `Pacific now: ${runway.current_time || "—"}`;

  const meetings = runway.timeline_items || [];
  timelineEl.innerHTML = meetings.length
    ? meetings
        .map(
          (m) => `<article class="runway-meeting">
            <span class="runway-meeting-time font-mono">${escapeHtml(m.time)}–${escapeHtml(m.end_time)}</span>
            <span class="runway-meeting-title">${escapeHtml(m.title)}</span>
            <span class="runway-meeting-meta text-muted">${escapeHtml(m.attendees_count)} attendees</span>
          </article>`
        )
        .join("")
    : `<p class="text-muted">No meetings on today's calendar.</p>`;

  const tasks = runway.today_tasks || [];
  tasksEl.innerHTML = tasks.length
    ? tasks
        .map(
          (t) =>
            `<li class="runway-task-item">${escapeHtml(t.title)} <span class="text-muted">in progress</span></li>`
        )
        .join("")
    : `<li class="text-muted">No in-progress tasks.</li>`;
}

function renderBlocks(blocks) {
  const root = document.getElementById("briefing-blocks");
  const skip = new Set(["runway"]);
  const html = Object.entries(blocks || {})
    .filter(([name]) => !skip.has(name))
    .map(([name, block]) => {
      const items = block.data || [];
      const rows = items.length
        ? items
            .map(
              (item) =>
                `<li class="briefing-item">
                  <span class="briefing-item-title">${escapeHtml(item.title)}</span>
                  <span class="briefing-item-context text-muted">${escapeHtml(item.context || item.detail || "")}</span>
                </li>`
            )
            .join("")
        : `<li class="text-muted">Nothing here.</li>`;
      return `<section class="briefing-card">
        <h3 class="briefing-card-title">${escapeHtml(BLOCK_LABELS[name] || name)} <span class="briefing-count">${block.count ?? items.length}</span></h3>
        <ul class="briefing-list">${rows}</ul>
      </section>`;
    })
    .join("");
  root.innerHTML = html;
}

async function loadBriefing(forceRefresh) {
  const meta = document.getElementById("briefing-meta");
  meta.textContent = "Loading…";
  const url = forceRefresh ? "/api/briefing/refresh" : "/api/briefing/today";
  const init = forceRefresh ? { method: "POST" } : {};
  const res = await fetch(url, init);
  if (!res.ok) {
    meta.textContent = `Error ${res.status}`;
    return;
  }
  const body = await res.json();
  meta.textContent = `${body.date} · cached=${body.cached}`;
  renderRunway(body.blocks?.runway?.extra);
  renderBlocks(body.blocks);
}

document.getElementById("briefing-refresh")?.addEventListener("click", () => {
  loadBriefing(true).catch((err) => {
    document.getElementById("briefing-meta").textContent = err.message;
  });
});

loadBriefing(false).catch((err) => {
  document.getElementById("briefing-meta").textContent = err.message;
});
