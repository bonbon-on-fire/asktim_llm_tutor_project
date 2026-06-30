"use strict";

(() => {
  const configEl = document.getElementById("tutor-config");
  const config = JSON.parse(configEl.textContent);
  if (typeof config.syllabus === "undefined") config.syllabus = true;
  // Whether the built-in course.txt description is folded into context. Like
  // `syllabus`, defaults on; the wizard's "No course description" turns it off.
  if (typeof config.courseEnabled === "undefined") config.courseEnabled = true;
  // One-off custom context (from the Create-context wizard). null = use the
  // built-in field above; a string = send as custom text with each /api/chat.
  if (typeof config.courseCustom === "undefined") config.courseCustom = null;
  if (typeof config.exerciseCustom === "undefined") config.exerciseCustom = null;
  if (typeof config.tutorCustom === "undefined") config.tutorCustom = null;
  if (typeof config.syllabusCustom === "undefined") config.syllabusCustom = null;
  // Per-conversation RAG toggle (Create-context wizard). null = let the server
  // resolve by default; "rag" / "full_context" force the mode.
  if (typeof config.contextMode === "undefined") config.contextMode = null;
  // Which content kind the exercise selection refers to: "exercise" (default)
  // or "practice". Carried with each /api/chat send.
  if (typeof config.exerciseKind === "undefined") config.exerciseKind = "exercise";

  const courseNameEl = document.querySelector(".course-name");

  const messageList = document.getElementById("message-list");
  const composerForm = document.getElementById("composer");
  const composerInput = document.getElementById("composer-input");
  const sendButton = document.getElementById("send-button");
  const attachButton = document.getElementById("attach-button");
  const imageInput = document.getElementById("image-input");
  const composerPreviews = document.getElementById("composer-previews");

  // Client-side mirror of utils/uploads.py caps. The server re-validates, so
  // these only exist to give fast, friendly feedback before upload.
  const ALLOWED_IMAGE_TYPES = ["image/png", "image/jpeg"];
  const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
  const MAX_IMAGES_PER_MESSAGE = 5;
  // Staged uploads for the next send: { file, url } (url = object URL preview).
  let stagedImages = [];

  const errorBanner = document.getElementById("error-banner");
  const errorText = document.getElementById("error-text");
  const errorDismiss = document.getElementById("error-dismiss");

  const emailModal = document.getElementById("email-modal");
  const emailForm = document.getElementById("email-form");
  const emailInput = document.getElementById("email-input");
  const passwordInput = document.getElementById("password-input");
  const passwordStage = document.getElementById("password-stage");
  const passwordHint = document.getElementById("password-hint");
  const emailDisplay = document.getElementById("email-display");
  const emailChangeBtn = document.getElementById("email-change");
  const emailSubmit = document.getElementById("email-submit");
  const emailSkip = document.getElementById("email-skip");
  const emailError = document.getElementById("email-error");

  const MIN_PASSWORD_LENGTH = 6;

  // Modal moves through two stages. "email" gathers the address, then the
  // server is probed to learn whether it's already registered; "password"
  // collects the password with copy that depends on the probe result.
  let modalStage = "email"; // "email" | "password"
  let modalEmailExists = null; // null until probed; then true|false
  let modalConfirmedEmail = ""; // the email we advanced past stage 1 with

  const historyToggle = document.getElementById("history-toggle");
  const sidebar = document.getElementById("sidebar");
  const sidebarClose = document.getElementById("sidebar-close");
  const sidebarList = document.getElementById("sidebar-list");
  const sidebarEmpty = document.getElementById("sidebar-empty");
  const newChatButton = document.getElementById("new-chat");
  const addEmailButton = document.getElementById("add-email");

  // Lazy-loaded course/exercise/tutor options, shared by the Create-context wizard.
  let contextOptions = null; // { courses: [...], tutors: [...] }

  // Create-context wizard (sandbox_ui only)
  const createContextButton = document.getElementById("create-context");
  const createModal = document.getElementById("create-modal");
  const createForm = document.getElementById("create-form");
  const createStepLabel = document.getElementById("create-step-label");
  const createStepBody = document.getElementById("create-step-body");
  const createError = document.getElementById("create-error");
  const createBack = document.getElementById("create-back");
  const createNext = document.getElementById("create-next");
  const createCancel = document.getElementById("create-cancel");
  let createModalOpen = false;
  let createStep = 0;
  // Per-step draft: each field is { mode: "existing"|"custom", existing, custom }.
  let createDraft = null;

  const detailView = document.getElementById("detail-view");
  const detailBack = document.getElementById("detail-back");
  const detailMeta = document.getElementById("detail-meta");
  const detailMessages = document.getElementById("detail-messages");

  let conversationId = null;
  let isSending = false;
  let studentMessageCount = 0;
  let modalOpen = false;
  let dismissedThisSession = false;
  let sidebarOpen = false;
  // AbortController for the in-flight POST /api/chat — set when sending,
  // aborted when the student switches to a past conversation mid-request.
  let currentChatController = null;

  function updateSendButton() {
    const hasText = composerInput.value.trim().length > 0;
    sendButton.disabled = isSending || (!hasText && stagedImages.length === 0);
  }

  function setSending(sending) {
    isSending = sending;
    composerInput.disabled = sending;
    if (attachButton) attachButton.disabled = sending;
    updateSendButton();
  }

  // --- Image lightbox -------------------------------------------------------
  // Click any chat image — a staged composer thumbnail (not yet sent) or one
  // already in the message log — to view it large, centered over the chat,
  // ChatGPT-style. One overlay is lazily created and reused.
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
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !imageLightbox.hidden) closeImageLightbox();
      });
    }
    const big = imageLightbox.querySelector(".image-lightbox-img");
    big.src = src;
    big.alt = alt || "attached image";
    imageLightbox.hidden = false;
  }

  function closeImageLightbox() {
    if (imageLightbox) imageLightbox.hidden = true;
  }

  function renderStagedPreviews() {
    if (!composerPreviews) return;
    composerPreviews.innerHTML = "";
    if (stagedImages.length === 0) {
      composerPreviews.hidden = true;
      return;
    }
    composerPreviews.hidden = false;
    stagedImages.forEach((item, index) => {
      const thumb = document.createElement("div");
      thumb.className = "composer-thumb";
      const img = document.createElement("img");
      img.src = item.url;
      img.alt = item.file.name || "attached image";
      img.addEventListener("click", () => openImageLightbox(item.url, img.alt));
      thumb.appendChild(img);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "composer-thumb-remove";
      remove.setAttribute("aria-label", "Remove image");
      remove.textContent = "×";
      remove.addEventListener("click", () => {
        URL.revokeObjectURL(item.url);
        stagedImages.splice(index, 1);
        renderStagedPreviews();
        updateSendButton();
      });
      thumb.appendChild(remove);
      composerPreviews.appendChild(thumb);
    });
  }

  function addStagedFiles(fileList) {
    const files = Array.from(fileList || []);
    for (const file of files) {
      if (stagedImages.length >= MAX_IMAGES_PER_MESSAGE) {
        showError("You can attach up to " + MAX_IMAGES_PER_MESSAGE + " images.");
        break;
      }
      if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
        showError("Only PNG and JPEG images are supported.");
        continue;
      }
      if (file.size > MAX_IMAGE_BYTES) {
        showError("Images must be 10 MB or smaller.");
        continue;
      }
      stagedImages.push({ file: file, url: URL.createObjectURL(file) });
    }
    renderStagedPreviews();
    updateSendButton();
  }

  function setMessageContent(el, role, content) {
    // Tutor replies are markdown (tables, lists, bold). Render them to HTML so
    // they display cleanly — but ALWAYS sanitize, since innerHTML would
    // otherwise reintroduce the XSS hole that textContent guarded against.
    // Student text and any case where the libs failed to load stay textContent.
    const canRenderMarkdown =
      role === "tutor" &&
      typeof window.marked !== "undefined" &&
      typeof window.DOMPurify !== "undefined";
    if (canRenderMarkdown) {
      el.classList.add("message-rich");
      el.innerHTML = window.DOMPurify.sanitize(window.marked.parse(content));
    } else {
      // textContent — never raw innerHTML — to prevent XSS from tutor/student text.
      el.textContent = content;
    }
  }

  function appendImages(li, srcs) {
    if (!srcs || srcs.length === 0) return;
    const wrap = document.createElement("div");
    wrap.className = "message-images";
    for (const src of srcs) {
      const img = document.createElement("img");
      img.className = "message-image";
      img.src = src;
      img.alt = "attached image";
      img.loading = "lazy";
      img.addEventListener("click", () => openImageLightbox(src, img.alt));
      wrap.appendChild(img);
    }
    li.appendChild(wrap);
  }

  // Collapsible "Pedagogical reasoning" disclosure under a tutor message —
  // same markup/formatting as database_ui's review dashboard. The Sandbox is a
  // dev/TA tool, so surfacing the tutor's hidden reasoning is intentional.
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

  function renderMessage(role, content, imageSrcs, reasoning) {
    const li = document.createElement("li");
    li.className = "message message-" + role;
    if (imageSrcs && imageSrcs.length) {
      // Image(s) above the text: attach images first, then the text in its own
      // wrapper (setMessageContent writes onto the element it's given, so the
      // text needs its own node to avoid clobbering the image block).
      appendImages(li, imageSrcs);
      if (content) {
        const textEl = document.createElement("div");
        textEl.className = "message-text";
        setMessageContent(textEl, role, content);
        li.appendChild(textEl);
      }
    } else {
      setMessageContent(li, role, content);
    }
    if (role === "tutor") appendReasoning(li, reasoning);
    messageList.appendChild(li);
    // Always auto-scroll to bottom. Known papercut: fights user scrolling.
    messageList.scrollTop = messageList.scrollHeight;
    return li;
  }

  function renderThinking() {
    const li = document.createElement("li");
    li.className = "message message-thinking";
    li.appendChild(document.createTextNode("AskTIM Sandbox is thinking"));
    // Three staggered .thinking-dot spans CSS-blink one-after-another.
    for (let i = 0; i < 3; i++) {
      const dot = document.createElement("span");
      dot.className = "thinking-dot";
      dot.textContent = ".";
      li.appendChild(dot);
    }
    messageList.appendChild(li);
    messageList.scrollTop = messageList.scrollHeight;
    return li;
  }

  function showError(reason) {
    errorText.textContent = reason;
    errorBanner.hidden = false;
  }

  function hideError() {
    errorBanner.hidden = true;
    errorText.textContent = "";
  }

  function hasEmailSet() {
    // The `tutor_email` cookie is HttpOnly so JS can't read it directly.
    // The server stamps document.body.dataset.hasEmail on every render
    // based on the request's cookie; we also flip it locally after a
    // successful submission so the modal doesn't re-open this page load.
    return document.body.dataset.hasEmail === "true";
  }

  function refreshAddEmailVisibility() {
    // Show the "Add email" sidebar button only when no email is set —
    // gives skipped-the-modal students a way back in.
    addEmailButton.hidden = hasEmailSet();
  }

  function emailLooksValid(value) {
    return value.includes("@") && value.includes(".");
  }

  function passwordLooksValid(value) {
    return value.length >= MIN_PASSWORD_LENGTH;
  }

  function setModalStage(stage) {
    modalStage = stage;
    if (stage === "email") {
      passwordStage.hidden = true;
      emailInput.hidden = false;
      emailInput.disabled = false;
      emailSubmit.textContent = "Next";
    } else {
      // Stage 2: hide email input (kept in DOM so the value persists),
      // show the recap + password field with copy that depends on
      // whether the email is already registered.
      emailInput.hidden = true;
      passwordStage.hidden = false;
      emailDisplay.textContent = modalConfirmedEmail;
      if (modalEmailExists) {
        passwordInput.placeholder = "Enter your password";
        passwordInput.setAttribute("autocomplete", "current-password");
        passwordHint.textContent = "";
        emailSubmit.textContent = "Sign in";
      } else {
        passwordInput.placeholder = "Create a password (6+ characters)";
        passwordInput.setAttribute("autocomplete", "new-password");
        passwordHint.textContent = "";
        emailSubmit.textContent = "Create";
      }
    }
    updateEmailSubmit();
  }

  function updateEmailSubmit() {
    if (modalStage === "email") {
      emailSubmit.disabled = !emailLooksValid(emailInput.value.trim());
    } else {
      emailSubmit.disabled = !passwordLooksValid(passwordInput.value);
    }
  }

  function openEmailModal({ manual = false } = {}) {
    if (modalOpen) return;
    modalOpen = true;
    emailError.hidden = true;
    emailError.textContent = "";
    emailInput.value = "";
    passwordInput.value = "";
    modalEmailExists = null;
    modalConfirmedEmail = "";
    // Manual open (the "Add email" button) is dismissible as "Cancel"; the
    // automatic prompt after the third message reads "Skip".
    emailSkip.textContent = manual ? "Cancel" : "Skip";
    setModalStage("email");
    emailModal.hidden = false;
    emailInput.focus();
  }

  function closeEmailModal({ dismissed = false } = {}) {
    if (!modalOpen) return;
    modalOpen = false;
    emailModal.hidden = true;
    if (dismissed) {
      dismissedThisSession = true;
    }
    composerInput.focus();
  }

  function maybeShowEmailModal(count) {
    console.log("[modal-trigger]", {
      count,
      hasEmail: hasEmailSet(),
      dismissed: dismissedThisSession,
      modalOpen,
      sidebarOpen,
    });
    if (count < 3) return;
    if (hasEmailSet()) return;
    if (dismissedThisSession) return;
    openEmailModal();
  }

  // ---- Step 8: history sidebar + read-only detail view ------------------

  function showSidebarEmpty(text) {
    sidebarEmpty.textContent = text;
    sidebarEmpty.hidden = false;
  }

  function renderHistoryEntries(email, conversations) {
    sidebarList.innerHTML = "";
    if (!email) {
      showSidebarEmpty("Add your email to save chat history");
      return;
    }
    if (!conversations || conversations.length === 0) {
      showSidebarEmpty("No past conversations yet.");
      return;
    }
    // Have entries — make sure the loading/empty banner is hidden.
    sidebarEmpty.hidden = true;
    for (const c of conversations) {
      const li = document.createElement("li");
      li.className = "sidebar-entry";
      li.tabIndex = 0;
      li.setAttribute("role", "button");

      const title = document.createElement("div");
      title.className = "sidebar-entry-title";
      title.textContent = formatEntryHeader(c);

      const snippet = document.createElement("div");
      snippet.className = "sidebar-entry-snippet";
      snippet.textContent = c.last_message_snippet || "(no messages yet)";

      li.appendChild(title);
      li.appendChild(snippet);

      li.dataset.conversationId = c.id;
      if (c.id === conversationId) {
        li.classList.add("sidebar-entry-active");
      }
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

  function formatEntryHeader(c) {
    // "Exercise 3 · May 19 · 8 messages" — strip leading zeros from
    // exercise number; show the most-recent-active date.
    const exNumber = parseInt(c.exercise_number, 10);
    const parts = [
      `Exercise ${Number.isFinite(exNumber) ? exNumber : c.exercise_number}`,
    ];
    if (c.last_active_at) {
      const d = new Date(c.last_active_at);
      parts.push(
        d.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
      );
    }
    const count = c.message_count;
    parts.push(`${count} ${count === 1 ? "message" : "messages"}`);
    return parts.join(" · ");
  }

  function formatFullDate(isoDate) {
    if (!isoDate) return "";
    const d = new Date(isoDate);
    return d.toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  }

  async function refreshSidebar({ showLoading = true } = {}) {
    if (showLoading) {
      sidebarList.innerHTML = "";
      showSidebarEmpty("Loading…");
    }
    try {
      const response = await fetch("/api/history");
      if (!response.ok) {
        if (showLoading) showSidebarEmpty("Could not load history");
        return;
      }
      const data = await response.json();
      renderHistoryEntries(data.email, data.conversations);
    } catch (err) {
      if (showLoading) showSidebarEmpty("Could not load history");
    }
  }

  async function openSidebar() {
    if (sidebarOpen) return;
    sidebarOpen = true;
    sidebar.setAttribute("data-open", "true");
    refreshAddEmailVisibility();
    await refreshSidebar();
  }

  function closeSidebar() {
    if (!sidebarOpen) return;
    sidebarOpen = false;
    sidebar.setAttribute("data-open", "false");
  }

  function toggleSidebar() {
    if (sidebarOpen) {
      closeSidebar();
    } else {
      openSidebar();
    }
  }

  function highlightActiveEntry() {
    for (const entry of sidebarList.querySelectorAll(".sidebar-entry")) {
      const isActive = entry.dataset.conversationId === conversationId;
      entry.classList.toggle("sidebar-entry-active", isActive);
    }
  }

  async function loadConversation(targetConversationId) {
    if (targetConversationId === conversationId) return;

    // Abort any in-flight chat request — the reply belongs to the OLD
    // conversation; the student is moving on.
    if (currentChatController) {
      currentChatController.abort();
      currentChatController = null;
    }

    // Optimistically clear the live chat. Composer draft stays.
    messageList.innerHTML = "";
    hideError();

    try {
      const response = await fetch(
        `/api/conversation/${encodeURIComponent(targetConversationId)}`,
      );
      if (!response.ok) {
        showError("Could not load that conversation.");
        return;
      }
      const data = await response.json();
      conversationId = data.id;
      studentMessageCount = (data.messages || []).filter(
        (m) => m.role === "student",
      ).length;
      for (const m of data.messages || []) {
        const srcs = (m.images || []).map((img) => `/api/image/${img.id}`);
        renderMessage(m.role, m.content, srcs, m.pedagogical_reasoning);
      }
      highlightActiveEntry();
    } catch (err) {
      showError("Could not load that conversation.");
    }
  }

  function closeDetailView() {
    if (detailView) detailView.hidden = true;
  }

  function startNewChat() {
    // Clear the live chat and start a fresh conversation. Composer text
    // is intentionally preserved — student may have typed a draft they
    // want to send into the new conversation.
    if (currentChatController) {
      currentChatController.abort();
      currentChatController = null;
    }
    messageList.innerHTML = "";
    conversationId = null;
    studentMessageCount = 0;
    // Each new chat is a fresh chance to capture the email — reset the
    // "dismissed" flag so the modal can re-appear after 3 messages if
    // the email cookie still isn't set.
    dismissedThisSession = false;
    hideError();
    highlightActiveEntry();
    composerInput.focus();
  }

  // ---- Context switcher (sandbox_ui only) --------------------------------------

  async function ensureContextOptions() {
    if (contextOptions) return contextOptions;
    const response = await fetch("/api/context/options");
    if (!response.ok) throw new Error("options fetch failed");
    contextOptions = await response.json();
    return contextOptions;
  }

  function courseBySlug(slug) {
    if (!contextOptions) return null;
    return contextOptions.courses.find((c) => c.slug === slug) || null;
  }

  function tutorLabel(stem) {
    // "tutor_01" -> "Tutor 1" for display; value stays the raw stem.
    const m = /tutor_0*(\d+)/.exec(stem);
    return m ? "Tutor " + m[1] : stem;
  }

  function fillSelect(selectEl, options, current) {
    selectEl.innerHTML = "";
    for (const o of options) {
      const opt = document.createElement("option");
      opt.value = o.value;
      opt.textContent = o.label;
      if (o.value === current) opt.selected = true;
      selectEl.appendChild(opt);
    }
  }

  // ---- Create-context wizard (sandbox_ui only) ---------------------------------

  const CREATE_STEPS = ["course", "exercise", "tutor", "syllabus"];
  const CREATE_LABELS = ["Course", "Exercise", "Tutor prompt", "Syllabus"];
  const STEP_LABELS = {
    course: "Course",
    exercise: "Exercise",
    tutor: "Tutor prompt",
    syllabus: "Syllabus",
  };
  // When the RAG toggle is on, the syllabus step is skipped — course, syllabus,
  // and lectures all come from retrieval, so there's nothing to pick there.
  function activeSteps() {
    return createDraft && createDraft.useRag
      ? CREATE_STEPS.filter((s) => s !== "syllabus")
      : CREATE_STEPS;
  }
  const CUSTOM = "__custom__";
  const LOCKED_TUTOR = "tutor_05"; // the tutor prompt is locked to this in the wizard
  const LOCK_ICON_SVG =
    '<svg class="lock-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>';

  async function fetchPreviewText(stepKey, value) {
    let url;
    if (stepKey === "course") {
      url = `/api/context/preview?kind=course&course=${encodeURIComponent(value)}`;
    } else if (stepKey === "exercise") {
      const raw = String(value || "");
      const isPractice = raw.startsWith("practice:");
      const num = raw.includes(":") ? raw.split(":")[1] : raw;
      url =
        `/api/context/preview?kind=${isPractice ? "practice" : "exercise"}` +
        `&course=${encodeURIComponent(createDraft.course.existing)}` +
        `&exercise=${encodeURIComponent(num)}`;
    } else if (stepKey === "tutor") {
      url = `/api/context/preview?kind=tutor&tutor=${encodeURIComponent(value)}`;
    } else {
      url = `/api/context/preview?kind=syllabus&course=${encodeURIComponent(createDraft.course.existing)}`;
    }
    try {
      const r = await fetch(url);
      if (!r.ok) return "(could not load preview)";
      const d = await r.json();
      return d.text || "";
    } catch (_) {
      return "(could not load preview)";
    }
  }

  function buildSelect(options, value) {
    const sel = document.createElement("select");
    sel.className = "context-select";
    sel.id = "create-select";
    const addOption = (parent, o) => {
      const opt = document.createElement("option");
      opt.value = o.value;
      opt.textContent = o.label;
      if (o.value === value) opt.selected = true;
      parent.appendChild(opt);
    };
    for (const o of options) {
      if (o.group) {
        if (!o.options.length) continue;
        const og = document.createElement("optgroup");
        og.label = o.group;
        for (const inner of o.options) addOption(og, inner);
        sel.appendChild(og);
      } else {
        addOption(sel, o);
      }
    }
    return sel;
  }

  function renderCreateStep() {
    createError.hidden = true;
    const steps = activeSteps();
    const step = steps[createStep];
    const stepLabelText =
      `Step ${createStep + 1} of ${steps.length}: ${STEP_LABELS[step]}`;
    if (step === "tutor") {
      // Tutor prompt is locked to tutor_05 — show a small lock icon by the label.
      createStepLabel.innerHTML = `${stepLabelText} ${LOCK_ICON_SVG}`;
    } else {
      createStepLabel.textContent = stepLabelText;
    }
    createStepBody.innerHTML = "";

    let options = [];
    let currentValue;
    let placeholder = "";
    let customValue = "";

    if (step === "course") {
      options = [
        ...contextOptions.courses
          .map((c) => ({ value: c.slug, label: c.name || c.slug }))
          .sort((a, b) => a.label.localeCompare(b.label, undefined, { numeric: true })),
        { value: CUSTOM, label: "Create custom course" },
      ];
      const d = createDraft.course;
      currentValue = d.mode === "custom" ? CUSTOM : d.existing;
      customValue = d.custom;
      placeholder = "Paste or write the course context…";
    } else if (step === "exercise") {
      const cd = createDraft.course;
      const courseObj = cd.mode === "existing" ? courseBySlug(cd.existing) : null;
      const exs = (courseObj && courseObj.exercises) || [];
      const pracs = (courseObj && courseObj.practice) || [];
      options = [
        // Flat list: exercises first, then practice problems, then custom (no
        // group headers). The value prefix (exercise:/practice:) carries the kind.
        ...exs.map((n) => ({
          value: "exercise:" + n,
          label: "Exercise " + (parseInt(n, 10) || n),
        })),
        ...pracs.map((n) => ({
          value: "practice:" + n,
          label: "Practice " + (parseInt(n, 10) || n),
        })),
        { value: CUSTOM, label: "Create custom exercise" },
      ];
      const d = createDraft.exercise;
      if (cd.mode === "custom") {
        currentValue = CUSTOM; // custom course has no built-in exercises
      } else if (d.mode === "custom") {
        currentValue = CUSTOM;
      } else {
        const firstExisting =
          (exs[0] && "exercise:" + exs[0]) ||
          (pracs[0] && "practice:" + pracs[0]) ||
          CUSTOM;
        currentValue =
          d.existing ? d.kind + ":" + d.existing : firstExisting;
      }
      customValue = d.custom;
      placeholder = "Paste or write the exercise…";
    } else if (step === "tutor") {
      options = [
        ...contextOptions.tutors
          .map((t) => ({ value: t, label: tutorLabel(t) }))
          .sort((a, b) => a.label.localeCompare(b.label, undefined, { numeric: true })),
        { value: CUSTOM, label: "Create custom prompt" },
      ];
      currentValue = LOCKED_TUTOR; // locked — testers can't change the tutor prompt here
      customValue = "";
      placeholder = "Paste or write the tutor prompt…";
    } else {
      // syllabus
      const cd = createDraft.course;
      const courseObj = cd.mode === "existing" ? courseBySlug(cd.existing) : null;
      options = [];
      if (courseObj && courseObj.has_syllabus) {
        options.push({ value: "default", label: "Course syllabus" });
      }
      options.push({ value: "none", label: "No syllabus" });
      options.push({ value: CUSTOM, label: "Create custom syllabus" });
      const d = createDraft.syllabus;
      let v = d.mode === "custom" ? CUSTOM : d.value;
      if (v === "default" && !(courseObj && courseObj.has_syllabus)) v = "none";
      currentValue = v;
      customValue = d.custom;
      placeholder = "Paste or write the syllabus…";
    }

    // Default to the first option in the dropdown when the draft has no valid
    // explicit selection yet, so the step opens on the first built-in (e.g. the
    // first course) rather than the trailing "Create custom …" option.
    const optionMatches = (o, v) =>
      o.value === v || (o.options && o.options.some((i) => i.value === v));
    if (options.length && !options.some((o) => optionMatches(o, currentValue))) {
      currentValue = options[0].value;
    }

    const sel = buildSelect(options, currentValue);
    if (step === "tutor") sel.disabled = true; // tutor prompt is locked to tutor_05
    createStepBody.appendChild(sel);

    const ta = document.createElement("textarea");
    ta.className = "create-custom";
    ta.id = "create-custom-input";
    ta.placeholder = placeholder;
    createStepBody.appendChild(ta);

    // RAG toggle — course step only, and only for courses with a built index.
    // When on, course/syllabus/lectures are retrieved and the syllabus step is
    // skipped.
    let ragToggleRow = null;
    let courseDescRow = null;
    if (step === "course") {
      // "Include course description" toggle — gates the built-in course.txt.
      // Mirrors the RAG toggle; hidden for a custom course or when RAG is on.
      courseDescRow = document.createElement("label");
      courseDescRow.className = "rag-toggle";
      const dcb = document.createElement("input");
      dcb.type = "checkbox";
      dcb.id = "create-course-desc-toggle";
      dcb.checked = createDraft.course.enabled !== false;
      const dspan = document.createElement("span");
      dspan.textContent = "Include course description";
      courseDescRow.appendChild(dcb);
      courseDescRow.appendChild(dspan);
      createStepBody.appendChild(courseDescRow);
      dcb.addEventListener("change", () => {
        createDraft.course.enabled = dcb.checked;
      });

      ragToggleRow = document.createElement("label");
      ragToggleRow.className = "rag-toggle";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.id = "create-rag-toggle";
      cb.checked = !!createDraft.useRag;
      const span = document.createElement("span");
      span.textContent = "Use RAG for course context";
      ragToggleRow.appendChild(cb);
      ragToggleRow.appendChild(span);
      createStepBody.appendChild(ragToggleRow);
      cb.addEventListener("change", () => {
        createDraft.useRag = cb.checked;
        updateCourseDescVisibility();
        const s = activeSteps();
        createStepLabel.textContent =
          `Step ${createStep + 1} of ${s.length}: ${STEP_LABELS[step]}`;
        createNext.textContent =
          createStep === s.length - 1 ? "Create & start chat" : "Continue";
      });
    }

    function updateRagToggleVisibility() {
      if (!ragToggleRow) return;
      const v = sel.value;
      const courseObj = v && v !== CUSTOM ? courseBySlug(v) : null;
      const hasRag = !!(courseObj && courseObj.has_rag);
      ragToggleRow.hidden = !hasRag;
      if (!hasRag && createDraft.useRag) {
        // A custom or un-indexed course can't use RAG — force it off.
        createDraft.useRag = false;
        const cb = document.getElementById("create-rag-toggle");
        if (cb) cb.checked = false;
        createStepLabel.textContent =
          `Step ${createStep + 1} of ${activeSteps().length}: ${STEP_LABELS[step]}`;
      }
    }

    function updateCourseDescVisibility() {
      if (!courseDescRow) return;
      const v = sel.value;
      // Show only for a real (built-in) course with RAG off — a custom course's
      // text is always included, and RAG retrieves course material instead.
      courseDescRow.hidden = !(v && v !== CUSTOM && !createDraft.useRag);
    }

    const stepKey = step;

    // Keep the draft's typed text in sync, so toggling to an existing option
    // and back doesn't lose what the tester wrote.
    ta.addEventListener("input", () => {
      if (ta.readOnly) return;
      if (stepKey === "syllabus") createDraft.syllabus.custom = ta.value;
      else createDraft[stepKey].custom = ta.value;
      updateCreateNextEnabled();
    });

    // Token guards the async preview fetch against a newer selection change.
    let syncToken = 0;
    async function syncTextarea() {
      const val = sel.value;
      const token = ++syncToken;
      if (val === CUSTOM) {
        // "Create …" — editable, restore the draft's typed text.
        ta.readOnly = false;
        ta.hidden = false;
        ta.placeholder = placeholder;
        ta.value =
          (stepKey === "syllabus"
            ? createDraft.syllabus.custom
            : createDraft[stepKey].custom) || "";
      } else if (stepKey === "syllabus" && val === "none") {
        // No syllabus — nothing to preview.
        ta.readOnly = true;
        ta.hidden = true;
        ta.value = "";
      } else {
        // Existing option — show its text, read-only.
        ta.readOnly = true;
        ta.hidden = false;
        ta.value = "Loading…";
        const text = await fetchPreviewText(stepKey, val);
        if (token === syncToken) ta.value = text;
      }
      updateRagToggleVisibility();
      updateCourseDescVisibility();
      updateCreateNextEnabled();
    }
    sel.addEventListener("change", syncTextarea);
    syncTextarea();

    createBack.hidden = createStep === 0;
    createNext.textContent =
      createStep === steps.length - 1 ? "Create & start chat" : "Continue";
    updateCreateNextEnabled();
  }

  function updateCreateNextEnabled() {
    const sel = document.getElementById("create-select");
    const ta = document.getElementById("create-custom-input");
    if (!sel) return;
    // Grey out Continue while a "Write my own…" field is still empty —
    // same pattern as the email modal's disabled submit button.
    const needsText = sel.value === CUSTOM;
    createNext.disabled = needsText && !(ta && ta.value.trim());
  }

  function saveCreateStep() {
    const sel = document.getElementById("create-select");
    const ta = document.getElementById("create-custom-input");
    if (!sel) return;
    const step = activeSteps()[createStep];
    if (step === "syllabus") {
      if (sel.value === CUSTOM) {
        createDraft.syllabus.mode = "custom";
        createDraft.syllabus.custom = ta.value;
      } else {
        createDraft.syllabus.mode = "builtin";
        createDraft.syllabus.value = sel.value;
      }
      return;
    }
    if (step === "course") {
      const cd = createDraft.course;
      if (sel.value === CUSTOM) {
        cd.mode = "custom";
        cd.custom = ta.value;
        cd.enabled = true;
      } else {
        cd.mode = "existing";
        cd.existing = sel.value;
        // cd.enabled is set by the "Include course description" toggle.
      }
      return;
    }
    if (step === "exercise") {
      const d = createDraft.exercise;
      if (sel.value === CUSTOM) {
        d.mode = "custom";
        d.custom = ta.value;
      } else {
        d.mode = "existing";
        const [kind, num] = sel.value.split(":");
        d.kind = kind === "practice" ? "practice" : "exercise";
        d.existing = num || "";
      }
      return;
    }
    const d = createDraft[step];
    if (sel.value === CUSTOM) {
      d.mode = "custom";
      d.custom = ta.value;
    } else {
      d.mode = "existing";
      d.existing = sel.value;
    }
  }

  async function openCreateModal() {
    if (createModalOpen) return;
    createError.hidden = true;
    try {
      await ensureContextOptions();
    } catch (_) {
      /* handled by the null check below */
    }
    createModalOpen = true;
    createModal.hidden = false;

    if (!contextOptions) {
      createStepBody.innerHTML = "";
      createError.textContent = "Could not load context options.";
      createError.hidden = false;
      return;
    }

    // Default each step to the first option in its dropdown. Built-ins now sort
    // first and "Create custom …" is last, so leaving existing/value empty means
    // no explicit match and the <select> falls back to its first <option>.
    createDraft = {
      course: { mode: "existing", existing: "", custom: "", enabled: true },
      exercise: { mode: "existing", existing: "", custom: "", kind: "exercise" },
      tutor: { mode: "existing", existing: "", custom: "" },
      syllabus: { mode: "builtin", value: "", custom: "" },
      useRag: false,
    };
    createStep = 0;
    renderCreateStep();
  }

  function closeCreateModal() {
    if (!createModalOpen) return;
    createModalOpen = false;
    createModal.hidden = true;
  }

  function createGoBack() {
    if (createStep === 0) return;
    saveCreateStep();
    createStep -= 1;
    renderCreateStep();
  }

  function createGoNext(event) {
    event.preventDefault();
    saveCreateStep();
    // Continue is disabled while a custom field is empty; guard the Enter-key
    // submit path too, then advance with no error message.
    const sel = document.getElementById("create-select");
    const ta = document.getElementById("create-custom-input");
    if (sel && sel.value === CUSTOM && !(ta && ta.value.trim())) return;
    if (createStep < activeSteps().length - 1) {
      createStep += 1;
      renderCreateStep();
    } else {
      finishCreate();
    }
  }

  function finishCreate() {
    const c = createDraft.course;
    const e = createDraft.exercise;
    const t = createDraft.tutor;
    const s = createDraft.syllabus;

    if (c.mode === "custom") {
      config.course = null;
      config.courseCustom = c.custom;
      config.courseEnabled = true;
    } else {
      // Keep the real slug even when the description is off — exercises,
      // figures, and RAG all key off the course identity.
      config.course = c.existing;
      config.courseCustom = null;
      config.courseEnabled = c.enabled !== false;
    }

    // A custom course has no built-in exercises, so its exercise is custom too.
    if (c.mode === "custom" || e.mode === "custom") {
      config.exercise = null;
      config.exerciseCustom = e.custom;
      config.exerciseKind = "exercise";
    } else {
      config.exercise = e.existing;
      config.exerciseCustom = null;
      config.exerciseKind = e.kind === "practice" ? "practice" : "exercise";
    }

    if (t.mode === "custom") {
      config.tutor = null;
      config.tutorCustom = t.custom;
    } else {
      config.tutor = t.existing;
      config.tutorCustom = null;
    }

    if (s.mode === "custom") {
      config.syllabusCustom = s.custom;
      config.syllabus = false;
    } else if (s.value === "default") {
      config.syllabusCustom = null;
      config.syllabus = true;
    } else {
      config.syllabusCustom = null;
      config.syllabus = false;
    }

    // RAG toggle → per-conversation context mode. When on, course/syllabus/
    // lectures are retrieved (the syllabus step was skipped), so force syllabus
    // off; when off, pin full_context so an indexed course isn't silently RAG'd.
    if (createDraft.useRag) {
      config.contextMode = "rag";
      config.syllabus = false;
      config.syllabusCustom = null;
    } else {
      config.contextMode = "full_context";
    }

    if (config.courseCustom != null) {
      if (courseNameEl) courseNameEl.textContent = "Custom context";
    } else {
      const chosen = courseBySlug(config.course);
      if (courseNameEl) {
        courseNameEl.textContent = chosen ? chosen.name || "" : "Custom context";
      }
    }

    closeCreateModal();
    startNewChat();
  }

  // ---- Step 7: email modal --------------------------------------------------

  async function submitEmailStage() {
    const emailValue = emailInput.value.trim();
    if (!emailLooksValid(emailValue)) return;

    emailSubmit.disabled = true;
    emailError.hidden = true;

    try {
      const response = await fetch("/api/identity/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: emailValue }),
      });
      if (!response.ok) {
        let reason = "Could not check that email, please try again";
        try {
          const body = await response.json();
          if (body && body.reason) reason = body.reason;
        } catch (_) {
          /* ignore */
        }
        emailError.textContent = reason;
        emailError.hidden = false;
        emailSubmit.disabled = false;
        return;
      }
      const data = await response.json();
      modalConfirmedEmail = data.email;
      modalEmailExists = !!data.exists;
      setModalStage("password");
      passwordInput.focus();
    } catch (err) {
      emailError.textContent =
        "Cannot reach AskTIM Sandbox. Check your connection and try again.";
      emailError.hidden = false;
      emailSubmit.disabled = false;
    }
  }

  async function submitPasswordStage() {
    const passwordValue = passwordInput.value;
    if (!passwordLooksValid(passwordValue)) return;

    emailSubmit.disabled = true;
    emailError.hidden = true;

    try {
      const response = await fetch("/api/identity", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: modalConfirmedEmail,
          password: passwordValue,
        }),
      });

      if (!response.ok) {
        let reason = "Could not save your details. Please try again.";
        let errorCode = "";
        try {
          const body = await response.json();
          if (body && body.error) errorCode = body.error;
          if (body && body.reason) reason = body.reason;
        } catch (_) {
          /* ignore */
        }
        if (errorCode === "wrong_password") {
          reason = "Wrong password, try again";
          passwordInput.value = "";
          updateEmailSubmit();
          passwordInput.focus();
        }
        emailError.textContent = reason;
        emailError.hidden = false;
        emailSubmit.disabled = false;
        return;
      }

      // Mark local state so maybeShowEmailModal won't reopen this page load.
      // The actual cookie was set by the server response.
      document.body.dataset.hasEmail = "true";
      refreshAddEmailVisibility();
      closeEmailModal();
      // If the sidebar is open, refresh — past anonymous conversations
      // from this session were just backfilled.
      if (sidebarOpen) {
        refreshSidebar();
      }
    } catch (err) {
      emailError.textContent =
        "Cannot reach AskTIM Sandbox. Check your connection and try again.";
      emailError.hidden = false;
      emailSubmit.disabled = false;
    }
  }

  function submitEmail(event) {
    event.preventDefault();
    if (modalStage === "email") {
      submitEmailStage();
    } else {
      submitPasswordStage();
    }
  }

  function backToEmailStage() {
    passwordInput.value = "";
    modalEmailExists = null;
    emailError.hidden = true;
    setModalStage("email");
    emailInput.focus();
    emailInput.select();
  }

  function convertThinkingToTutor(bubble) {
    // Reuse the thinking placeholder as the tutor bubble so the message
    // doesn't visibly jump. Clear the "AskTIM is thinking…" copy on the
    // first delta and flip the styling class.
    bubble.className = "message message-tutor";
    bubble.textContent = "";
  }

  function parseSSEFrame(frame) {
    // Pull `event: name` and `data: ...` out of one SSE frame. The frame
    // arrives with its inter-frame `\n\n` already stripped by the caller.
    let eventName = "message";
    const dataLines = [];
    for (const rawLine of frame.split("\n")) {
      if (!rawLine || rawLine.startsWith(":")) continue;
      if (rawLine.startsWith("event:")) {
        eventName = rawLine.slice(6).trim();
      } else if (rawLine.startsWith("data:")) {
        dataLines.push(rawLine.slice(5).trimStart());
      }
    }
    if (dataLines.length === 0) return null;
    let payload = null;
    try {
      payload = JSON.parse(dataLines.join("\n"));
    } catch (_) {
      return null;
    }
    return { event: eventName, data: payload };
  }

  async function sendMessage() {
    const text = composerInput.value.trim();
    const outgoingImages = stagedImages.slice();
    if ((!text && outgoingImages.length === 0) || isSending) return;

    hideError();
    // Optimistically render the student bubble (with any attached image
    // thumbnails) + a "thinking" placeholder. As soon as the first streamed
    // delta arrives we morph the thinking bubble into the tutor bubble.
    const previewSrcs = outgoingImages.map((item) => item.url);
    const studentBubble = renderMessage("student", text, previewSrcs);
    const tutorBubble = renderThinking();
    let tutorBubbleActive = false; // false until first delta lands
    const originalText = composerInput.value;
    composerInput.value = "";
    stagedImages = [];
    renderStagedPreviews();
    setSending(true);

    // The fields that go on every chat send, JSON or multipart.
    const fields = {
      text: text,
      course: config.course,
      exercise: config.exercise,
      exercise_kind: config.exerciseKind,
      tutor: config.tutor,
      course_enabled: config.courseEnabled,
      syllabus: config.syllabus,
    };
    // One-off custom context (Create-context wizard) — only sent when set.
    if (config.courseCustom != null) fields.course_custom = config.courseCustom;
    if (config.exerciseCustom != null) fields.exercise_custom = config.exerciseCustom;
    if (config.tutorCustom != null) fields.tutor_custom = config.tutorCustom;
    if (config.syllabusCustom != null) fields.syllabus_custom = config.syllabusCustom;
    if (config.contextMode != null) fields.context_mode = config.contextMode;
    if (conversationId) fields.conversation_id = conversationId;

    let body;
    let headers;
    if (outgoingImages.length > 0) {
      const form = new FormData();
      for (const [k, v] of Object.entries(fields)) {
        form.append(k, typeof v === "boolean" ? String(v) : v);
      }
      for (const item of outgoingImages) {
        form.append("images", item.file, item.file.name);
      }
      body = form; // browser sets the multipart Content-Type + boundary
      headers = undefined;
    } else {
      body = JSON.stringify(fields);
      headers = { "Content-Type": "application/json" };
    }

    const revokeOutgoing = () => {
      for (const item of outgoingImages) URL.revokeObjectURL(item.url);
    };

    const controller = new AbortController();
    currentChatController = controller;
    let sawDone = false;
    let streamError = null;

    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: headers,
        body: body,
        signal: controller.signal,
      });

      if (!response.ok) {
        tutorBubble.remove();
        studentBubble.remove();
        revokeOutgoing();
        composerInput.value = originalText;
        showError("Something went wrong, please try again");
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let sseBuffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        sseBuffer += decoder.decode(value, { stream: true });

        // Split on the SSE event delimiter. The last segment may be
        // an incomplete frame — keep it in the buffer for next loop.
        let separatorIdx;
        while ((separatorIdx = sseBuffer.indexOf("\n\n")) !== -1) {
          const rawFrame = sseBuffer.slice(0, separatorIdx);
          sseBuffer = sseBuffer.slice(separatorIdx + 2);
          const parsed = parseSSEFrame(rawFrame);
          if (!parsed) continue;
          if (parsed.event === "delta") {
            const piece = parsed.data && parsed.data.text;
            if (typeof piece === "string" && piece.length > 0) {
              if (!tutorBubbleActive) {
                convertThinkingToTutor(tutorBubble);
                tutorBubbleActive = true;
              }
              tutorBubble.textContent += piece;
              messageList.scrollTop = messageList.scrollHeight;
            }
          } else if (parsed.event === "done") {
            sawDone = true;
            const finalReply = parsed.data && parsed.data.reply;
            if (typeof finalReply === "string") {
              if (!tutorBubbleActive) {
                convertThinkingToTutor(tutorBubble);
                tutorBubbleActive = true;
              }
              // Server's parsed reply is authoritative — replace
              // any tokens we'd accumulated in case they drifted. Render
              // markdown now that the full (table-complete) reply is in hand.
              setMessageContent(tutorBubble, "tutor", finalReply);
              appendReasoning(
                tutorBubble,
                parsed.data && parsed.data.pedagogical_reasoning,
              );
              messageList.scrollTop = messageList.scrollHeight;
            }
            if (parsed.data && parsed.data.conversation_id) {
              conversationId = parsed.data.conversation_id;
            }
            if (
              typeof (parsed.data && parsed.data.student_message_count) ===
              "number"
            ) {
              studentMessageCount = parsed.data.student_message_count;
            }
          } else if (parsed.event === "error") {
            streamError =
              (parsed.data && parsed.data.reason) ||
              "Something went wrong. Please try again.";
          }
        }
      }

      if (streamError) {
        tutorBubble.remove();
        studentBubble.remove();
        revokeOutgoing();
        composerInput.value = originalText;
        showError("Something went wrong, please try again");
        return;
      }

      if (!sawDone) {
        tutorBubble.remove();
        studentBubble.remove();
        revokeOutgoing();
        composerInput.value = originalText;
        showError("Something went wrong, please try again");
        return;
      }

      maybeShowEmailModal(studentMessageCount);
      // If the sidebar is open, silently re-fetch so the conversation
      // that just got a new message floats to the top of the list.
      if (sidebarOpen) {
        refreshSidebar({ showLoading: false });
      }
    } catch (err) {
      if (err && err.name === "AbortError") {
        // Student switched to a past conversation mid-request.
        // Roll back the optimistic bubbles without showing an error.
        tutorBubble.remove();
        studentBubble.remove();
        revokeOutgoing();
      } else {
        tutorBubble.remove();
        studentBubble.remove();
        revokeOutgoing();
        composerInput.value = originalText;
        showError("Something went wrong, please try again");
      }
    } finally {
      if (currentChatController === controller) {
        currentChatController = null;
      }
      setSending(false);
      composerInput.focus();
    }
  }

  composerForm.addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage();
  });

  composerInput.addEventListener("input", updateSendButton);

  composerInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });

  // Image attach: paperclip opens the file picker; selecting files stages them.
  if (attachButton && imageInput) {
    attachButton.addEventListener("click", () => imageInput.click());
    imageInput.addEventListener("change", () => {
      addStagedFiles(imageInput.files);
      imageInput.value = ""; // reset so the same file can be re-picked
    });
  }

  // Drag-and-drop images onto the composer.
  if (composerForm) {
    composerForm.addEventListener("dragover", (event) => {
      if (event.dataTransfer && Array.from(event.dataTransfer.types || []).includes("Files")) {
        event.preventDefault();
        composerForm.classList.add("composer-dragover");
      }
    });
    composerForm.addEventListener("dragleave", (event) => {
      if (event.target === composerForm) composerForm.classList.remove("composer-dragover");
    });
    composerForm.addEventListener("drop", (event) => {
      if (event.dataTransfer && event.dataTransfer.files && event.dataTransfer.files.length) {
        event.preventDefault();
        composerForm.classList.remove("composer-dragover");
        addStagedFiles(event.dataTransfer.files);
      }
    });
  }

  // Paste images straight into the composer (e.g. a clipboard screenshot).
  // Only intercepts when the clipboard actually carries image files, so a
  // normal text paste falls through to the textarea untouched.
  if (composerInput) {
    composerInput.addEventListener("paste", (event) => {
      const items = (event.clipboardData && event.clipboardData.items) || [];
      const files = [];
      for (const item of items) {
        if (item.kind === "file" && item.type.startsWith("image/")) {
          const file = item.getAsFile();
          if (file) files.push(file);
        }
      }
      if (files.length) {
        event.preventDefault();
        addStagedFiles(files);
      }
    });
  }

  errorDismiss.addEventListener("click", hideError);

  // Email + password modal wiring
  emailInput.addEventListener("input", updateEmailSubmit);
  passwordInput.addEventListener("input", updateEmailSubmit);
  emailForm.addEventListener("submit", submitEmail);
  emailChangeBtn.addEventListener("click", backToEmailStage);
  emailSkip.addEventListener("click", () =>
    closeEmailModal({ dismissed: true }),
  );
  emailModal.addEventListener("click", (event) => {
    // Backdrop click = skip; clicks inside the card are ignored
    if (event.target === emailModal) {
      closeEmailModal({ dismissed: true });
    }
  });

  // History sidebar + detail view wiring (Step 8)
  historyToggle.addEventListener("click", toggleSidebar);
  sidebarClose.addEventListener("click", closeSidebar);
  newChatButton.addEventListener("click", startNewChat);
  addEmailButton.addEventListener("click", () => openEmailModal({ manual: true }));
  detailBack.addEventListener("click", closeDetailView);

  // Create-context wizard wiring (sandbox_ui only)
  createContextButton.addEventListener("click", openCreateModal);
  createCancel.addEventListener("click", closeCreateModal);
  createBack.addEventListener("click", createGoBack);
  createForm.addEventListener("submit", createGoNext);
  createModal.addEventListener("click", (event) => {
    if (event.target === createModal) closeCreateModal();
  });

  // Unified Escape: close in z-order — detail > create > email > sidebar
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!detailView.hidden) {
      closeDetailView();
    } else if (createModalOpen) {
      closeCreateModal();
    } else if (modalOpen) {
      closeEmailModal({ dismissed: true });
    } else if (sidebarOpen) {
      closeSidebar();
    }
  });

  // Initial visibility for the sidebar's Add-email button (driven by
  // the body's data-has-email attribute the server stamps each render).
  refreshAddEmailVisibility();

  // Auto-focus the composer so an embedded iframe is immediately typable
  // (works once the iframe has focus; harmless on first paint otherwise).
  composerInput.focus();
  updateSendButton();
})();
