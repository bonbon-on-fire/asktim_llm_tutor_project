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

  let activeConversationId = null;

  // Sidebar open/close toggle (mirrors the student app's behavior).
  function setSidebar(open) {
    sidebar.setAttribute("data-open", open ? "true" : "false");
  }
  if (historyToggle) historyToggle.addEventListener("click", () => setSidebar(true));
  if (sidebarClose) sidebarClose.addEventListener("click", () => setSidebar(false));

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

  // "Exercise 3 · May 19 · 8 messages" — mirrors main_ui's formatEntryHeader.
  function formatEntryHeader(c) {
    const exNumber = parseInt(c.exercise_number, 10);
    const parts = [
      `Exercise ${Number.isFinite(exNumber) ? exNumber : c.exercise_number}`,
    ];
    if (c.last_active_at) {
      const d = new Date(c.last_active_at);
      parts.push(d.toLocaleDateString(undefined, { month: "short", day: "numeric" }));
    }
    const n = c.message_count;
    parts.push(`${n} ${n === 1 ? "message" : "messages"}`);
    return parts.join(" · ");
  }

  function studentLabel(c) {
    return c.email || "Anonymous";
  }

  function renderSidebar(conversations) {
    sidebarList.innerHTML = "";
    if (!conversations || conversations.length === 0) {
      showSidebarEmpty("No conversations yet.");
      return;
    }
    sidebarEmpty.hidden = true;

    for (const c of conversations) {
      const li = document.createElement("li");
      li.className = "sidebar-entry";
      li.tabIndex = 0;
      li.setAttribute("role", "button");
      li.dataset.conversationId = c.id;

      // Course eyebrow: a compact, muted label sitting ABOVE the identity line.
      // With several courses feeding one DB, it groups entries at a glance.
      // Truncated to one line via CSS; the full name shows on hover.
      if (c.course_name) {
        const course = document.createElement("div");
        course.className = "sidebar-entry-course";
        course.textContent = c.course_name;
        course.title = c.course_name;
        li.appendChild(course);
      }

      // Email/identity line sits ABOVE the exercise header line.
      const student = document.createElement("div");
      student.className = "sidebar-entry-student";
      student.textContent = studentLabel(c);
      if (!c.email) student.classList.add("is-anonymous");

      const title = document.createElement("div");
      title.className = "sidebar-entry-title";
      title.textContent = formatEntryHeader(c);

      const snippet = document.createElement("div");
      snippet.className = "sidebar-entry-snippet";
      snippet.textContent = c.last_message_snippet || "(no messages)";

      li.appendChild(student);
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
      wrap.appendChild(el);
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

  function renderMessage(m) {
    const li = document.createElement("li");
    li.className = "message message-" + m.role;
    if (m.images && m.images.length) {
      appendImages(li, m.images);
      if (m.content) {
        const textEl = document.createElement("div");
        textEl.className = "message-text";
        setMessageContent(textEl, m.role, m.content);
        li.appendChild(textEl);
      }
    } else {
      setMessageContent(li, m.role, m.content);
    }
    // Reviewer-only: surface the tutor's hidden reasoning.
    if (m.role === "tutor") appendReasoning(li, m.pedagogical_reasoning);
    messageList.appendChild(li);
  }

  async function loadConversation(id) {
    if (id === activeConversationId) return;
    activeConversationId = id;
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

  refreshSidebar();
})();
