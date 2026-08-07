/* vidpack — app runtime. Vanilla JS, no build step.
   Renders against the FastAPI JSON in app/main.py. */

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const state = {
  niches: [],
  nicheId: null,
  nicheName: "",
  windowDays: 90,
  videos: [],
  hooks: [],
  summary: null,
  pkg: null,
  running: false,
};

/* ── dom helpers ─────────────────────────────────────────────────────── */

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.appendChild(typeof child === "object" ? child : document.createTextNode(String(child)));
  }
  return node;
}

function icon(name, cls = "ic ic-sm") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", cls);
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#i-${name}`);
  svg.appendChild(use);
  return svg;
}

function meter(pct, variant = "") {
  const clamped = Math.max(0, Math.min(100, Number(pct) || 0));
  return el("span", { class: `meter ${variant}`.trim() }, [
    el("i", { style: `width:${clamped}%` }),
  ]);
}

function emptyState(iconName, title, sub, action) {
  return el("div", { class: "empty" }, [
    el("span", { class: "empty-ic" }, [icon(iconName, "ic")]),
    el("p", { class: "empty-title", text: title }),
    el("p", { class: "empty-sub", text: sub }),
    action || null,
  ]);
}

function fill(host, node) {
  host.textContent = "";
  if (node) host.appendChild(node);
}

/* ── formatting ──────────────────────────────────────────────────────── */

function fmtCount(n) {
  const num = Number(n);
  if (n === null || n === undefined || !isFinite(num)) return "—";
  if (num >= 1e9) return (num / 1e9).toFixed(1).replace(/\.0$/, "") + "B";
  if (num >= 1e6) return (num / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (num >= 1e3) return (num / 1e3).toFixed(1).replace(/\.0$/, "") + "K";
  return num.toLocaleString();
}

function fmtDur(sec) {
  if (!sec) return "";
  const s = Math.round(sec);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const pad = (x) => String(x).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s % 60)}` : `${m}:${pad(s % 60)}`;
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return isNaN(d) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function fmtAgo(iso) {
  if (!iso) return "never";
  const then = new Date(/[Z+]/.test(iso) ? iso : iso + "Z");
  if (isNaN(then)) return "";
  const mins = Math.round((Date.now() - then.getTime()) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return days < 30 ? `${days}d ago` : fmtDate(iso);
}

function hookTypes(raw) {
  return String(raw || "").split("|").map((s) => s.trim()).filter(Boolean);
}

/* The YouTube API returns HTML-escaped titles (&quot;, &#39;, &amp;).
   Decode for display — the value is then inserted as text, never as markup. */
const decoderEl = document.createElement("textarea");

function decodeHtml(text) {
  if (text === null || text === undefined) return "";
  const value = String(text);
  if (!value.includes("&")) return value;
  decoderEl.innerHTML = value;
  return decoderEl.value;
}

/* ── api ─────────────────────────────────────────────────────────────── */

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

/* ── snackbar ────────────────────────────────────────────────────────── */

const snack = {
  show(message, kind = "info") {
    const bar = $("#snackbar");
    $("#snackText").textContent = message;
    $("#snackIcon").firstElementChild.setAttribute(
      "href",
      kind === "error" ? "#i-error" : kind === "good" ? "#i-check" : "#i-info"
    );
    bar.className =
      "snackbar is-open" + (kind === "error" ? " is-error" : kind === "good" ? " is-good" : "");
    clearTimeout(bar._timer);
    bar._timer = setTimeout(() => (bar.className = "snackbar"), kind === "error" ? 6000 : 4000);
  },
};

/* ── theme ───────────────────────────────────────────────────────────── */

function resolvedTheme() {
  const stamped = document.documentElement.dataset.theme;
  if (stamped === "light" || stamped === "dark") return stamped;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function paintThemeIcon() {
  $("#themeIcon").firstElementChild.setAttribute(
    "href",
    resolvedTheme() === "dark" ? "#i-sun" : "#i-moon"
  );
}

function toggleTheme() {
  const next = resolvedTheme() === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem("vidpack-theme", next);
  } catch (e) {}
  paintThemeIcon();
}

/* ── clipboard ───────────────────────────────────────────────────────── */

async function copy(text, label = "Copied") {
  try {
    await navigator.clipboard.writeText(text);
    snack.show(label, "good");
  } catch (e) {
    snack.show("The browser blocked the clipboard. Select the text and copy manually.", "error");
  }
}

/* ── async button state ──────────────────────────────────────────────── */

function busy(btn, on) {
  if (!btn) return;
  btn.dataset.busy = on ? "true" : "false";
  btn.disabled = !!on;
}

/* ── navigation ──────────────────────────────────────────────────────── */

const VIEWS = ["research", "packages", "library"];

function currentView() {
  const hash = (location.hash || "").replace(/^#\/?/, "");
  return VIEWS.includes(hash) ? hash : "research";
}

function goto(view, { push = true } = {}) {
  const target = VIEWS.includes(view) ? view : "research";
  $$(".nav-item").forEach((b) => {
    const on = b.dataset.view === target;
    if (on) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  });
  $$(".view").forEach((v) => v.classList.toggle("is-active", v.dataset.view === target));
  if (push && location.hash !== `#${target}`) history.pushState(null, "", `#${target}`);
  if (target === "library" && state.nicheId) loadLibrary(state.nicheId);
  closeDrawer();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function drawerMode() {
  return window.matchMedia("(max-width: 1024px)").matches;
}

function openDrawer() {
  $("#shell").classList.add("is-drawer-open");
  $("#scrim").classList.add("is-open");
}

function closeDrawer() {
  $("#shell").classList.remove("is-drawer-open");
  $("#scrim").classList.remove("is-open");
}

function toggleNav() {
  if (drawerMode()) {
    $("#shell").classList.contains("is-drawer-open") ? closeDrawer() : openDrawer();
  } else {
    $("#shell").classList.toggle("is-collapsed");
  }
}

/* ── health ──────────────────────────────────────────────────────────── */

async function loadHealth() {
  try {
    const health = await api("/api/health");
    if (!health.youtube_key) {
      snack.show("YouTube data access is not configured, so research cannot run.", "error");
    }
  } catch (e) {
    /* the API is down; the shell will show it elsewhere */
  }
}

/* ── niches ──────────────────────────────────────────────────────────── */

async function loadNiches() {
  const data = await api("/api/niches");
  state.niches = data.niches || [];
  renderRail();
  renderRecent();
  fillSelect($("#genNiche"));
  fillSelect($("#libNiche"));
  syncSelects();
  return state.niches;
}

function fillSelect(select) {
  const previous = select.value;
  select.textContent = "";
  select.appendChild(el("option", { value: "", text: "Choose a niche" }));
  state.niches.forEach((n) =>
    select.appendChild(
      el("option", { value: n.id, text: n.total_runs > 0 ? n.name : `${n.name} (not researched)` })
    )
  );
  if (previous) select.value = previous;
}

function syncSelects() {
  if (!state.nicheId) return;
  const has = state.niches.some((n) => n.id === state.nicheId);
  if (!has) return;
  $("#genNiche").value = state.nicheId;
  $("#libNiche").value = state.nicheId;
  $$(".rail-niche").forEach((r) =>
    r.setAttribute("aria-current", r.dataset.niche === state.nicheId ? "true" : "false")
  );
}

function nicheMeta(n) {
  return n.total_runs > 0
    ? `${n.total_runs} run${n.total_runs > 1 ? "s" : ""} · ${fmtAgo(n.last_research_at)}`
    : "Not researched yet";
}

function renderRail() {
  const host = $("#railNiches");
  host.textContent = "";
  if (!state.niches.length) {
    host.appendChild(
      el("p", {
        class: "rail-foot",
        style: "border:0;padding:6px 14px",
        text: "Nothing yet. Search a niche to start.",
      })
    );
    return;
  }
  state.niches.slice(0, 12).forEach((n) => {
    host.appendChild(
      el(
        "button",
        {
          class: "rail-niche",
          "data-niche": n.id,
          "aria-current": state.nicheId === n.id ? "true" : "false",
          onclick: () => openNiche(n.id),
        },
        [
          el("span", { class: "rn-dot", text: (n.name || "?").trim().charAt(0) }),
          el("span", { class: "rn-body" }, [
            el("span", { class: "rn-name", text: n.name }),
            el("span", { class: "rn-meta", text: nicheMeta(n) }),
          ]),
        ]
      )
    );
  });
}

function renderRecent() {
  const host = $("#recentList");
  host.textContent = "";
  const researched = state.niches.filter((n) => n.total_runs > 0);
  if (!researched.length) {
    host.appendChild(
      emptyState(
        "insights",
        "No research yet",
        "Search a niche above. One run analyses up to 30 recent videos."
      )
    );
    return;
  }
  const list = el("div", { class: "vid-list" });
  researched.slice(0, 8).forEach((n) => {
    list.appendChild(
      el(
        "button",
        { class: "vid-row", style: "grid-template-columns:36px minmax(0,1fr) auto", onclick: () => openNiche(n.id) },
        [
          el("span", { class: "rn-dot", text: (n.name || "?").trim().charAt(0) }),
          el("span", { class: "vr-body" }, [
            el("span", { class: "vr-title", text: n.name }),
            el("span", { class: "vr-meta", text: `${nicheMeta(n)} · ${n.window_days}d window` }),
          ]),
          icon("chevron", "ic ic-sm"),
        ]
      )
    );
  });
  host.appendChild(list);
}

/* ── research: rendering ─────────────────────────────────────────────── */

function showIdle() {
  $("#researchIdle").classList.remove("hidden");
  $("#researchResults").classList.add("hidden");
  $("#runbar").classList.add("hidden");
}

function showResults() {
  $("#researchIdle").classList.add("hidden");
  $("#researchResults").classList.remove("hidden");
}

function thumbUrl(video) {
  if (video.thumbnail_url) return video.thumbnail_url;
  if (video.youtube_id) return `https://i.ytimg.com/vi/${video.youtube_id}/mqdefault.jpg`;
  return "";
}

function watchUrl(video) {
  return video.youtube_id ? `https://www.youtube.com/watch?v=${video.youtube_id}` : "";
}

function statTile(label, value, sub, iconName, isText) {
  return el("div", { class: "stat" }, [
    el("div", { class: "stat-label" }, [icon(iconName, "ic ic-xs"), label]),
    el("div", { class: "stat-value" + (isText ? " is-text" : ""), text: value }),
    sub ? el("div", { class: "stat-sub", text: sub }) : null,
  ]);
}

function renderStats(videos, summary) {
  const host = $("#statsRow");
  host.textContent = "";
  const scores = videos.map((v) => Number(v.engagement_score) || 0).filter((n) => n > 0);
  const avg = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;
  const views = videos.reduce((a, v) => a + (Number(v.views) || 0), 0);
  const topHook = (summary && summary.hook_types && summary.hook_types[0]) || null;
  const features = (summary && summary.features) || {};

  host.appendChild(statTile("Videos analysed", String(videos.length), "in this cohort", "insights"));
  host.appendChild(
    statTile("Median views", fmtCount(medianOf(videos.map((v) => Number(v.views) || 0))),
      `${fmtCount(views)} across the cohort`, "eye")
  );
  host.appendChild(
    statTile("Avg engagement", avg ? avg.toFixed(2) : "—", "likes and comments per view, recency-weighted", "trending")
  );
  host.appendChild(
    topHook
      ? statTile("Leading hook", String(topHook.type || topHook.hook_type || "—"),
          `${Math.round((topHook.share || 0) * 100)}% of the cohort`, "bulb", true)
      : statTile("Best posting day", features.best_post_day || "—", "highest average engagement", "clock", true)
  );
}

function medianOf(nums) {
  const sorted = nums.filter((n) => isFinite(n)).sort((a, b) => a - b);
  if (!sorted.length) return 0;
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function cohortSkeleton(rows = 6) {
  const host = $("#cohortList");
  host.textContent = "";
  for (let i = 0; i < rows; i++) {
    host.appendChild(
      el("div", { class: "sk-row" }, [
        el("div", { class: "skeleton sk-line", style: "width:16px" }),
        el("div", { class: "skeleton sk-thumb" }),
        el("div", {}, [
          el("div", { class: "skeleton sk-line", style: "width:86%" }),
          el("div", { class: "skeleton sk-line", style: "width:52%;margin-top:8px;height:10px" }),
        ]),
        el("div", { class: "skeleton sk-line", style: "height:10px" }),
      ])
    );
  }
}

function renderCohort(videos, hooks) {
  state.videos = videos || [];
  state.hooks = hooks || [];
  const host = $("#cohortList");
  host.textContent = "";
  $("#cohortCount").textContent = videos.length ? `${videos.length} videos` : "";

  if (!videos.length) {
    host.appendChild(
      emptyState(
        "insights",
        "No videos stored for this niche",
        "Run research once and the ranked cohort, its hooks and its keywords land here."
      )
    );
    return;
  }

  const top = Math.max(...videos.map((v) => Number(v.engagement_score) || 0), 0.0001);
  const hookByVideo = new Map(state.hooks.map((h) => [h.source_video_id, h]));
  const pageSize = 15;
  const pages = Math.ceil(videos.length / pageSize);
  let page = 0;

  function draw() {
    host.textContent = "";
    const slice = videos.slice(page * pageSize, page * pageSize + pageSize);
    slice.forEach((video, i) => {
      const index = page * pageSize + i;
      const score = Number(video.engagement_score) || 0;
      const hook = hookByVideo.get(video.youtube_id);
      const types = hookTypes(hook && hook.hook_type).slice(0, 2);
      const thumb = thumbUrl(video);

      const row = el(
        "button",
        {
          class: "vid-row",
          type: "button",
          "aria-expanded": "false",
          onclick: (event) => toggleDetail(event.currentTarget, video, hook),
        },
        [
          el("span", { class: "vr-rank", text: String(index + 1) }),
          el("span", { class: "vr-thumb" }, [
            thumb ? el("img", { src: thumb, alt: "", loading: "lazy", decoding: "async" }) : null,
            video.duration_sec ? el("span", { class: "vr-dur", text: fmtDur(video.duration_sec) }) : null,
          ]),
          el("span", { class: "vr-body" }, [
            el("span", { class: "vr-title", text: decodeHtml(video.title) || "Untitled" }),
            el("span", {
              class: "vr-meta",
              text: [
                decodeHtml(video.channel_title) || "Unknown channel",
                `${fmtCount(video.views)} views`,
                fmtDate(video.published_at),
              ].filter(Boolean).join(" · "),
            }),
            types.length
              ? el("span", { class: "vr-hooks" }, types.map((t) => el("span", { class: "tag tag-primary", text: t })))
              : null,
          ]),
          el("span", { class: "vr-right" }, [
            el("span", { class: "vr-score", text: score ? score.toFixed(2) : "—" }),
            meter((score / top) * 100, index === 0 ? "meter-lead" : ""),
          ]),
        ]
      );
      host.appendChild(row);
    });

    if (pages > 1) {
      const from = page * pageSize + 1;
      const to = Math.min((page + 1) * pageSize, videos.length);
      host.appendChild(
        el("div", { class: "pager" }, [
          el("span", { class: "pager-info", text: `${from}–${to} of ${videos.length}` }),
          el("span", { class: "pager-ctrls" }, [
            el("button", {
              class: "btn btn-text btn-sm",
              text: "← Prev",
              disabled: page === 0,
              onclick: () => { if (page > 0) { page--; draw(); } },
            }),
            el("button", {
              class: "btn btn-text btn-sm",
              text: "Next →",
              disabled: page >= pages - 1,
              onclick: () => { if (page < pages - 1) { page++; draw(); } },
            }),
          ]),
        ])
      );
    }
  }
  draw();
}

function toggleDetail(row, video, hook) {
  const next = row.nextElementSibling;
  const open = row.getAttribute("aria-expanded") === "true";
  if (open && next && next.classList.contains("vid-detail")) {
    next.remove();
    row.setAttribute("aria-expanded", "false");
    return;
  }
  $$(".vid-detail").forEach((d) => d.remove());
  $$(".vid-row").forEach((r) => r.setAttribute("aria-expanded", "false"));
  row.setAttribute("aria-expanded", "true");

  const ratio = video.views ? ((Number(video.likes) || 0) / video.views) * 100 : 0;
  const detail = el("div", { class: "vid-detail" }, [
    el("div", { class: "vd-grid" }, [
      detailItem("Channel", decodeHtml(video.channel_title) || "—"),
      detailItem("Engagement score", (Number(video.engagement_score) || 0).toFixed(2)),
      detailItem("Views", fmtCount(video.views)),
      detailItem("Likes", `${fmtCount(video.likes)} (${ratio.toFixed(2)}% of views)`),
      detailItem("Comments", fmtCount(video.comments)),
      detailItem("Duration", fmtDur(video.duration_sec) || "—"),
      detailItem("Published", fmtDate(video.published_at) || "—"),
      detailItem("Hook pattern", hookTypes(hook && hook.hook_type).join(", ") || "plain"),
    ]),
    video.tags && video.tags.length
      ? el("div", { style: "margin-top:14px" }, [
          el("div", { class: "vd-label", style: "margin-bottom:6px" }, "Creator tags"),
          el("div", { class: "tag-wrap" },
            video.tags.slice(0, 12).map((t) => el("span", { class: "tag", text: t }))),
        ])
      : null,
    el("div", { class: "vd-foot" }, [
      el("a", {
        class: "btn btn-outlined btn-sm",
        href: watchUrl(video),
        target: "_blank",
        rel: "noopener",
      }, [icon("external"), "Open on YouTube"]),
      el("button", {
        class: "btn btn-text btn-sm",
        onclick: () => copy(decodeHtml(video.title), "Title copied"),
      }, [icon("copy"), "Copy title"]),
    ]),
  ]);
  row.after(detail);
}

function detailItem(label, value) {
  return el("div", { class: "vd-item" }, [
    el("div", { class: "vd-label", text: label }),
    el("div", { class: "vd-value", text: value }),
  ]);
}

function renderHookMix(summary) {
  const host = $("#hookMix");
  const rows = (summary && summary.hook_types) || [];
  if (!rows.length) {
    fill(host, emptyState("bulb", "No hook data", "Run research on this niche to classify its hooks."));
    return;
  }
  const box = el("div", { class: "dist" });
  rows.slice(0, 6).forEach((row) => {
    const share = Math.round((row.share || 0) * 100);
    box.appendChild(
      el("div", { class: "dist-row" }, [
        el("span", { class: "dr-name", text: String(row.type || row.hook_type || "plain") }),
        el("span", { class: "dr-val", text: `${share}%` }),
        meter(share),
      ])
    );
  });
  fill(host, box);
}

function renderKeywords(summary) {
  const host = $("#keywordList");
  const rows = (summary && summary.keywords) || [];
  if (!rows.length) {
    fill(host, emptyState("tag", "No keywords yet", "Keywords are pulled from titles and creator tags during a run."));
    return;
  }
  const top = Math.max(...rows.map((k) => Number(k.weight) || 0), 0.0001);
  const box = el("div", { class: "dist" });
  rows.slice(0, 8).forEach((row) => {
    box.appendChild(
      el("div", { class: "dist-row" }, [
        el("span", { class: "dr-name", text: row.term }),
        el("span", { class: "dr-val", text: `×${row.freq}` }),
        meter(((Number(row.weight) || 0) / top) * 100),
      ])
    );
  });
  fill(host, box);
}

function renderFacts(summary, videos) {
  const host = $("#cohortFacts");
  const features = (summary && summary.features) || {};
  const buckets = features.duration_buckets || {};
  const bucketList = Array.isArray(buckets)
    ? buckets.map((b) => [b.bucket, b.count])
    : Object.entries(buckets);
  bucketList.sort((a, b) => b[1] - a[1]);

  const facts = [];
  if (features.best_post_day) {
    facts.push(["clock", `Best posting day is <b>${features.best_post_day}</b> by average engagement.`]);
  }
  if (features.avg_title_length) {
    facts.push(["script", `Titles average <b>${features.avg_title_length}</b> characters.`]);
  }
  if (bucketList.length) {
    facts.push(["play", `Most of the cohort runs <b>${bucketList[0][0]}</b> (${bucketList[0][1]} videos).`]);
  }
  const channels = new Set(videos.map((v) => v.channel_title).filter(Boolean));
  if (channels.size) {
    facts.push(["library", `<b>${channels.size}</b> distinct channels in the top ${videos.length}.`]);
  }

  if (!facts.length) {
    fill(host, emptyState("info", "No profile yet", "Cohort features appear after the first run."));
    return;
  }
  const box = el("div", { class: "facts" });
  facts.forEach(([name, html]) => {
    const line = el("div", { class: "fact" }, [icon(name)]);
    const span = document.createElement("span");
    span.innerHTML = html;
    line.appendChild(span);
    box.appendChild(line);
  });
  fill(host, box);
}

function renderHookPager(host, hooks, pageSize = 8) {
  if (!hooks || !hooks.length) {
    fill(host, emptyState("bulb", "No hooks yet", "The best-performing titles become the hook library."));
    return 0;
  }
  const top = Math.max(...hooks.map((h) => Number(h.score) || 0), 0.0001);
  const pages = Math.ceil(hooks.length / pageSize);
  let page = 0;

  function draw() {
    const box = el("div", { class: "hook-list" });
    hooks.slice(page * pageSize, page * pageSize + pageSize).forEach((hook) => {
      const score = Number(hook.score) || 0;
      box.appendChild(
        el("div", { class: "hook-row" }, [
          el("span", { class: "hr-text", text: decodeHtml(hook.hook_text || hook.text) || "—" }),
          el("span", { class: "hr-score", text: score.toFixed(2) }),
          el("span", { class: "hr-bar" }, [meter((score / top) * 100)]),
        ])
      );
    });
    if (pages > 1) {
      const from = page * pageSize + 1;
      const to = Math.min((page + 1) * pageSize, hooks.length);
      box.appendChild(
        el("div", { class: "pager" }, [
          el("span", { class: "pager-info", text: `${from}–${to} of ${hooks.length}` }),
          el("span", { class: "pager-ctrls" }, [
            el("button", {
              class: "btn btn-text btn-sm",
              text: "← Prev",
              disabled: page === 0,
              onclick: () => { if (page > 0) { page--; draw(); } },
            }),
            el("button", {
              class: "btn btn-text btn-sm",
              text: "Next →",
              disabled: page >= pages - 1,
              onclick: () => { if (page < pages - 1) { page++; draw(); } },
            }),
          ]),
        ])
      );
    }
    fill(host, box);
  }
  draw();
  return hooks.length;
}

function renderHooks(hooks) {
  renderHookPager($("#hooksList"), hooks, 8);
}

function renderResearch(name, metaParts, videos, hooks, summary) {
  state.nicheName = name;
  state.summary = summary;
  $("#resTitle").textContent = name;

  const meta = $("#resMeta");
  meta.textContent = "";
  metaParts.filter(Boolean).forEach((part) => meta.appendChild(el("span", { class: "tag", text: part })));

  renderStats(videos, summary);
  renderCohort(videos, hooks);
  renderHookMix(summary);
  renderKeywords(summary);
  renderFacts(summary, videos);
  renderHooks(hooks);
  showResults();
}

/* patterns rows (stored) -> the same shape build_research_summary returns */
function patternsToSummary(rows) {
  if (!rows || !rows.length) return null;
  const hook_types = rows
    .filter((r) => r.kind === "hook_type")
    .map((r) => ({ type: r.value, share: r.avg_score || 0, count: r.occurrences }))
    .sort((a, b) => b.share - a.share);
  const keywords = rows
    .filter((r) => r.kind === "keyword")
    .map((r) => ({ term: r.value, freq: r.occurrences, weight: r.avg_score }));
  const duration_buckets = {};
  rows.filter((r) => r.kind === "duration").forEach((r) => (duration_buckets[r.value] = r.occurrences));
  return { hook_types, keywords, features: { duration_buckets } };
}

/* cohort features the patterns table does not store, derived client-side */
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function deriveFeatures(videos) {
  if (!videos || !videos.length) return {};
  const lengths = videos.map((v) => (v.title || "").length);
  const byDay = new Map();
  videos.forEach((v) => {
    const date = new Date(v.published_at || "");
    if (isNaN(date)) return;
    const key = WEEKDAYS[date.getUTCDay()];
    const bucket = byDay.get(key) || [];
    bucket.push(Number(v.engagement_score) || 0);
    byDay.set(key, bucket);
  });
  let bestDay = null;
  let bestAvg = -1;
  byDay.forEach((scores, day) => {
    const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
    if (avg > bestAvg) {
      bestAvg = avg;
      bestDay = day;
    }
  });
  return {
    best_post_day: bestDay,
    avg_title_length: lengths.length
      ? Math.round((lengths.reduce((a, b) => a + b, 0) / lengths.length) * 10) / 10
      : 0,
  };
}

function withDerived(summary, videos) {
  const base = summary || {};
  return { ...base, features: { ...deriveFeatures(videos), ...(base.features || {}) } };
}

/* ── research: running ───────────────────────────────────────────────── */

function setStep(index, status) {
  const step = $(`.run-step[data-step="${index}"]`);
  if (step) step.dataset.state = status;
}

function startRun(name) {
  state.running = true;
  $("#runbar").classList.remove("hidden");
  $("#runTitle").textContent = `Researching “${name}”`;
  $("#runProgress").style.width = "12%";
  [1, 2, 3].forEach((i) => setStep(i, ""));
  setStep(1, "active");
  $("#researchIdle").classList.add("hidden");
  showResults();
  $("#resTitle").textContent = name;
  $("#resMeta").textContent = "";
  $("#statsRow").textContent = "";
  cohortSkeleton();
}

function endRun() {
  state.running = false;
  $("#runProgress").style.width = "100%";
  setTimeout(() => $("#runbar").classList.add("hidden"), 900);
}

async function runResearch(rawName, days) {
  const name = (rawName || "").trim();
  if (name.length < 2) {
    snack.show("Type at least two characters to research a niche.", "error");
    return;
  }
  if (state.running) return;

  const heroBtn = $("#heroSubmit");
  busy(heroBtn, true);
  startRun(name);

  try {
    const created = await api("/api/niches", {
      method: "POST",
      body: JSON.stringify({ name, window_days: days || state.windowDays }),
    });
    const niche = created.niche;
    state.nicheId = niche.id;

    setStep(1, "done");
    setStep(2, "active");
    $("#runProgress").style.width = "48%";

    const result = await api(`/api/niches/${niche.id}/research`, { method: "POST" });

    setStep(2, "done");
    setStep(3, "active");
    $("#runProgress").style.width = "82%";

    const hooksData = await api(`/api/niches/${niche.id}/hooks`);
    setStep(3, "done");

    renderResearch(
      niche.name,
      [
        `${result.videos.length} videos`,
        `${niche.window_days}d window`,
        result.run_id ? `run #${result.run_id}` : null,
        "just now",
      ],
      result.videos || [],
      hooksData.hooks || [],
      withDerived(result.summary, result.videos || [])
    );

    await loadNiches();
    syncSelects();
    snack.show(`Research complete. ${result.videos.length} videos analysed.`, "good");
  } catch (error) {
    $("#runbar").classList.add("hidden");
    $("#cohortList").textContent = "";
    $("#cohortList").appendChild(
      emptyState(
        "error",
        "Research could not finish",
        error.message,
        el("button", { class: "btn btn-outlined btn-sm", onclick: () => runResearch(name, days) }, [
          icon("refresh"),
          "Try again",
        ])
      )
    );
    snack.show(error.message, "error");
  } finally {
    busy(heroBtn, false);
    endRun();
  }
}

/* `navigate:false` preloads a niche without stealing the current view — boot uses
   it so a deep link like /app#packages still lands on Packages. */
async function openNiche(id, { silent = false, navigate = true } = {}) {
  if (!id) return;
  state.nicheId = id;
  syncSelects();
  renderRail();
  if (navigate) goto("research", { push: true });
  showResults();
  cohortSkeleton();
  $("#statsRow").textContent = "";

  try {
    const data = await api(`/api/niches/${id}`);
    const niche = data.niche || {};
    const videos = data.videos || [];
    const summary = withDerived(patternsToSummary(data.patterns), videos);

    $("#resTitle").textContent = niche.name || id;

    if (!videos.length) {
      $("#resMeta").textContent = "";
      $("#statsRow").textContent = "";
      fill(
        $("#cohortList"),
        emptyState(
          "insights",
          "This niche has not been researched",
          "Run it once and the ranked cohort, hooks and keywords appear here.",
          el("button", {
            class: "btn btn-filled btn-sm",
            onclick: () => runResearch(niche.name || id, niche.window_days || state.windowDays),
          }, [icon("insights"), "Run research"])
        )
      );
      renderHookMix(null);
      renderKeywords(null);
      renderFacts(null, []);
      renderHooks([]);
      return;
    }

    renderResearch(
      niche.name || id,
      [
        `${videos.length} videos`,
        `${niche.window_days || "—"}d window`,
        `${niche.total_runs || 0} run${niche.total_runs === 1 ? "" : "s"}`,
        `refreshed ${fmtAgo(niche.last_research_at)}`,
      ],
      videos,
      data.hooks || [],
      summary
    );
    if (!silent) snack.show(`Loaded ${niche.name || id} from the library.`);
  } catch (error) {
    snack.show(error.message, "error");
    fill($("#cohortList"), emptyState("error", "Could not load this niche", error.message));
  }
}

async function refreshCurrent(button) {
  if (!state.nicheId) {
    snack.show("Open a niche first.", "error");
    return;
  }
  busy(button, true);
  try {
    const result = await api(`/api/niches/${state.nicheId}/refresh`, { method: "POST" });
    await openNiche(state.nicheId, { silent: true });
    snack.show(`Re-pulled ${result.refreshed} videos. Hooks re-ranked.`, "good");
  } catch (error) {
    snack.show(error.message, "error");
  } finally {
    busy(button, false);
  }
}

/* ── story studio: chat ───────────────────────────────────────────────── */

const chatLog = [];

function chatScroll() {
  const body = $("#chatScroll");
  if (body) body.scrollTop = body.scrollHeight;
}

function autosizeTextarea() {
  const el = $("#chatText");
  if (!el) return;
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 200) + "px";
}

function appendChatBubble(role, text, store = true) {
  const host = $("#chatLog");
  if (!host) return;
  if (host.querySelector(".chat-empty")) host.textContent = "";
  if (store) chatLog.push({ role, content: text });
  const avatar = role === "user"
    ? null
    : el("span", { class: "msg-avatar msg-avatar-ai" }, [icon("sparkle", "ic")]);
  const actions = [];
  if (role === "ai") {
    actions.push(
      el("button", { class: "btn btn-text btn-sm", onclick: () => copy(text, "Script copied") },
        [icon("copy"), "Copy"]),
      el("button", { class: "btn btn-text btn-sm", onclick: (e) => buildKit(text, e.currentTarget) },
        [icon("package"), "Upload-ready kit"])
    );
  }
  const bubble = el("div", { class: `msg msg-${role}` }, [
    avatar,
    el("div", { class: "msg-main" }, [
      role === "user" ? null : el("div", { class: "msg-name", text: "Story AI" }),
      el("div", { class: "msg-text", text }),
      actions.length
        ? el("div", { class: "msg-actions" }, actions)
        : null,
    ]),
  ]);
  host.appendChild(bubble);
  chatScroll();
}

function chatNicheId() {
  const picked = $("#genNiche") ? $("#genNiche").value : "";
  return picked || state.nicheId || "";
}

async function buildKit(script, button) {
  const nicheId = chatNicheId();
  if (!nicheId) {
    snack.show("Choose a niche in the chat bar first — the kit needs niche research.", "error");
    return;
  }
  if (button) busy(button, true);
  try {
    const data = await api("/api/story/kit", {
      method: "POST",
      body: JSON.stringify({ niche_id: nicheId, script }),
    });
    renderKit(data.package);
    $("#kitSheet").showModal();
    snack.show("Upload-ready kit saved to the library.", "good");
  } catch (error) {
    snack.show(error.message, "error");
  } finally {
    if (button) busy(button, false);
  }
}

function renderKit(pkg) {
  const body = $("#kitBody");
  if (!body) return;
  const titles = pkg.titles || [];
  const box = el("div", {});
  box.appendChild(
    el("div", { class: "kit-section" }, [
      el("h4", { class: "kit-title", text: "Title variants" }),
      ...titles.map((t, i) =>
        el("div", { class: "kit-row" }, [
          el("span", { class: "kit-rank", text: `${i + 1}` }),
          el("span", { class: "kit-text", text: decodeHtml(t.title) }),
          el("span", { class: "tag", text: `~${t.ctr_estimate}%` }),
          el("button", { class: "btn btn-text btn-sm", onclick: () => copy(t.title, "Title copied") },
            [icon("copy"), "Copy"]),
        ])
      ),
    ])
  );
  box.appendChild(
    el("div", { class: "kit-section" }, [
      el("h4", { class: "kit-title", text: "Description" }),
      el("div", { class: "kit-desc", text: pkg.summary || "" }),
      el("div", { class: "kit-row kit-row-right" }, [
        el("button", { class: "btn btn-text btn-sm", onclick: () => copy(pkg.summary, "Description copied") },
          [icon("copy"), "Copy description"]),
      ]),
    ])
  );
  box.appendChild(
    el("div", { class: "kit-section" }, [
      el("h4", { class: "kit-title", text: "Tags" }),
      el("div", { class: "kit-tags" },
        (pkg.tags || []).map((t) => el("span", { class: "tag tag-lg", text: t }))),
      el("div", { class: "kit-row kit-row-right" }, [
        el("button", { class: "btn btn-text btn-sm", onclick: () => copy((pkg.tags || []).join(", "), "Tags copied") },
          [icon("copy"), "Copy tags"]),
      ]),
    ])
  );
  fill(body, box);
}

function showTyping() {
  const host = $("#chatLog");
  if (!host) return;
  if (host.querySelector(".chat-typing")) return;
  host.appendChild(
    el("div", { class: "msg msg-ai" }, [
      el("span", { class: "msg-avatar msg-avatar-ai" }, [icon("sparkle", "ic")]),
      el("div", { class: "msg-main" }, [
        el("div", { class: "msg-name", text: "Story AI" }),
        el("div", { class: "chat-typing" }, [
          el("i"), el("i"), el("i"),
        ]),
      ]),
    ])
  );
  chatScroll();
}

function hideTyping() {
  const t = $("#chatLog .chat-typing");
  if (t) t.closest(".msg").remove();
}

async function sendChat(event) {
  event.preventDefault();
  if (chatPending) return;
  const input = $("#chatText");
  const text = input.value.trim();
  if (!text) return;
  if (isGibberish(text)) {
    snack.show("That looks like random characters — describe a story idea instead.", "error");
    return;
  }
  input.value = "";
  autosizeTextarea();
  appendChatBubble("user", text);
  const button = $("#chatSend");
  busy(button, true);
  chatPending = true;
  showTyping();
  try {
    const data = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        messages: chatLog.slice(-12),
        niche: chatNicheId() || null,
      }),
    });
    hideTyping();
    appendChatBubble("ai", data.reply || "No reply.");
  } catch (error) {
    hideTyping();
    appendChatBubble("ai", `⚠ ${error.message}`, false);
  } finally {
    busy(button, false);
    chatPending = false;
    chatScroll();
  }
}

let chatPending = false;

function isGibberish(text) {
  const t = text.trim();
  if (t.length < 3) return true;
  if (/^(\w)\1{2,}$/.test(t)) return true;
  if (/(asdf|qwer|wert|sdfg|zxcv|xcvb|hjkl|fghj|tyui|vbn|jkl|xyz)/i.test(t)) return true;
  const letters = t.replace(/[^a-zA-Z]/g, "");
  const words = letters.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  for (const w of words) {
    if (w.length >= 5) {
      const vowels = new Set(w.match(/[aeiouy]/g) || []);
      let hasBigram = false;
      for (let i = 0; i < w.length - 1; i++) {
        if ("th he in er an re on at en nd ti es or te of ed is it al ar st to nt ng se ha as ou io le ve co me de hi ri ro ic ne im ly ra la di si el ea ns ll ec ie us un ch wh ck gh ph sh br gr pl fl dr tr pr sp sk sm sn bl cr fr gl sl sw cl ft mp lt pt rd rg rk rl rm rn rp rr rt rv ry".split(" ").includes(w.slice(i, i + 2))) {
          hasBigram = true;
          break;
        }
      }
      if (vowels.size < 2 && !hasBigram) return true;
    }
  }
  return false;
}

function openScriptInChat(script) {
  chatLog.length = 0;
  $("#chatLog").textContent = "";
  appendChatBubble("ai", script || "No script in this package.");
  goto("packages");
}


/* ── library ─────────────────────────────────────────────────────────── */

async function loadLibrary(nicheId) {
  if (!nicheId) {
    $("#libHookCount").textContent = "";
    $("#libPkgCount").textContent = "";
    fill(
      $("#libHooks"),
      emptyState("library", "No niche selected",
        "Pick a niche above to open its hook library.")
    );
    fill(
      $("#libPackages"),
      emptyState("package", "No niche selected",
        "Pick a niche above to see its upload-ready kits.")
    );
    return;
  }
  try {
    const [hooksData, pkgData] = await Promise.all([
      api(`/api/niches/${nicheId}/hooks`),
      api(`/api/niches/${nicheId}/packages`),
    ]);

    const hooks = hooksData.hooks || [];
    $("#libHookCount").textContent = hooks.length ? `${hooks.length}` : "";
    const hookHost = $("#libHooks");
    if (!hooks.length) {
      fill(hookHost, emptyState("bulb", "No hooks yet", "Run research on this niche to build the hook library."));
    } else {
      renderHookPager(hookHost, hooks, 8);
    }

    const packages = pkgData.packages || [];
    $("#libPkgCount").textContent = packages.length ? `${packages.length}` : "";
    const pkgHost = $("#libPackages");
    if (!packages.length) {
      fill(pkgHost, emptyState(
        "package",
        "No kits yet",
        "Write a story in the Story studio, then hit \"Upload-ready kit\" under the reply to get titles, description and tags.",
        el("button", {
          class: "btn btn-filled",
          style: "margin-top:12px",
          onclick: () => goto("packages"),
        }, [icon("script"), "Write a story"])
      ));
    } else {
      const box = el("div", {});
      packages.forEach((pkg) => {
        const first = decodeHtml((pkg.titles && pkg.titles[0] && pkg.titles[0].title)) || "Package";
        box.appendChild(
          el("div", { class: "saved-pkg" }, [
            el("span", { class: "sp-title", text: first }),
            el("span", { class: "sp-row" }, [
              el("span", { class: "tag", text: `${(pkg.titles || []).length} titles` }),
              el("span", { class: "tag", text: fmtDate(pkg.created_at) }),
              el("button", {
                class: "btn btn-text btn-sm",
                style: "margin-left:auto",
                onclick: () => { renderKit(pkg); $("#kitSheet").showModal(); },
              }, [icon("package"), "View kit"]),
              el("button", {
                class: "btn btn-text btn-sm",
                onclick: () => openScriptInChat(pkg.script),
              }, [icon("external"), "Open script"]),
            ]),
          ])
        );
      });
      fill(pkgHost, box);
    }
  } catch (error) {
    snack.show(error.message, "error");
  }
}

async function refreshLibrary(button) {
  const nicheId = $("#libNiche").value;
  if (!nicheId) {
    snack.show("Choose a niche to refresh.", "error");
    return;
  }
  busy(button, true);
  try {
    const result = await api(`/api/niches/${nicheId}/refresh`, { method: "POST" });
    await loadLibrary(nicheId);
    /* refresh the research view in place — the user stays in Library */
    if (state.nicheId === nicheId) await openNiche(nicheId, { silent: true, navigate: false });
    snack.show(`Re-pulled ${result.refreshed} videos. Hooks re-ranked.`, "good");
  } catch (error) {
    snack.show(error.message, "error");
  } finally {
    busy(button, false);
  }
}

/* ── events ──────────────────────────────────────────────────────────── */

$("#menuBtn").addEventListener("click", toggleNav);
$("#scrim").addEventListener("click", closeDrawer);
$("#themeBtn").addEventListener("click", toggleTheme);
$("#helpBtn").addEventListener("click", () => $("#shortcuts").showModal());
$("#shortcutsClose").addEventListener("click", () => $("#shortcuts").close());

$$(".nav-item").forEach((button) =>
  button.addEventListener("click", () => goto(button.dataset.view))
);

$("#omniForm").addEventListener("submit", (event) => {
  event.preventDefault();
  goto("research");
  const value = $("#omniInput").value;
  $("#heroInput").value = value;
  runResearch(value, state.windowDays);
});

$("#heroForm").addEventListener("submit", (event) => {
  event.preventDefault();
  const value = $("#heroInput").value;
  $("#omniInput").value = value;
  runResearch(value, state.windowDays);
});

$$("#windowGroup button").forEach((button) =>
  button.addEventListener("click", () => {
    state.windowDays = Number(button.dataset.days) || 90;
    $$("#windowGroup button").forEach((other) =>
      other.setAttribute("aria-pressed", other === button ? "true" : "false")
    );
  })
);

$$(".suggest .chip").forEach((chip) =>
  chip.addEventListener("click", () => {
    const value = chip.dataset.niche;
    $("#heroInput").value = value;
    $("#omniInput").value = value;
    runResearch(value, state.windowDays);
  })
);

$("#backToSearch").addEventListener("click", () => {
  showIdle();
  $("#heroInput").focus();
});

$("#resRefresh").addEventListener("click", (event) => refreshCurrent(event.currentTarget));

$("#resPackage").addEventListener("click", () => {
  goto("packages");
  const chat = $("#chatText");
  if (chat) chat.focus();
});

$("#reloadNiches").addEventListener("click", async (event) => {
  busy(event.currentTarget, true);
  try {
    await loadNiches();
    snack.show("Niche list reloaded.", "good");
  } catch (error) {
    snack.show(error.message, "error");
  } finally {
    busy(event.currentTarget, false);
  }
});

$("#chatForm").addEventListener("submit", sendChat);

$("#libNiche").addEventListener("change", (event) => {
  if (event.target.value) loadLibrary(event.target.value);
});

$("#refreshBtn").addEventListener("click", (event) => refreshLibrary(event.currentTarget));

window.addEventListener("scroll", () => {
  $("#appbar").dataset.scrolled = window.scrollY > 4 ? "true" : "false";
}, { passive: true });

window.addEventListener("hashchange", () => goto(currentView(), { push: false }));

window.addEventListener("resize", () => {
  if (!drawerMode()) closeDrawer();
});

window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (!document.documentElement.dataset.theme) paintThemeIcon();
});

/* keyboard shortcuts */
let pendingG = false;
document.addEventListener("keydown", (event) => {
  const target = event.target;
  const typing =
    target instanceof HTMLElement &&
    (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable);

  if (event.key === "Escape") {
    closeDrawer();
    return;
  }
  if (typing || event.metaKey || event.ctrlKey || event.altKey) return;

  if (event.key === "/") {
    event.preventDefault();
    $("#omniInput").focus();
    $("#omniInput").select();
    return;
  }
  if (event.key === "?") {
    event.preventDefault();
    $("#shortcuts").showModal();
    return;
  }
  if (event.key === "t") {
    toggleTheme();
    return;
  }
  if (event.key === "[") {
    toggleNav();
    return;
  }
  if (event.key === "g") {
    pendingG = true;
    setTimeout(() => (pendingG = false), 900);
    return;
  }
  if (pendingG) {
    pendingG = false;
    if (event.key === "r") goto("research");
    if (event.key === "p") goto("packages");
    if (event.key === "l") goto("library");
  }
});

/* textarea: Enter sends, Shift+Enter newline, autosize */
$("#chatText").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("#chatForm").requestSubmit();
  }
});
$("#chatText").addEventListener("input", autosizeTextarea);
$$(".chat-suggest .chip").forEach((chip) =>
  chip.addEventListener("click", () => {
    $("#chatText").value = chip.dataset.story;
    $("#chatForm").requestSubmit();
  })
);
$("#genNiche").addEventListener("change", (event) => {
  const n = state.niches.find((x) => x.id === event.target.value);
  $("#chatNicheTag").textContent = n ? n.name : "Free chat";
});

/* ── boot ────────────────────────────────────────────────────────────── */

(async function boot() {
  paintThemeIcon();
  goto(currentView(), { push: false });
  loadHealth();

  try {
    await loadNiches();
    showIdle();
    $("#heroInput").focus();
  } catch (error) {
    snack.show(error.message, "error");
    showIdle();
  }
})();





