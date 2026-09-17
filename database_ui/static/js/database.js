"use strict";
// database_ui — read-only conversation browser. Lists every conversation in the
// DB and renders a selected one's transcript. No composer, no writes.
(function () {
  const sidebarList = document.getElementById("sidebar-list");
  const sidebarEmpty = document.getElementById("sidebar-empty");
  const messageList = document.getElementById("message-list");
  const placeholder = document.getElementById("review-placeholder");
  const errorBanner = document.getElementById("error-banner");
  const errorText = document.getElementById("error-text");
  const errorDismiss = document.getElementById("error-dismiss");
  const sidebar = document.getElementById("sidebar");
  const historyToggle = document.getElementById("history-toggle");
  const sidebarClose = document.getElementById("sidebar-close");
  const weeklyOpen = document.getElementById("weekly-report-open");
  const analyticsPanel = document.getElementById("analytics-panel");

  // Filter & sort bar (client-side over the loaded list; see applyView).
  const reviewToolbar = document.getElementById("review-toolbar");
  const sortTrigger = document.getElementById("sort-trigger");
  const sortPop = document.getElementById("sort-pop");
  const courseTrigger = document.getElementById("course-trigger");
  const coursePop = document.getElementById("course-pop");
  const flagToggle = document.getElementById("flag-toggle");

  let activeConversationId = null;
  // Every conversation from /api/conversations, kept so the toolbar can filter
  // and re-sort without re-fetching.
  let allConversations = [];
  // Distinct course codes present in the loaded list (set by buildCourseOptions).
  let allCourseKeys = [];
  // view.courses is a Set of selected course codes; null until first built, then
  // defaults to "all selected" (matching the weekly report's course picker).
  const view = { sort: "recent", courses: null, flaggedOnly: false };

  // Sidebar open/close toggle (mirrors the student app's behavior).
  function setSidebar(open) {
    sidebar.setAttribute("data-open", open ? "true" : "false");
  }
  if (historyToggle) historyToggle.addEventListener("click", () => setSidebar(true));
  if (sidebarClose) sidebarClose.addEventListener("click", () => setSidebar(false));

  // Swap the main pane between the transcript ("conversation") and the weekly
  // report ("report"). The panel toggles via the `hidden` property (chat.css
  // has `[hidden]{display:none!important}`, so inline display can't beat it);
  // #message-list toggles via inline display, which overrides chat.css's flex.
  function setView(view) {
    const report = view === "report";
    if (analyticsPanel) analyticsPanel.hidden = !report;
    if (messageList) messageList.style.display = report ? "none" : "";
  }
  function showReport() {
    activeConversationId = null;
    highlightActive();
    hideError();
    setView("report");
    if (window.WeeklyReport) window.WeeklyReport.ensureInit();
  }
  function hideReport() {
    setView("conversation");   // back to the transcript pane
  }
  if (weeklyOpen) {
    weeklyOpen.addEventListener("click", () => {
      showReport();   // render the report in-place in the dashboard
    });
  }
  // Selecting a conversation swaps the report back out (see loadConversation);
  // Escape does too (see the unified Escape handler below).

  function showError(msg) {
    errorText.textContent = msg;
    errorBanner.hidden = false;
  }
  function hideError() {
    errorBanner.hidden = true;
    errorText.textContent = "";
  }
  if (errorDismiss) errorDismiss.addEventListener("click", hideError);

  function showSidebarEmpty(text) {
    sidebarList.innerHTML = "";
    sidebarEmpty.textContent = text;
    sidebarEmpty.hidden = false;
  }

  // --- Image lightbox --------------------------------------------------------
  // Click any transcript image to view it large, centered over the review pane,
  // ChatGPT-style — matching main_ui / sandbox_ui. One overlay is lazily created
  // and reused; the .image-lightbox* styles ship in the shared chat.css.
  let imageLightbox = null;

  function openImageLightbox(src, alt) {
    if (!imageLightbox) {
      imageLightbox = document.createElement("div");
      imageLightbox.className = "image-lightbox";
      imageLightbox.hidden = true;
      const big = document.createElement("img");
      big.className = "image-lightbox-img";
      const close = document.createElement("button");
      close.type = "button";
      close.className = "image-lightbox-close";
      close.setAttribute("aria-label", "Close image");
      close.textContent = "×";
      imageLightbox.appendChild(big);
      imageLightbox.appendChild(close);
      document.body.appendChild(imageLightbox);
      // Backdrop or × click closes; clicking the image itself does nothing.
      imageLightbox.addEventListener("click", (event) => {
        if (event.target !== big) closeImageLightbox();
      });
      // Escape-to-close is handled by the unified Escape handler below.
    }
    const big = imageLightbox.querySelector(".image-lightbox-img");
    big.src = src;
    big.alt = alt || "attached image";
    imageLightbox.hidden = false;
  }

  function closeImageLightbox() {
    if (imageLightbox) imageLightbox.hidden = true;
  }

  // "Exercise 3 · May 19 · 8 messages" (or "Practice 3 ...") — mirrors
  // main_ui's formatEntryHeader.
  function formatEntryHeader(c) {
    const exNumber = parseInt(c.exercise_number, 10);
    const kindLabel = c.exercise_kind === "practice" ? "Practice" : "Exercise";
    const parts = [
      `${kindLabel} ${Number.isFinite(exNumber) ? exNumber : c.exercise_number}`,
    ];
    if (c.last_active_at) {
      const d = new Date(c.last_active_at);
      parts.push(d.toLocaleDateString(undefined, { month: "short", day: "numeric" }));
    }
    const n = c.message_count;
    parts.push(`${n} ${n === 1 ? "message" : "messages"}`);
    // Running estimated cost of the conversation, appended when non-zero —
    // mirrors sandbox_ui's history entries.
    if (typeof c.total_cost_usd === "number" && c.total_cost_usd > 0) {
      parts.push(formatTotalCostUsd(c.total_cost_usd));
    }
    return parts.join(" · ");
  }

  // Per-message estimated cost, 4 decimals so a ~$0.005-0.02 turn stays legible.
  function formatCostUsd(usd) {
    return "$" + Number(usd).toFixed(4);
  }

  // Conversation total: 2 decimals, falling back to 4 under a cent so a cheap
  // conversation still shows a non-zero figure. Matches sandbox_ui.
  function formatTotalCostUsd(usd) {
    const n = Number(usd);
    return "$" + n.toFixed(n < 0.01 ? 4 : 2);
  }

  function studentLabel(c) {
    return c.email || "Anonymous";
  }

  function renderSidebar(conversations) {
    sidebarList.innerHTML = "";
    if (!conversations || conversations.length === 0) {
      showSidebarEmpty("No past conversations yet");
      return;
    }
    sidebarEmpty.hidden = true;

    for (const c of conversations) {
      const li = document.createElement("li");
      li.className = "sidebar-entry";
      li.tabIndex = 0;
      li.setAttribute("role", "button");
      li.dataset.conversationId = c.id;

      // Identity line sits at the TOP of the entry — the username (or
      // "Anonymous"), in the crimson accent.
      const student = document.createElement("div");
      student.className = "sidebar-entry-student";
      student.textContent = studentLabel(c);
      if (!c.email) student.classList.add("is-anonymous");

      // Course eyebrow: a compact, muted label BELOW the identity line. With
      // several courses feeding one DB, it groups entries at a glance. Truncated
      // to one line via CSS; the full name shows on hover.
      const course = document.createElement("div");
      if (c.course_name) {
        course.className = "sidebar-entry-course";
        course.textContent = c.course_name;
        course.title = c.course_name;
      }

      const title = document.createElement("div");
      title.className = "sidebar-entry-title";
      title.textContent = formatEntryHeader(c);

      const snippet = document.createElement("div");
      snippet.className = "sidebar-entry-snippet";
      snippet.textContent = c.last_message_snippet || "(no messages)";

      li.appendChild(student);
      if (c.course_name) li.appendChild(course);
      li.appendChild(title);
      li.appendChild(snippet);

      // Flagged conversations (judge marked "didn't work well" in a weekly
      // report) get a crimson flag pinned to the entry's top-right. Same colour
      // and 16px box as the outage marker; decorative, so no hover. The SVG is a
      // static literal (no user data), so innerHTML doesn't break the no-raw-HTML
      // XSS guarantee that governs message content.
      if (c.flagged) {
        const flag = document.createElement("span");
        flag.className = "sidebar-entry-flag";
        flag.innerHTML =
          '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
          '<path d="M6 2a1 1 0 0 1 1 1v1.2l1.9-.5a7 7 0 0 1 4.6.4 5 5 0 0 0 3.9.1l1.2-.5A1 1 0 0 1 20 4.6V13a1 1 0 0 1-.62.92l-1.2.5a7 7 0 0 1-5.46-.14 5 5 0 0 0-3.3-.29L7 14.3V21a1 1 0 1 1-2 0V3a1 1 0 0 1 1-1z"/>' +
          '</svg>';
        flag.setAttribute("aria-hidden", "true");
        li.appendChild(flag);
      }

      if (c.id === activeConversationId) li.classList.add("sidebar-entry-active");

      const open = () => loadConversation(c.id);
      li.addEventListener("click", open);
      li.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          open();
        }
      });
      sidebarList.appendChild(li);
    }
    // If a conversation is already active when the list (re)builds — e.g. a
    // /?c=<id> deep link from the standalone weekly report — reveal it.
    scrollActiveIntoView();
  }

  function highlightActive() {
    for (const el of sidebarList.querySelectorAll(".sidebar-entry")) {
      el.classList.toggle(
        "sidebar-entry-active",
        el.dataset.conversationId === activeConversationId,
      );
    }
    scrollActiveIntoView();
  }

  // Bring the active conversation's sidebar entry into view. Matters most when a
  // conversation is opened from the weekly report's flagged list: it becomes the
  // selected (highlighted) entry, but may sit far down the list — this scrolls it
  // into the sidebar so the selection is actually visible. block:"nearest" scrolls
  // the sidebar minimally and never moves the page.
  function scrollActiveIntoView() {
    if (!activeConversationId) return;
    const el = sidebarList.querySelector(
      `.sidebar-entry[data-conversation-id="${CSS.escape(activeConversationId)}"]`,
    );
    if (el) el.scrollIntoView({ block: "nearest" });
  }

  async function refreshSidebar() {
    showSidebarEmpty("Loading…");
    try {
      const r = await fetch("/api/conversations");
      if (!r.ok) {
        // Surface a stale-schema error specifically; fall back to the generic
        // message for anything else (or an unparseable body).
        let msg = "Could not load conversations";
        try {
          const body = await r.json();
          if (body && body.error === "schema_outdated" && body.message) msg = body.message;
        } catch (_) {}
        reviewToolbar.hidden = true;
        return showSidebarEmpty(msg);
      }
      const data = await r.json();
      allConversations = Array.isArray(data.conversations) ? data.conversations : [];
      buildCourseOptions();
      reviewToolbar.hidden = allConversations.length === 0;
      applyView();
    } catch (e) {
      reviewToolbar.hidden = true;
      showSidebarEmpty("Could not load conversations");
    }
  }

  // --- Filter & sort bar -----------------------------------------------------
  // Populate the course popover from the distinct courses present, keyed by the
  // stable course code and labeled by display name (sorted). Multi-select: every
  // course starts selected, and toggling one re-filters live — mirroring the
  // weekly report's course picker.
  function buildCourseOptions() {
    const seen = new Map(); // code -> display name
    for (const c of allConversations) {
      if (c.course && !seen.has(c.course)) seen.set(c.course, c.course_name || c.course);
    }
    allCourseKeys = [...seen.keys()];

    // Initialise to "all selected"; on a refresh, keep the user's selection but
    // drop courses that vanished, and fall back to "all" if nothing's left.
    if (view.courses === null) {
      view.courses = new Set(allCourseKeys);
    } else {
      for (const k of [...view.courses]) if (!seen.has(k)) view.courses.delete(k);
      if (view.courses.size === 0) view.courses = new Set(allCourseKeys);
    }

    const opts = [...seen.entries()].map(([code, name]) => ({ code, name }));
    opts.sort((a, b) => a.name.localeCompare(b.name));

    coursePop.innerHTML = "";
    for (const o of opts) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "rt-opt";
      btn.setAttribute("role", "option");
      btn.textContent = o.name;
      btn.dataset.course = o.code;
      const isSel = view.courses.has(o.code);
      btn.classList.toggle("is-selected", isSel);
      btn.setAttribute("aria-selected", isSel ? "true" : "false");
      // Toggle this course and keep the popover open so several can be picked in
      // one go (the popover lives inside .rt-control, so the outside-click
      // handler leaves it open). The list re-filters live.
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        if (view.courses.has(o.code)) view.courses.delete(o.code);
        else view.courses.add(o.code);
        const on = view.courses.has(o.code);
        btn.classList.toggle("is-selected", on);
        btn.setAttribute("aria-selected", on ? "true" : "false");
        updateCourseActive();
        applyView();
      });
      coursePop.appendChild(btn);
    }
    updateCourseActive();
  }

  // Mark the course chip active when a strict subset of courses is selected.
  function updateCourseActive() {
    const subset = view.courses && view.courses.size < allCourseKeys.length;
    courseTrigger.classList.toggle("rt-active", !!subset);
  }

  // Apply the current sort + filters to allConversations and render.
  function applyView() {
    let list = allConversations.slice();
    // Filter by course only when it's a strict subset (all selected = show all).
    if (view.courses && view.courses.size < allCourseKeys.length) {
      list = list.filter((c) => view.courses.has(c.course));
    }
    if (view.flaggedOnly) list = list.filter((c) => c.flagged);

    list.sort((a, b) => {
      const ta = a.last_active_at ? Date.parse(a.last_active_at) : 0;
      const tb = b.last_active_at ? Date.parse(b.last_active_at) : 0;
      return view.sort === "oldest" ? ta - tb : tb - ta;
    });

    if (list.length === 0 && allConversations.length > 0) {
      // Nothing matched the active filters (the list itself isn't empty).
      showSidebarEmpty("No conversations match these filters");
      return;
    }
    renderSidebar(list);
  }

  // Mark one option selected within a popover, clearing its siblings.
  function markSelected(pop, chosen) {
    for (const opt of pop.querySelectorAll(".rt-opt")) {
      const on = opt === chosen;
      opt.classList.toggle("is-selected", on);
      opt.setAttribute("aria-selected", on ? "true" : "false");
    }
  }

  // Position a fixed popover directly under its trigger, nudged left if it would
  // spill past the right edge (the sidebar's overflow:hidden would clip a
  // normally-positioned dropdown, so the pops live at the top layer instead).
  function placePop(trigger, pop) {
    const r = trigger.getBoundingClientRect();
    pop.hidden = false; // must be visible to measure
    const w = pop.offsetWidth;
    let left = r.left;
    const overflow = left + w - (window.innerWidth - 8);
    if (overflow > 0) left = Math.max(8, left - overflow);
    pop.style.left = `${left}px`;
    pop.style.top = `${r.bottom + 6}px`;
  }

  function openPop(trigger, pop) {
    closePops();
    trigger.setAttribute("aria-expanded", "true");
    placePop(trigger, pop);
  }

  function closePops() {
    for (const t of [sortTrigger, courseTrigger]) t.setAttribute("aria-expanded", "false");
    sortPop.hidden = true;
    coursePop.hidden = true;
  }

  function togglePop(trigger, pop) {
    if (pop.hidden) openPop(trigger, pop);
    else closePops();
  }

  if (sortTrigger) {
    sortTrigger.addEventListener("click", (e) => {
      e.stopPropagation();
      togglePop(sortTrigger, sortPop);
    });
    for (const opt of sortPop.querySelectorAll(".rt-opt")) {
      opt.addEventListener("click", () => {
        view.sort = opt.dataset.sort;
        markSelected(sortPop, opt);
        closePops();
        applyView();
      });
    }
  }
  if (courseTrigger) {
    courseTrigger.addEventListener("click", (e) => {
      e.stopPropagation();
      togglePop(courseTrigger, coursePop);
    });
  }
  if (flagToggle) {
    flagToggle.addEventListener("click", () => {
      view.flaggedOnly = !view.flaggedOnly;
      flagToggle.setAttribute("aria-pressed", view.flaggedOnly ? "true" : "false");
      applyView();
    });
  }
  // Dismiss the popovers on an outside click, on Escape, and on any scroll/resize
  // (a fixed pop would otherwise float away from its detached trigger).
  document.addEventListener("click", (e) => {
    if (sortPop.hidden && coursePop.hidden) return;
    if (e.target.closest(".rt-control")) return;
    closePops();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closePops();
  });
  window.addEventListener("resize", closePops);
  if (sidebarList) sidebarList.addEventListener("scroll", closePops);

  function setMessageContent(el, role, content) {
    // Tutor replies are markdown + LaTeX math; render + sanitize via the shared
    // helper. Everything else is text.
    const rich =
      role === "tutor" && typeof window.renderTutorMarkdown === "function"
        ? window.renderTutorMarkdown(content || "")
        : null;
    if (rich !== null) {
      el.classList.add("message-rich");
      el.innerHTML = rich;
    } else {
      el.textContent = content || "";
    }
  }

  function appendImages(li, images) {
    if (!images || images.length === 0) return;
    const wrap = document.createElement("div");
    wrap.className = "message-images";
    for (const img of images) {
      const el = document.createElement("img");
      el.className = "message-image";
      el.src = `/api/image/${img.id}`;
      el.alt = "attached image";
      el.loading = "lazy";
      // Click to view large (matches main_ui / sandbox_ui).
      el.addEventListener("click", () => openImageLightbox(el.src, el.alt));
      wrap.appendChild(el);
    }
    li.appendChild(wrap);
  }

  // A "📎 <name>" pill for a non-image attachment on a past message. Rendered as
  // a download link — clicking it fetches the bytes from /api/file/<id>, served
  // with Content-Disposition: attachment so the browser saves it under the
  // original filename. Reuses chat.css's .attachment-chip.
  function renderFileChip(att) {
    const chip = document.createElement("a");
    chip.className = "attachment-chip";
    chip.href = `/api/file/${att.id}`;
    chip.setAttribute("download", att.filename || "");
    const icon = document.createElement("span");
    icon.className = "attachment-chip-icon";
    icon.setAttribute("aria-hidden", "true");
    // Static markup only (no user input); the filename is a separate text node.
    icon.innerHTML =
      '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" ' +
      'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>' +
      '<polyline points="14 2 14 8 20 8"/></svg>';
    const label = document.createElement("span");
    label.className = "attachment-chip-name";
    label.textContent = att.filename; // user-controlled — keep as a text node (no innerHTML)
    chip.appendChild(icon);
    chip.appendChild(label);
    return chip;
  }

  function appendFileChips(li, attachments) {
    if (!attachments || attachments.length === 0) return;
    const wrap = document.createElement("div");
    wrap.className = "message-attachments";
    for (const a of attachments) {
      wrap.appendChild(renderFileChip(a));
    }
    li.appendChild(wrap);
  }

  function appendReasoning(li, reasoning) {
    if (!reasoning) return;
    const details = document.createElement("details");
    details.className = "review-reasoning";
    const summary = document.createElement("summary");
    summary.textContent = "Pedagogical reasoning";
    const body = document.createElement("div");
    body.className = "review-reasoning-body";
    body.textContent = reasoning;
    details.appendChild(summary);
    details.appendChild(body);
    li.appendChild(details);
  }

  // Small non-collapsible label above the reasoning disclosure naming the LLM
  // behind this tutor turn and — when known — that turn's estimated cost, e.g.
  // "gpt-5.4 ($0.0075)". *model* is parsed from the stored usage breakdown;
  // *costUsd* is omitted when null (legacy rows predating cost tracking).
  function appendModelLabel(li, model, costUsd) {
    if (!model && costUsd == null) return;
    const div = document.createElement("div");
    div.className = "review-model";
    // Providers report a date-stamped snapshot id (e.g. "gpt-5.4-2026-03-05");
    // strip a trailing -YYYY-MM-DD / -YYYYMMDD for display.
    const label = (model || "").replace(/-(?:\d{4}-\d{2}-\d{2}|\d{8})$/, "");
    if (label && costUsd != null) {
      div.textContent = label + " (" + formatCostUsd(costUsd) + ")";
    } else if (label) {
      div.textContent = label;
    } else {
      div.textContent = formatCostUsd(costUsd);
    }
    li.appendChild(div);
  }

  // Collapsible "RAG retrieval" disclosure under a tutor message — expands to the
  // chunks RAG pulled that turn, each further expanding to its full text.
  // Mirrors sandbox_ui's review rendering.
  function appendRetrieved(li, retrieved) {
    if (!retrieved || !retrieved.length) return;
    const details = document.createElement("details");
    details.className = "review-reasoning review-retrieved";
    const summary = document.createElement("summary");
    summary.textContent =
      "RAG retrieval (" +
      retrieved.length +
      (retrieved.length === 1 ? " chunk)" : " chunks)");
    details.appendChild(summary);
    const body = document.createElement("div");
    body.className = "review-reasoning-body";
    retrieved.forEach((r) => {
      const chunk = document.createElement("details");
      chunk.className = "review-retrieved-chunk";
      const cs = document.createElement("summary");
      const score = typeof r.score === "number" ? r.score.toFixed(3) : r.score;
      const src = String(r.source || "").replace(/^local:/, "");
      const chars = r.chars != null ? r.chars : (r.text || "").length;
      cs.textContent = score + "  " + src + "  (" + chars + " chars)";
      chunk.appendChild(cs);
      const ct = document.createElement("div");
      ct.className = "review-retrieved-text";
      ct.textContent = r.text || "";
      chunk.appendChild(ct);
      body.appendChild(chunk);
    });
    details.appendChild(body);
    li.appendChild(details);
  }

  // Thumbs up/down icons (same glyphs as sandbox_ui).
  const THUMB_UP_SVG =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 10v11"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a2.5 2.5 0 0 1 3 3.88Z"/></svg>';
  const THUMB_DOWN_SVG =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 14V3"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a2.5 2.5 0 0 1-3-3.88Z"/></svg>';

  // Display-only thumbs under a tutor message reflecting the student's stored
  // rating (-1/0/1) — this is a read-only review tool, so the active thumb is
  // highlighted but the controls are inert (no writes back to the DB).
  function appendRating(li, rating) {
    const current = rating === 1 || rating === -1 ? rating : 0;
    const bar = document.createElement("li");
    bar.className = "msg-rating msg-rating-readonly";

    const up = document.createElement("span");
    up.className = "rating-btn rating-up";
    up.setAttribute("aria-label", "Rated thumbs up");
    up.innerHTML = THUMB_UP_SVG;
    if (current === 1) up.classList.add("is-active");

    const down = document.createElement("span");
    down.className = "rating-btn rating-down";
    down.setAttribute("aria-label", "Rated thumbs down");
    down.innerHTML = THUMB_DOWN_SVG;
    if (current === -1) down.classList.add("is-active");

    bar.appendChild(up);
    bar.appendChild(down);
    li.insertAdjacentElement("afterend", bar);
  }

  function renderMessage(m) {
    const li = document.createElement("li");
    li.className = "message message-" + m.role;
    const hasImages = m.images && m.images.length;
    const hasAttachments = m.attachments && m.attachments.length;
    // Attachments render ABOVE the text (matching the live student apps):
    // image thumbnails first, then downloadable "📎 name" file chips.
    appendImages(li, m.images);
    appendFileChips(li, m.attachments);
    if (hasImages || hasAttachments) {
      if (m.content) {
        const textEl = document.createElement("div");
        textEl.className = "message-text";
        setMessageContent(textEl, m.role, m.content);
        li.appendChild(textEl);
      }
    } else {
      setMessageContent(li, m.role, m.content);
    }
    // Reviewer-only metadata under each tutor turn: model+cost label, hidden
    // reasoning, and the RAG chunks retrieved that turn.
    if (m.role === "tutor") {
      appendModelLabel(li, m.model, m.cost_usd);
      appendReasoning(li, m.pedagogical_reasoning);
      appendRetrieved(li, m.retrieved);
    }
    messageList.appendChild(li);
    // Thumbs go in as the next sibling, so they sit under the bubble but outside
    // its background — the message must already be in the DOM.
    if (m.role === "tutor") appendRating(li, m.rating);
  }

  // Flag banner: if the judge flagged this conversation in a weekly report,
  // pin a crimson strip atop the transcript so the reviewer sees WHY without
  // opening the report. Collapsed by default (just the one-liner); clicking it
  // expands the full issue list. `flag` is null for unflagged conversations.
  function renderFlagBanner(flag) {
    if (!flag) return;
    const li = document.createElement("li");
    li.className = "review-flag-banner";

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "review-flag-summary";
    btn.setAttribute("aria-expanded", "false");

    const mark = document.createElement("span");
    mark.className = "review-flag-mark";
    mark.textContent = "⚠";
    mark.setAttribute("aria-hidden", "true");

    const oneLine = document.createElement("span");
    oneLine.className = "review-flag-oneline";
    oneLine.textContent = flag.one_line || "Flagged in a weekly report";

    const caret = document.createElement("span");
    caret.className = "review-flag-caret";
    caret.setAttribute("aria-hidden", "true");
    caret.textContent = "›";   // › — rotates to point down when open

    btn.append(mark, oneLine, caret);

    const details = document.createElement("div");
    details.className = "review-flag-details";
    details.hidden = true;

    // Which week (and score, if graded) this flag came from.
    if (flag.week_start) {
      const meta = document.createElement("div");
      meta.className = "review-flag-meta";
      let text = "Flagged in the week of " + flag.week_start + " report";
      const g = flag.grade;
      if (g && typeof g.total_score === "number") {
        text += " · score " + g.total_score + (g.max_score ? "/" + g.max_score : "");
      }
      meta.textContent = text;
      details.appendChild(meta);
    }

    const issues = Array.isArray(flag.issues) ? flag.issues : [];
    if (issues.length) {
      const ul = document.createElement("ul");
      ul.className = "review-flag-issues";
      for (const it of issues) {
        const item = document.createElement("li");
        const head = document.createElement("span");
        head.className = "review-flag-issue-head";
        head.textContent = [it.severity, it.type,
          typeof it.points === "number" ? it.points + " pts" : null]
          .filter(Boolean).join(" · ");
        item.appendChild(head);
        if (it.quote) {
          const body = document.createElement("span");
          body.className = "review-flag-issue-body";
          body.textContent = it.quote;
          item.appendChild(body);
        }
        ul.appendChild(item);
      }
      details.appendChild(ul);
    }

    btn.addEventListener("click", () => {
      const open = details.hidden;   // hidden now -> we're about to open
      details.hidden = !open;
      li.classList.toggle("is-open", open);
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });

    li.append(btn, details);
    messageList.appendChild(li);
  }

  async function loadConversation(id) {
    if (id === activeConversationId) return;
    activeConversationId = id;
    setView("conversation");   // leave the report if it was showing
    highlightActive();
    hideError();
    if (placeholder) placeholder.hidden = true;
    messageList.innerHTML = "";
    try {
      const r = await fetch(`/api/conversation/${id}`);
      if (!r.ok) {
        showError("Could not load that conversation");
        return;
      }
      const convo = await r.json();
      renderFlagBanner(convo.flag);
      for (const m of convo.messages) renderMessage(m);
      messageList.scrollTop = 0;
    } catch (e) {
      showError("Could not load that conversation");
    }
  }

  // Unified Escape: step back one layer at a time — image lightbox first, then
  // the sidebar (side dashboard) while it's open, then the weekly report.
  // Closing the open sidebar takes priority over leaving the report, so Escape
  // on the report tucks the sidebar away rather than exiting the report.
  // Mirrors main_ui / sandbox_ui, where Escape peels back the frontmost overlay.
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (imageLightbox && !imageLightbox.hidden) {
      closeImageLightbox();
    } else if (sidebar && sidebar.getAttribute("data-open") === "true") {
      setSidebar(false);
    } else if (analyticsPanel && !analyticsPanel.hidden) {
      hideReport();
    }
  });

  // Bridge for the weekly report's flagged list: the report (analytics.js) runs
  // both here and on the standalone /analytics page. On the dashboard it calls
  // this opener to swap a flagged conversation's transcript in-place; on the
  // standalone page (no transcript) it deep-links to /?c=<id>, read below.
  window.DatabaseReview = { open: loadConversation };

  refreshSidebar();

  // Deep link: /?c=<id> opens that conversation directly on load — used by the
  // standalone weekly report's flagged list, which navigates here. A blank or
  // bad id is ignored (loadConversation surfaces a load error if the id is real
  // but unreadable).
  const deepLinkId = new URLSearchParams(window.location.search).get("c");
  if (deepLinkId) loadConversation(deepLinkId);

  // Open the sidebar by default on wider screens (mirrors the student app).
  // Narrow screens (≤480px, where it covers the full transcript) stay closed.
  if (window.matchMedia("(min-width: 481px)").matches) {
    setSidebar(true);
  }
})();
