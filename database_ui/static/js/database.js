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

  let activeConversationId = null;

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
  }

  function highlightActive() {
    for (const el of sidebarList.querySelectorAll(".sidebar-entry")) {
      el.classList.toggle(
        "sidebar-entry-active",
        el.dataset.conversationId === activeConversationId,
      );
    }
  }

  async function refreshSidebar() {
    showSidebarEmpty("Loading…");
    try {
      const r = await fetch("/api/conversations?sort=date");
      if (!r.ok) {
        // Surface a stale-schema error specifically; fall back to the generic
        // message for anything else (or an unparseable body).
        let msg = "Could not load conversations";
        try {
          const body = await r.json();
          if (body && body.error === "schema_outdated" && body.message) msg = body.message;
        } catch (_) {}
        return showSidebarEmpty(msg);
      }
      const data = await r.json();
      renderSidebar(data.conversations);
    } catch (e) {
      showSidebarEmpty("Could not load conversations");
    }
  }

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
        showError("Could not load that conversation.");
        return;
      }
      const convo = await r.json();
      for (const m of convo.messages) renderMessage(m);
      messageList.scrollTop = 0;
    } catch (e) {
      showError("Could not load that conversation.");
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
