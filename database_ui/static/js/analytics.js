// database_ui/static/js/analytics.js
// Renders the weekly report: fetches JSON, draws lightweight inline-SVG charts.
(function () {
  "use strict";
  const SVG = "http://www.w3.org/2000/svg";
  const $ = (id) => document.getElementById(id);

  function el(tag, attrs, kids) {
    const n = attrs && attrs._svg ? document.createElementNS(SVG, tag) : document.createElement(tag);
    for (const k in (attrs || {})) if (k !== "_svg") n.setAttribute(k, attrs[k]);
    (kids || []).forEach((c) => n.appendChild(typeof c === "string" ? document.createTextNode(c) : c));
    return n;
  }

  const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  // Expand a { "YYYY-MM-DD": value } map into the full Sun–Sat week starting at
  // sundayKey, filling absent days with 0 so every week charts the same seven
  // slots. All date math is in UTC (the keys are date-only) to avoid DST drift.
  function weekSeries(byDay, sundayKey, unit) {
    const [y, m, d] = sundayKey.split("-").map(Number);
    const base = Date.UTC(y, m - 1, d);
    return DOW.map((name, i) => {
      const dt = new Date(base + i * 86400000);
      const iso = dt.toISOString().slice(0, 10);
      const value = byDay[iso] || 0;
      return { label: name, value, title: `${name}, ${MON[dt.getUTCMonth()]} ${dt.getUTCDate()} · ${value} ${unit}` };
    });
  }

  // A "nice" round axis ceiling that clears the data max with one empty step of
  // headroom above the tallest bar (e.g. max 8 → ceiling 10, step 2).
  function niceScale(m) {
    m = Math.max(1, m);
    const pow = Math.pow(10, Math.floor(Math.log10(m)));
    let step = pow;
    for (const s of [1, 2, 5, 10]) {
      step = s * pow;
      if (m / step <= 4) break;
    }
    let ceil = Math.ceil(m / step) * step;
    if (ceil <= m) ceil += step;   // guarantee the empty top layer
    return { ceil, step };
  }

  // Accessible bar chart from [{label, value, title}]. Faint horizontal
  // gridlines with left-edge value ticks; top-rounded bars (square bottom);
  // each bar carries a native <title> tooltip.
  function barChart(data, opts) {
    opts = opts || {};
    const w = 520, h = 220, padX = 30, padTop = 20, padBot = 26;
    const plotH = h - padTop - padBot, baseY = padTop + plotH;
    const n = data.length || 1;
    const max = Math.max(1, ...data.map((d) => d.value));
    const { ceil, step } = niceScale(max);
    const slot = (w - padX * 2) / n, bw = slot * 0.6;
    const svg = el("svg", { _svg: true, viewBox: `0 0 ${w} ${h}`, class: "chart", role: "img",
      "aria-label": opts.label || "Bar chart" });

    const TICKS = Math.round(ceil / step);
    for (let t = 0; t <= TICKS; t++) {
      const gy = padTop + plotH * (t / TICKS);
      svg.appendChild(el("line", { _svg: true, x1: padX, y1: gy, x2: w - padX, y2: gy, class: "chart-grid" }));
      svg.appendChild(el("text", { _svg: true, x: padX - 6, y: gy + 3, "text-anchor": "end", class: "chart-lbl" },
        [String(Math.round(ceil - step * t))]));
    }

    data.forEach((d, i) => {
      const x = padX + i * slot + (slot - bw) / 2;
      const bh = plotH * (d.value / ceil);
      const y = baseY - bh;
      const r = Math.min(4, bw / 2, bh);
      // Path with rounded upper corners only, so bars sit flat on the baseline.
      const path = `M${x},${baseY} L${x},${y + r} Q${x},${y} ${x + r},${y}`
        + ` L${x + bw - r},${y} Q${x + bw},${y} ${x + bw},${y + r} L${x + bw},${baseY} Z`;
      const bar = el("path", { _svg: true, d: path, fill: "var(--accent)" });
      bar.appendChild(el("title", { _svg: true }, [d.title || `${d.label}: ${d.value}`]));
      svg.appendChild(bar);
      svg.appendChild(el("text", { _svg: true, x: x + bw / 2, y: y - 4, "text-anchor": "middle", class: "chart-val" }, [String(d.value)]));
      svg.appendChild(el("text", { _svg: true, x: x + bw / 2, y: h - 8, "text-anchor": "middle", class: "chart-lbl" }, [d.label]));
    });
    return svg;
  }

  function card(title, body, titleExtra) {
    const c = el("div", { class: "a-card" });
    if (title) {
      const h = el("h2", { class: "a-card-title" }, [title]);
      if (titleExtra) h.appendChild(titleExtra);   // e.g. the Flagged card's (i)
      c.appendChild(h);
    }
    c.appendChild(body);
    return c;
  }

  function statList(pairs) {
    const ul = el("ul", { class: "a-stats" });
    pairs.forEach(([k, v]) => {
      const li = el("li");
      li.appendChild(el("span", { class: "a-stat-k" }, [k]));
      li.appendChild(el("span", { class: "a-stat-v" }, [String(v)]));
      ul.appendChild(li);
    });
    return ul;
  }

  function money(x) { return "$" + (x || 0).toFixed(2); }
  function arrow(wow, key) { return (wow && wow[key] && wow[key].arrow) || ""; }

  // A stroked chevron in a 24×24 viewBox, matching the picker caret. Used for
  // the borderless week-nav arrows (the caret path, rotated sideways).
  function svgChevron(d, cls) {
    const svg = el("svg", { _svg: true, class: cls, viewBox: "0 0 24 24",
      width: "16", height: "16", "aria-hidden": "true" });
    svg.appendChild(el("path", { _svg: true, d, fill: "none", stroke: "currentColor",
      "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round" }));
    return svg;
  }

  // The charts draw text inside a scaled viewBox, so a fixed SVG font-size
  // renders larger on screen and drifts with width. Size the label + value text
  // in SVG units from each chart's real render scale so they land at an exact
  // on-screen rem: day/axis labels at 0.8rem (like the stat keys), bar-top
  // values at 0.92rem (like the AI-review body). Re-run on resize.
  function sizeChartText() {
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    document.querySelectorAll("#analytics-content .chart").forEach((svg) => {
      const vb = (svg.viewBox && svg.viewBox.baseVal && svg.viewBox.baseVal.width) || 520;
      const shown = svg.getBoundingClientRect().width;
      if (!shown) return;
      const scale = vb / shown;   // SVG user units per on-screen pixel
      // Read the report's font-size tokens (rem multiples) so axis/day labels
      // track --fs-label and the bar-top values track --fs-body — one source of
      // truth in analytics.css rather than magic numbers duplicated here.
      const cs = getComputedStyle(svg);
      const lblRem = parseFloat(cs.getPropertyValue("--fs-label")) || 0.8;
      const valRem = parseFloat(cs.getPropertyValue("--fs-body")) || 0.92;
      svg.style.setProperty("--chart-lbl-size", (lblRem * rem * scale).toFixed(2) + "px");
      svg.style.setProperty("--chart-val-size", (valRem * rem * scale).toFixed(2) + "px");
    });
  }

  // One flagged conversation, e.g.
  // "28/40 (Practice 7 · Aug 17 · 2 messages) — <overview>". Only the label
  // inside the parentheses is the blue, clickable open-link; the parentheses
  // themselves stay in the line's base color and aren't clickable.
  function flagLine(id, c, m) {
    const g = c.grade || null;
    const score = g && typeof g.total_score === "number"
      ? g.total_score + "/" + (g.max_score || 40) : "—";
    const overview = (g && g.overview) || c.one_line || "";
    const p = el("p", { class: "a-flag" });
    p.appendChild(el("span", { class: "a-flag-score" }, [score]));
    p.appendChild(document.createTextNode(" ("));
    const link = el("button", { type: "button", class: "a-flag-open" }, [flagLabel(m)]);
    link.addEventListener("click", () => openFlagged(id));
    p.appendChild(link);
    p.appendChild(document.createTextNode(")"));
    if (overview) {
      p.appendChild(document.createTextNode(" — "));
      p.appendChild(el("span", { class: "a-flag-text" }, [overview]));
    }
    return p;
  }

  // "Practice 7 · Aug 17 · 2 messages" from live meta — mirrors database.js's
  // formatEntryHeader (minus the running cost). Falls back to a bare label when
  // the conversation's live metadata is unavailable.
  function flagLabel(m) {
    if (!m) return "open conversation";
    const num = parseInt(m.exercise_number, 10);
    const kind = m.exercise_kind === "practice" ? "Practice" : "Exercise";
    const parts = [kind + " " + (Number.isFinite(num) ? num : m.exercise_number)];
    if (m.last_active_at) {
      const d = new Date(m.last_active_at);
      parts.push(d.toLocaleDateString(undefined, { month: "short", day: "numeric" }));
    }
    const n = m.message_count;
    if (typeof n === "number") parts.push(n + (n === 1 ? " message" : " messages"));
    return parts.join(" · ");
  }

  // Open a flagged conversation. database.js exposes an opener that swaps the
  // transcript in-place; fall back to a home deep link if it isn't wired yet.
  function openFlagged(id) {
    if (window.DatabaseReview && typeof window.DatabaseReview.open === "function") {
      window.DatabaseReview.open(id);
    } else {
      window.location.href = "/?c=" + encodeURIComponent(id);
    }
  }

  // ---- Rubric popup: the (i) on the Flagged card title -------------------
  // Every flagged conversation is scored against one global rubric (the judge's
  // default), so a single (i) on the card heading opens it — not one per line.

  // A quiet circle-i glyph, drawn in a 24×24 viewBox to match the picker carets.
  function infoCircleSvg() {
    const svg = el("svg", { _svg: true, class: "a-info-icon", viewBox: "0 0 24 24",
      width: "15", height: "15", "aria-hidden": "true" });
    svg.appendChild(el("circle", { _svg: true, cx: "12", cy: "12", r: "9",
      fill: "none", stroke: "currentColor", "stroke-width": "2" }));
    svg.appendChild(el("line", { _svg: true, x1: "12", y1: "11", x2: "12", y2: "16.5",
      stroke: "currentColor", "stroke-width": "2", "stroke-linecap": "round" }));
    svg.appendChild(el("circle", { _svg: true, cx: "12", cy: "7.5", r: "1.25",
      fill: "currentColor" }));
    return svg;
  }
  function rubricInfoButton() {
    const b = el("button", { type: "button", class: "a-info",
      title: "View rubric", "aria-label": "View rubric" }, [infoCircleSvg()]);
    b.addEventListener("click", openRubric);
    return b;
  }

  // Render our own trusted rubric markdown with the vendored marked + DOMPurify
  // (both hosts load them). Returns null when the libs are absent, so the caller
  // can fall back to plain preformatted text.
  function mdToHtml(md) {
    const m = window.marked;
    let html = null;
    if (m && typeof m.parse === "function") html = m.parse(md);
    else if (typeof m === "function") html = m(md);
    if (html == null) return null;
    return window.DOMPurify ? window.DOMPurify.sanitize(html) : html;
  }

  let rubricCache = null;      // { title, markdown, html } — fetched once, reused
  let rubricOverlay = null;

  // Show only the scored criteria in the popup: drop the file's H1 title and
  // intro blurb (everything before the first "## " section) and the trailing
  // "## Summary" points table. The rubric file itself is unchanged — this is a
  // display-only slice, so the judge still grades against the full document.
  function rubricBodyMarkdown(md) {
    const lines = (md || "").split("\n");
    let start = lines.findIndex((l) => /^##\s+/.test(l));
    if (start < 0) start = 0;
    let end = lines.findIndex((l, i) => i > start && /^##\s+summary\b/i.test(l));
    if (end < 0) end = lines.length;
    // Trim trailing blank lines and a horizontal rule left before the summary.
    while (end > start && /^\s*(-{3,}\s*)?$/.test(lines[end - 1])) end--;
    return lines.slice(start, end).join("\n");
  }

  function paintRubric() {
    rubricOverlay.querySelector(".a-modal-title").textContent = rubricCache.title;
    const body = rubricOverlay.querySelector(".a-modal-body");
    if (rubricCache.html != null) {
      body.innerHTML = rubricCache.html;
    } else {
      body.textContent = "";
      body.appendChild(el("pre", { class: "a-rubric-pre" }, [rubricCache.markdown]));
    }
  }

  // Escape closes the popup first. Capture phase + stopPropagation so it beats
  // database.js's bubble-phase Escape (sidebar/report) and the standalone page's
  // Escape (back to conversations) — neither fires while the rubric is open.
  function onRubricKey(e) {
    if (e.key !== "Escape") return;
    e.stopPropagation();
    e.preventDefault();
    hideRubric();
  }

  function ensureRubricOverlay() {
    if (rubricOverlay) return rubricOverlay;
    const overlay = el("div", { class: "a-modal-overlay", hidden: "" });
    const cardEl = el("div", { class: "a-modal-card", role: "dialog",
      "aria-modal": "true", "aria-label": "Rubric" });
    const head = el("div", { class: "a-modal-head" });
    head.appendChild(el("h2", { class: "a-modal-title" }, ["Rubric"]));
    const close = el("button", { type: "button", class: "a-modal-close",
      "aria-label": "Close" }, ["×"]);
    close.addEventListener("click", hideRubric);
    head.appendChild(close);
    cardEl.appendChild(head);
    cardEl.appendChild(el("div", { class: "a-modal-body a-rubric-md" }));
    overlay.appendChild(cardEl);
    // Backdrop click (outside the card) closes; clicks on the card don't.
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) hideRubric(); });
    // Mount inside the analytics container so the --fs-* type tokens (scoped to
    // .analytics / .analytics-panel) resolve; the overlay is fixed, so it still
    // covers the viewport regardless of which host it lives in.
    const host = $("analytics-root") || $("analytics-panel") || document.body;
    host.appendChild(overlay);
    rubricOverlay = overlay;
    return overlay;
  }

  async function openRubric() {
    const overlay = ensureRubricOverlay();
    overlay.removeAttribute("hidden");
    document.addEventListener("keydown", onRubricKey, true);
    if (rubricCache) { paintRubric(); return; }
    overlay.querySelector(".a-modal-body").textContent = "Loading…";
    try {
      const r = await fetch("/api/analytics/rubric");
      if (!r.ok) throw new Error("rubric unavailable");
      const data = await r.json();
      const md = rubricBodyMarkdown(data.markdown || "");
      rubricCache = {
        title: "Rubric",
        markdown: md,
        html: mdToHtml(md),
      };
      paintRubric();
    } catch (e) {
      const body = overlay.querySelector(".a-modal-body");
      body.textContent = "";
      body.appendChild(el("p", { class: "a-rubric-error" }, ["Couldn't load the rubric"]));
    }
  }

  function hideRubric() {
    if (!rubricOverlay) return;
    rubricOverlay.setAttribute("hidden", "");
    document.removeEventListener("keydown", onRubricKey, true);
  }

  function render(payload) {
    const root = $("analytics-content");
    root.textContent = "";
    const s = payload.live, wow = s.week_over_week || {};
    const u = s.usage, co = s.cost;

    root.appendChild(card(null, statList([
      ["Conversations", u.conversations + " " + arrow(wow, "conversations")],
      ["Messages", u.total_messages + " " + arrow(wow, "total_messages")],
      ["Students", u.unique_students + " " + arrow(wow, "unique_students")],
      ["New students", u.new_students + " " + arrow(wow, "new_students")],
      ["Cost", money(co.total_usd) + " " + arrow(wow, "cost_usd")],
    ])));

    const byDay = weekSeries(u.messages_by_day || {}, payload.week.key, "messages");
    root.appendChild(card("Daily activity", barChart(byDay, { label: "Daily message activity, Sunday through Saturday" })));

    // AI review sits under Daily activity: the week's narrative overview, one
    // paragraph per course, scoped on read so a course login sees only its own.
    // Like the Flagged card, the whole card is dropped when there's nothing to
    // show — before the week's cache exists, or when no course had enough
    // activity to review — rather than showing a placeholder note.
    const reviews = (payload.cached && payload.cached.ai_review_by_course) || {};
    const reviewedCourses = Object.keys(reviews);
    if (reviewedCourses.length > 0) {
      const names = payload.course_names || {};
      const rBody = el("div");
      reviewedCourses.forEach((course) => {
        rBody.appendChild(el("p", { class: "a-review-course" }, [names[course] || course]));
        rBody.appendChild(el("p", { class: "a-review" }, [reviews[course]]));
      });
      root.appendChild(card("AI review", rBody));
    }

    // Flags: judged conversations that didn't work well — shown to every login.
    // The server course-filters the cache, so a scoped login only ever gets its
    // own courses' flags. Nothing to show until the week's cache exists, and the
    // whole card is dropped when there's nothing flagged (no empty card).
    if (payload.cached) {
      const flags = Object.entries(payload.cached.conversations || {})
        .filter((e) => !e[1].worked_well);
      if (flags.length > 0) {
        const names = payload.course_names || {};
        const meta = payload.conversation_meta || {};
        const flagBody = el("div");
        // Group by course under a quiet uppercase course eyebrow, mirroring the
        // AI-review layout — so the per-line course name drops out.
        const order = [];               // course keys in first-seen order
        const byCourse = new Map();
        flags.forEach((e) => {
          const key = e[1].course || "";
          if (!byCourse.has(key)) { byCourse.set(key, []); order.push(key); }
          byCourse.get(key).push(e);
        });
        order.forEach((course) => {
          flagBody.appendChild(el("p", { class: "a-review-course" }, [names[course] || course]));
          byCourse.get(course).forEach((e) => flagBody.appendChild(flagLine(e[0], e[1], meta[e[0]])));
        });
        root.appendChild(card("Flagged", flagBody, rubricInfoButton()));
      }
    }

    sizeChartText();   // match chart text to the on-screen rem sizes above
  }

  // Current selection shared by the week nav and the course dropdown, so either
  // control can reload the report while preserving the other's choice.
  let currentWeek = null;
  // Selected course keys. Set to every course in scope once the picker loads;
  // an empty array is an invalid state the picker guards against (it shows the
  // "Select at least one course" error and does not reload).
  let currentCourses = [];
  let allCourseKeys = [];   // every selectable course — used to detect "all selected"

  function setStatus(text, isError) {
    const s = $("analytics-status");
    if (!s) return;
    s.textContent = text || "";
    s.classList.toggle("is-error", !!isError);
  }

  // Build the ?course= params for the current selection. When every course is
  // selected we send none, so the server falls back to the login's full scope —
  // identical to the old "All courses" behavior. A strict subset sends one
  // course= per selected key.
  function courseParams() {
    if (!allCourseKeys.length) return [];
    if (currentCourses.length >= allCourseKeys.length) return [];
    return currentCourses.map((c) => "course=" + encodeURIComponent(c));
  }

  async function load(weekKey) {
    if (weekKey) currentWeek = weekKey;
    const params = [];
    if (currentWeek) params.push("week=" + encodeURIComponent(currentWeek));
    params.push(...courseParams());
    const q = params.length ? "?" + params.join("&") : "";
    const resp = await fetch("/api/analytics" + q);
    const payload = await resp.json();
    render(payload);
    setStatus("", false);
  }

  // ---- Week picker: a trigger that opens a small calendar popover ---------
  const WD = ["S", "M", "T", "W", "T", "F", "S"];
  const MONLONG = ["January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"];

  const dUTC = (y, m, d) => new Date(Date.UTC(y, m, d));
  const keyOf = (dt) => dt.toISOString().slice(0, 10);
  function parseKey(k) { const [y, m, d] = k.split("-").map(Number); return dUTC(y, m - 1, d); }
  const sundayOf = (dt) => new Date(dt.getTime() - dt.getUTCDay() * 86400000);
  function weekLabel(sun) {
    const sat = new Date(sun.getTime() + 6 * 86400000);
    return `${MON[sun.getUTCMonth()]} ${sun.getUTCDate()} — `
      + `${MON[sat.getUTCMonth()]} ${sat.getUTCDate()}, ${sat.getUTCFullYear()}`;
  }

  // Build the calendar popover. `range` = {min, max} week keys (Sundays); weeks
  // outside it are shown disabled. Selecting a week loads it and closes the pop.
  function setupPicker(range, initialKey) {
    const host = $("week-picker"), trigger = $("weekpick-trigger"), label = $("weekpick-label");
    let minKey = range.min, maxKey = range.max;
    let selected = initialKey;
    const sun0 = sundayOf(parseKey(selected));
    let viewY = sun0.getUTCFullYear(), viewM = sun0.getUTCMonth();

    const pop = el("div", { class: "weekpick-pop", role: "dialog", hidden: "" });
    host.appendChild(pop);

    // Prev/next week arrows flanking the trigger box. The box is moved into a
    // .weeknav wrapper so the arrows sit tight against it; each greys out when
    // stepping that way would leave the selectable range.
    const nav = el("div", { class: "weeknav" });
    const prevBtn = el("button", { type: "button", class: "weeknav-arrow", "aria-label": "Previous week" },
      [svgChevron("M15 6l-6 6 6 6", "weeknav-chev")]);
    const nextBtn = el("button", { type: "button", class: "weeknav-arrow", "aria-label": "Next week" },
      [svgChevron("M9 6l6 6-6 6", "weeknav-chev")]);
    host.parentNode.insertBefore(nav, host);
    nav.appendChild(prevBtn);
    nav.appendChild(host);          // moves the trigger box between the arrows
    nav.appendChild(nextBtn);
    const shiftKey = (days) =>
      keyOf(sundayOf(new Date(parseKey(selected).getTime() + days * 86400000)));
    function updateArrows() {
      prevBtn.disabled = shiftKey(-7) < minKey;
      nextBtn.disabled = shiftKey(7) > maxKey;
    }
    prevBtn.addEventListener("click", () => { const k = shiftKey(-7); if (k >= minKey) choose(k); });
    nextBtn.addEventListener("click", () => { const k = shiftKey(7); if (k <= maxKey) choose(k); });

    const ix = (y, m) => y * 12 + m;
    const monthIxOf = (k) => { const s = sundayOf(parseKey(k)); return ix(s.getUTCFullYear(), s.getUTCMonth()); };

    const setLabel = () => { label.textContent = weekLabel(sundayOf(parseKey(selected))); };
    // Picking a week updates the highlight and reloads but leaves the popover
    // open; only an outside click (onDoc) closes it.
    function choose(k) {
      selected = k;
      const s = sundayOf(parseKey(k));   // keep the calendar view on the chosen week's month
      viewY = s.getUTCFullYear();
      viewM = s.getUTCMonth();
      setLabel(); renderGrid(); load(k); updateArrows();
    }

    function renderGrid() {
      pop.textContent = "";
      const head = el("div", { class: "weekpick-head" });
      const prev = el("button", { type: "button", class: "weekpick-nav", "aria-label": "Previous month" }, ["‹"]);
      const next = el("button", { type: "button", class: "weekpick-nav", "aria-label": "Next month" }, ["›"]);
      const cur = ix(viewY, viewM);
      if (cur <= monthIxOf(minKey)) prev.setAttribute("disabled", "");
      if (cur >= monthIxOf(maxKey)) next.setAttribute("disabled", "");
      prev.addEventListener("click", () => { if (--viewM < 0) { viewM = 11; viewY--; } renderGrid(); });
      next.addEventListener("click", () => { if (++viewM > 11) { viewM = 0; viewY++; } renderGrid(); });
      head.appendChild(prev);
      head.appendChild(el("span", { class: "weekpick-month" }, [`${MONLONG[viewM]} ${viewY}`]));
      head.appendChild(next);
      pop.appendChild(head);

      const wd = el("div", { class: "weekpick-wd" });
      WD.forEach((c) => wd.appendChild(el("span", {}, [c])));
      pop.appendChild(wd);

      const lastOfMonth = dUTC(viewY, viewM + 1, 0);
      let sun = sundayOf(dUTC(viewY, viewM, 1));
      while (sun <= lastOfMonth) {
        const wkKey = keyOf(sun);
        const inRange = wkKey >= minKey && wkKey <= maxKey;
        const cls = "weekpick-week" + (wkKey === selected ? " is-selected" : "") + (inRange ? "" : " is-disabled");
        const row = el("div", { class: cls });
        for (let i = 0; i < 7; i++) {
          const day = new Date(sun.getTime() + i * 86400000);
          const off = day.getUTCMonth() !== viewM ? " is-off" : "";
          row.appendChild(el("span", { class: "weekpick-day" + off }, [String(day.getUTCDate())]));
        }
        if (inRange) { const k = wkKey; row.addEventListener("click", () => choose(k)); }
        pop.appendChild(row);
        sun = new Date(sun.getTime() + 7 * 86400000);
      }
    }

    function onDoc(e) { if (!host.contains(e.target)) closePop(); }
    function openPop() {
      renderGrid();
      pop.removeAttribute("hidden");
      trigger.setAttribute("aria-expanded", "true");
      document.addEventListener("mousedown", onDoc);
    }
    function closePop() {
      pop.setAttribute("hidden", "");
      trigger.setAttribute("aria-expanded", "false");
      document.removeEventListener("mousedown", onDoc);
    }
    trigger.addEventListener("click", () => (pop.hasAttribute("hidden") ? openPop() : closePop()));

    // Retighten the selectable range (e.g. when the course filter changes) and
    // clamp the selected week into it: if it now sits before the first eligible
    // week, snap to that first week; if after the last, snap to the last. The
    // calendar view follows so the picker shows the week it lands on. Returns
    // the (possibly changed) selected week key so the caller can load it.
    function setRange(r) {
      minKey = r.min;
      maxKey = r.max;
      if (selected < minKey) selected = minKey;
      else if (selected > maxKey) selected = maxKey;
      const s = sundayOf(parseKey(selected));
      viewY = s.getUTCFullYear();
      viewM = s.getUTCMonth();
      setLabel();
      renderGrid();
      updateArrows();
      return selected;
    }

    setLabel();
    updateArrows();
    return { setRange };
  }

  // Course filter: a multi-select dropdown that rescopes every card (stats, AI
  // review, flags) to the chosen courses. Mirrors the Download-data course
  // picker — every course starts selected ("All (N)"), clicking toggles each,
  // and applying an empty set is rejected with an error. Always shown when the
  // login has at least one course, so the control is consistent and discoverable
  // even for a single-course login.
  function setupCoursePicker(courses, picker) {
    const wk = $("week-picker");
    if (!wk || !courses || courses.length < 1) return;
    // Open on "all selected": the report lands on the full scope, matching the
    // old "All courses" default.
    allCourseKeys = courses.map((c) => c.key);
    currentCourses = allCourseKeys.slice();
    const checked = new Set(currentCourses);      // mutated as options toggle
    let appliedKey = currentCourses.slice().sort().join("|");   // last-applied selection

    const host = el("div", { class: "coursepick", id: "course-picker" });
    const trigger = el("button", { type: "button", class: "coursepick-trigger",
      "aria-haspopup": "listbox", "aria-expanded": "false" });
    const label = el("span", { class: "coursepick-label" }, [""]);
    trigger.appendChild(label);
    const caret = el("svg", { _svg: true, class: "weekpick-caret", viewBox: "0 0 24 24",
      width: "14", height: "14", "aria-hidden": "true" });
    caret.appendChild(el("path", { _svg: true, d: "M6 9l6 6 6-6", fill: "none",
      stroke: "currentColor", "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round" }));
    trigger.appendChild(caret);
    host.appendChild(trigger);
    const pop = el("div", { class: "coursepick-pop", role: "listbox",
      "aria-multiselectable": "true", hidden: "" });
    host.appendChild(pop);
    // Course picker sits on the LEFT of the bar; the week nav is pushed to the
    // right (analytics.css gives .weeknav margin-left:auto). Insert just before
    // the week-nav wrapper so, on the standalone page, it follows the back link.
    const navWrap = wk.parentNode;
    navWrap.parentNode.insertBefore(host, navWrap);

    // Inline validation message, shown just to the right of the course picker
    // (a light-blue pill) when the selection is emptied — not in the far-right
    // status line. Hidden until there's something to say.
    const errBox = el("span", { class: "coursepick-error", hidden: "" });
    navWrap.parentNode.insertBefore(errBox, navWrap);
    function setCourseError(msg) {
      errBox.textContent = msg || "";
      if (msg) errBox.removeAttribute("hidden");
      else errBox.setAttribute("hidden", "");
    }

    // Trigger label, mirroring the Download-data multi-select summary:
    // none -> "None", one -> that course, all -> "All (N)", else "N selected".
    function summary() {
      const n = checked.size;
      if (n === 0) return "None";
      if (n === 1) {
        const only = courses.find((c) => checked.has(c.key));
        return only ? only.name : "1 selected";
      }
      if (n === courses.length) return "All (" + n + ")";
      return n + " selected";
    }
    function paintLabel() { label.textContent = summary(); }

    function renderOpts() {
      pop.textContent = "";
      courses.forEach((c) => {
        const on = checked.has(c.key);
        const item = el("div",
          { class: "coursepick-opt" + (on ? " is-selected" : ""),
            role: "option", "aria-selected": on ? "true" : "false" },
          [c.name]);
        // Multi-select: a click toggles this course and keeps the list open
        // (stopPropagation) so several can be picked in one go. The report
        // reloads only when the dropdown closes with a changed selection.
        item.addEventListener("click", (e) => {
          e.stopPropagation();
          const now = !checked.has(c.key);
          if (now) checked.add(c.key); else checked.delete(c.key);
          item.classList.toggle("is-selected", now);
          item.setAttribute("aria-selected", now ? "true" : "false");
          paintLabel();
        });
        pop.appendChild(item);
      });
    }
    function onDoc(e) { if (!host.contains(e.target)) closePop(); }
    function openPop() {
      renderOpts();
      pop.removeAttribute("hidden");
      trigger.setAttribute("aria-expanded", "true");
      document.addEventListener("mousedown", onDoc);
    }
    async function closePop() {
      pop.setAttribute("hidden", "");
      trigger.setAttribute("aria-expanded", "false");
      document.removeEventListener("mousedown", onDoc);
      await applySelection();
    }
    trigger.addEventListener("click", () => (pop.hasAttribute("hidden") ? openPop() : closePop()));

    // Apply the (possibly changed) selection when the dropdown closes. Empty is
    // rejected with an error and no reload — the last valid report stays on
    // screen. An unchanged selection is a no-op.
    async function applySelection() {
      if (checked.size === 0) {
        setCourseError("Select at least one course");
        return;
      }
      setCourseError("");
      const key = Array.from(checked).sort().join("|");
      if (key === appliedKey) { setStatus("", false); return; }
      appliedKey = key;
      currentCourses = Array.from(checked);
      setStatus("", false);
      // Tighten the calendar range to the selected courses' data (all selected ⇒
      // the full login range). If the current week falls outside the new range,
      // setRange snaps it to the nearest eligible week (first if earlier, last
      // if later) and returns the week to load, so we never land on an empty
      // out-of-range report.
      let target = currentWeek;
      try {
        const qs = courseParams().join("&");
        const r = await fetch("/api/analytics/weeks" + (qs ? "?" + qs : ""));
        const data = await r.json();
        if (picker && data.range) target = picker.setRange(data.range);
      } catch (e) { /* keep the existing range if the refetch fails */ }
      load(target);
    }

    paintLabel();
  }

  async function initPicker() {
    const resp = await fetch("/api/analytics/weeks");
    const { range, courses } = await resp.json();
    const picker = setupPicker(range, range.max);
    setupCoursePicker(courses || [], picker);
    load(range.max);
  }

  // Fetch + build the picker at most once. Safe to call every time the report
  // is opened; a no-op after the first successful init.
  let inited = false;
  async function ensureInit() {
    if (inited || !$("week-picker")) return;
    inited = true;
    await initPicker();
  }

  // This module has a single host: the dashboard panel (index.html). It stays
  // dormant until database.js calls WeeklyReport.ensureInit() when the "Weekly
  // report" button is clicked; database.js owns Escape there.
  window.WeeklyReport = { ensureInit };
  window.addEventListener("resize", sizeChartText);
})();
