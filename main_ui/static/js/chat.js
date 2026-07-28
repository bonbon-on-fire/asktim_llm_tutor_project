"use strict";

(() => {
  const configEl = document.getElementById("tutor-config");
  const config = JSON.parse(configEl.textContent);

  const messageList = document.getElementById("message-list");
  const composerForm = document.getElementById("composer");
  const composerInput = document.getElementById("composer-input");
  const sendButton = document.getElementById("send-button");
  const attachButton = document.getElementById("attach-button");
  const imageInput = document.getElementById("image-input");
  const composerPreviews = document.getElementById("composer-previews");

  // Client-side mirror of utils/uploads.py and utils/attachments.py caps. The
  // server re-validates, so these only exist to give fast, friendly feedback
  // before upload.
  const ALLOWED_IMAGE_TYPES = ["image/png", "image/jpeg"];
  const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
  const ALLOWED_FILE_EXTS = [".csv", ".tsv", ".xlsx", ".pdf", ".docx", ".txt"];
  const MAX_FILE_BYTES = 5 * 1024 * 1024;
  // Images + non-image files combined, per message — mirrors
  // utils/uploads.py's enforce_combined_cap.
  const MAX_ATTACHMENTS_PER_MESSAGE = 3;

  // Mirror of utils/tokens.py — keep these constants identical to the
  // server's per-message token estimate. The server re-validates on every
  // send; this only gives fast, friendly feedback before the request goes out.
  const CHARS_PER_TOKEN = 4;
  const TOKENS_PER_IMAGE = 1600;
  const MAX_MESSAGE_TOKENS = 10000; // mirror of config default MAX_MESSAGE_TOKENS
  function estimateMessageTokens(text, extractedChars, nImages) {
    const chars = (text ? text.length : 0) + (extractedChars || 0);
    return (
      Math.ceil(chars / CHARS_PER_TOKEN) + Math.max(0, nImages) * TOKENS_PER_IMAGE
    );
  }

  // Staged uploads for the next send: { file, url } (url is an object URL for
  // the preview thumbnail, revoked when cleared).
  let stagedImages = [];
  // Staged non-image files for the next send: { file } (rendered as chips, no preview).
  let stagedFiles = [];
  const errorBanner = document.getElementById("error-banner");
  const errorText = document.getElementById("error-text");
  const errorDismiss = document.getElementById("error-dismiss");

  const emailModal = document.getElementById("email-modal");
  const emailModalBody = document.getElementById("email-modal-body");
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
  // The template's default copy, restored whenever the modal opens for a
  // reason other than a mandatory login gate (which overrides it below).
  const DEFAULT_MODAL_BODY = emailModalBody ? emailModalBody.textContent : "";

  const MIN_PASSWORD_LENGTH = 6;

  // Modal moves through two stages. "email" gathers the username, then the
  // server is probed to learn whether it's already registered; "password"
  // collects the password with copy that depends on the probe result.
  let modalStage = "email"; // "email" | "password"
  let modalEmailExists = null; // null until probed; then true|false
  let modalConfirmedEmail = ""; // the email we advanced past stage 1 with
  // True while the modal is a mandatory login gate (no Skip, no
  // backdrop-close) rather than the old dismissible nudge.
  let modalMandatory = false;

  const historyToggle = document.getElementById("history-toggle");
  const sidebar = document.getElementById("sidebar");
  const sidebarClose = document.getElementById("sidebar-close");
  const sidebarList = document.getElementById("sidebar-list");
  const sidebarEmpty = document.getElementById("sidebar-empty");
  const newChatButton = document.getElementById("new-chat");
  const addEmailButton = document.getElementById("add-email");
  const detailView = document.getElementById("detail-view");
  const detailBack = document.getElementById("detail-back");
  const detailMeta = document.getElementById("detail-meta");
  const detailMessages = document.getElementById("detail-messages");

  let conversationId = null;
  let isSending = false;
  let studentMessageCount = 0;
  // True once a `done` event (or a 403 conversation_limit fallback) reports
  // the per-conversation token ceiling reached; disables the composer until
  // "New chat".
  let conversationLocked = false;
  let modalOpen = false;
  let sidebarOpen = false;
  // AbortController for the in-flight POST /api/chat — set when sending,
  // aborted when the student switches to a past conversation mid-request.
  let currentChatController = null;

  function updateSendButton() {
    const hasText = composerInput.value.trim().length > 0;
    sendButton.disabled =
      conversationLocked ||
      isSending ||
      (!hasText && stagedImages.length === 0 && stagedFiles.length === 0);
  }

  function setSending(sending) {
    isSending = sending;
    composerInput.disabled = sending || conversationLocked;
    if (attachButton) attachButton.disabled = sending || conversationLocked;
    updateSendButton();
  }

  // ---- Conversation-length ceiling (Step 4: conversation-limit lockout) ----

  function lockConversation(reason) {
    // Idempotent — the streamed `done` event and a 403 conversation_limit
    // fallback on the next send can both call this for the same conversation.
    conversationLocked = true;
    composerInput.disabled = true;
    if (attachButton) attachButton.disabled = true;
    updateSendButton();
    showError(
      reason ||
        "This chat reached its length limit — start a new chat to continue.",
    );
  }

  function unlockConversation() {
    conversationLocked = false;
    composerInput.disabled = isSending;
    if (attachButton) attachButton.disabled = isSending;
    updateSendButton();
  }

  function clearStagedImages() {
    for (const item of stagedImages) {
      URL.revokeObjectURL(item.url);
    }
    stagedImages = [];
    renderStagedPreviews();
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

  // A "📎 <name>" pill — used both for a staged (not-yet-sent) file and for a
  // file attached to an already-sent/past message.
  function renderFileChip(name) {
    const chip = document.createElement("span");
    chip.className = "attachment-chip";
    const icon = document.createElement("span");
    icon.className = "attachment-chip-icon";
    icon.setAttribute("aria-hidden", "true");
    // Static markup only (no user input); the filename is a separate text node below.
    icon.innerHTML =
      '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" ' +
      'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>' +
      '<polyline points="14 2 14 8 20 8"/></svg>';
    const label = document.createElement("span");
    label.className = "attachment-chip-name";
    label.textContent = name; // user-controlled — keep as a text node (no innerHTML)
    chip.appendChild(icon);
    chip.appendChild(label);
    return chip;
  }

  // Staged-file variant of the chip: adds a remove (×) button.
  function renderRemovableFileChip(name, onRemove) {
    const chip = renderFileChip(name);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "attachment-chip-remove";
    remove.setAttribute("aria-label", "Remove file");
    remove.textContent = "×";
    remove.addEventListener("click", onRemove);
    chip.appendChild(remove);
    return chip;
  }

  function renderStagedPreviews() {
    if (!composerPreviews) return;
    composerPreviews.innerHTML = "";
    if (stagedImages.length === 0 && stagedFiles.length === 0) {
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
    stagedFiles.forEach((item, index) => {
      const chip = renderRemovableFileChip(item.file.name, () => {
        stagedFiles.splice(index, 1);
        renderStagedPreviews();
        updateSendButton();
      });
      composerPreviews.appendChild(chip);
    });
  }

  function fileExtension(name) {
    const idx = (name || "").lastIndexOf(".");
    return idx === -1 ? "" : name.slice(idx).toLowerCase();
  }

  function addStagedFiles(fileList) {
    const files = Array.from(fileList || []);
    if (files.length === 0) return;
    // Attachments require a logged-in username (mirrors the server's
    // `_login_required("attachment")` 403) — gate here before staging
    // anything, and cancel the attach entirely.
    if (!hasEmailSet()) {
      openEmailModal({ mandatory: true, trigger: "attachment" });
      return;
    }
    for (const file of files) {
      if (stagedImages.length + stagedFiles.length >= MAX_ATTACHMENTS_PER_MESSAGE) {
        showError(
          "You can upload up to " + MAX_ATTACHMENTS_PER_MESSAGE + " files at a time",
        );
        break;
      }
      if (ALLOWED_IMAGE_TYPES.includes(file.type)) {
        if (file.size > MAX_IMAGE_BYTES) {
          showError("Images must be 10 MB or smaller");
          continue;
        }
        stagedImages.push({ file: file, url: URL.createObjectURL(file) });
        continue;
      }
      if (ALLOWED_FILE_EXTS.includes(fileExtension(file.name))) {
        if (file.size > MAX_FILE_BYTES) {
          showError("Files must be 5 MB or smaller");
          continue;
        }
        stagedFiles.push({ file: file });
        continue;
      }
      showError(
        "Only PNG/JPEG images or " +
          ALLOWED_FILE_EXTS.join(", ") +
          " files are supported",
      );
    }
    renderStagedPreviews();
    updateSendButton();
  }

  function setMessageContent(el, role, content) {
    // Tutor replies are markdown + LaTeX math (\(...\), \[...\]). renderTutorMarkdown
    // parses markdown, renders math with KaTeX, and DOMPurify-sanitizes — one
    // sanitized innerHTML write, so the no-raw-innerHTML XSS guarantee holds.
    // Student text, and any case where the libs failed to load, stay textContent.
    const rich =
      role === "tutor" && typeof window.renderTutorMarkdown === "function"
        ? window.renderTutorMarkdown(content)
        : null;
    if (rich !== null) {
      el.classList.add("message-rich");
      el.innerHTML = rich;
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

  function appendFileChips(li, names) {
    if (!names || names.length === 0) return;
    const wrap = document.createElement("div");
    wrap.className = "message-attachments";
    for (const name of names) {
      wrap.appendChild(renderFileChip(name));
    }
    li.appendChild(wrap);
  }

  function renderMessage(role, content, imageSrcs, attachmentNames, messageId, rating) {
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
    appendFileChips(li, attachmentNames);
    messageList.appendChild(li);
    if (role === "tutor") {
      // After the bubble is in the DOM, drop the thumbs in as the next sibling.
      appendRating(li, messageId, rating);
    }
    // Always auto-scroll to bottom. Known papercut: fights user scrolling.
    messageList.scrollTop = messageList.scrollHeight;
    return li;
  }

  function renderThinking() {
    const li = document.createElement("li");
    li.className = "message message-thinking";
    li.appendChild(document.createTextNode("AskTIM is thinking"));
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
    // The `tutor_username` cookie is HttpOnly so JS can't read it directly.
    // The server stamps document.body.dataset.hasEmail on every render
    // based on the request's cookie; we also flip it locally after a
    // successful submission so the modal doesn't re-open this page load.
    return document.body.dataset.hasEmail === "true";
  }

  function refreshAddEmailVisibility() {
    // Show the "Add username" sidebar button only when no username is set —
    // gives skipped-the-modal students a way back in.
    addEmailButton.hidden = hasEmailSet();
  }

  function emailLooksValid(value) {
    // Login is by username, not email — accept any non-empty value within
    // the length the backend allows (see _validate_username).
    return value.length > 0 && value.length <= 100;
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

  // trigger: "attachment" | "message_count" | null — only used to tailor the
  // mandatory-mode copy (which action is gated).
  function mandatoryModalCopy(trigger) {
    return trigger === "attachment"
      ? "Log in to attach files or images and save your chats to help AskTIM provide better and more consistent help."
      : "Log in to keep chatting.";
  }

  function openEmailModal({ manual = false, mandatory = false, trigger = null } = {}) {
    if (modalOpen) {
      // Already open (e.g. the count-based gate and an attach attempt raced) —
      // let a mandatory request upgrade a still-open dismissible modal.
      if (mandatory && !modalMandatory) {
        modalMandatory = true;
        emailSkip.hidden = true;
        if (emailModalBody) emailModalBody.textContent = mandatoryModalCopy(trigger);
      }
      return;
    }
    modalOpen = true;
    modalMandatory = mandatory;
    emailError.hidden = true;
    emailError.textContent = "";
    emailInput.value = "";
    passwordInput.value = "";
    modalEmailExists = null;
    modalConfirmedEmail = "";
    if (mandatory) {
      // Login is required to proceed — no Skip/Cancel, no backdrop-close.
      emailSkip.hidden = true;
      if (emailModalBody) emailModalBody.textContent = mandatoryModalCopy(trigger);
    } else {
      // Manual open (the "Add username" button) is dismissible as "Cancel";
      // the automatic prompt after each message reads "Skip".
      emailSkip.hidden = false;
      emailSkip.textContent = manual ? "Cancel" : "Skip";
      if (emailModalBody) emailModalBody.textContent = DEFAULT_MODAL_BODY;
    }
    setModalStage("email");
    emailModal.hidden = false;
    emailInput.focus();
  }

  function closeEmailModal() {
    if (!modalOpen) return;
    modalOpen = false;
    modalMandatory = false;
    emailModal.hidden = true;
    composerInput.focus();
  }

  // ---- Per-message thumbs up/down (stored as -1/0/1 on the tutor message) ----
  const THUMB_UP_SVG =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 10v11"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a2.5 2.5 0 0 1 3 3.88Z"/></svg>';
  const THUMB_DOWN_SVG =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 14V3"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a2.5 2.5 0 0 1-3-3.88Z"/></svg>';

  async function postRating(messageId, rating) {
    try {
      await fetch(`/api/message/${messageId}/rating`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rating: rating }),
      });
    } catch (e) {
      /* best-effort — a failed rating should never disrupt the chat */
    }
  }

  // Append a thumbs up/down control under a tutor message. `rating` is the
  // stored value (-1/0/1); clicking a thumb sets it, clicking the active thumb
  // again clears it back to 0. Persists via POST /api/message/<id>/rating.
  function appendRating(li, messageId, rating) {
    if (!messageId) return;
    let current = rating === 1 || rating === -1 ? rating : 0;
    // A sibling list item placed AFTER the bubble, so the thumbs sit under the
    // message but outside the bubble background. `li` must already be in the DOM.
    const bar = document.createElement("li");
    bar.className = "msg-rating";

    const up = document.createElement("button");
    up.type = "button";
    up.className = "rating-btn rating-up";
    up.setAttribute("aria-label", "Thumbs up");
    up.innerHTML = THUMB_UP_SVG;

    const down = document.createElement("button");
    down.type = "button";
    down.className = "rating-btn rating-down";
    down.setAttribute("aria-label", "Thumbs down");
    down.innerHTML = THUMB_DOWN_SVG;

    function paint() {
      up.classList.toggle("is-active", current === 1);
      down.classList.toggle("is-active", current === -1);
      up.setAttribute("aria-pressed", current === 1 ? "true" : "false");
      down.setAttribute("aria-pressed", current === -1 ? "true" : "false");
    }
    function choose(value) {
      const next = current === value ? 0 : value; // toggle off if re-clicked
      current = next;
      paint();
      postRating(messageId, next);
    }
    up.addEventListener("click", () => choose(1));
    down.addEventListener("click", () => choose(-1));
    paint();
    bar.appendChild(up);
    bar.appendChild(down);
    li.insertAdjacentElement("afterend", bar);
  }

  // Login is mandatory once the free-message threshold is passed — mirrors
  // the server's config.free_messages_before_login (default 3, see
  // main_ui/config.py FREE_MESSAGES_BEFORE_LOGIN). Once `count` reaches that
  // threshold the *next* send would be rejected server-side
  // (403 login_required), so gate it here first with a non-dismissible modal.
  const FREE_MESSAGES_BEFORE_LOGIN = 3;

  function maybeShowEmailModal(count) {
    if (hasEmailSet()) return;
    if (count < FREE_MESSAGES_BEFORE_LOGIN) return;
    openEmailModal({ mandatory: true, trigger: "message_count" });
  }

  // ---- Step 8: history sidebar + read-only detail view ------------------

  function showSidebarEmpty(text) {
    sidebarEmpty.textContent = text;
    sidebarEmpty.hidden = false;
  }

  function renderHistoryEntries(email, conversations) {
    sidebarList.innerHTML = "";
    if (!email) {
      showSidebarEmpty("Log in to save chat history");
      return;
    }
    if (!conversations || conversations.length === 0) {
      showSidebarEmpty("No past conversations yet");
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
    // "Exercise 3 · May 19 · 8 messages" (or, per that course's config,
    // "Week 3 Practice · ...") — strip leading zeros from the number; show the
    // most-recent-active date. Each row is labelled by ITS OWN course: the
    // server sends a per-conversation `label_template` (from that course's
    // labels), so a mixed-course history renders each entry in its course's
    // format. Fall back to the current page's `labels` map, then the built-in
    // defaults. "{n}" = the number.
    const exNumber = parseInt(c.exercise_number, 10);
    const number = Number.isFinite(exNumber) ? exNumber : c.exercise_number;
    const labels = config.labels || {};
    const template =
      c.label_template ||
      labels[c.exercise_kind] ||
      (c.exercise_kind === "practice" ? "Practice {n}" : "Exercise {n}");
    const parts = [template.replace("{n}", number)];
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
      renderHistoryEntries(data.username, data.conversations);
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
    // The lockout is per-conversation and this endpoint doesn't report the
    // loaded conversation's token total; optimistically unlock and let a
    // 403 conversation_limit on the next send re-lock if it's already full.
    unlockConversation();

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
        const attachmentNames = (m.attachments || []).map((a) => a.filename);
        renderMessage(m.role, m.content, srcs, attachmentNames, m.id, m.rating);
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
    hideError();
    unlockConversation(); // "New chat" is the escape from a length-limit lockout
    highlightActiveEntry();
    composerInput.focus();
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
        body: JSON.stringify({ username: emailValue }),
      });
      if (!response.ok) {
        let reason = "Could not check that username, please try again";
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
      modalConfirmedEmail = data.username;
      modalEmailExists = !!data.exists;
      setModalStage("password");
      passwordInput.focus();
    } catch (err) {
      emailError.textContent =
        "Cannot reach AskTIM, check your connection and try again";
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
          username: modalConfirmedEmail,
          password: passwordValue,
        }),
      });

      if (!response.ok) {
        let reason = "Could not save your details, please try again";
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
        "Cannot reach AskTIM, check your connection and try again";
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
    if (conversationLocked) return;
    // Belt-and-braces: the mandatory modal's overlay already blocks the
    // composer visually, but guard the entry point too.
    if (modalOpen && modalMandatory) return;

    const text = composerInput.value.trim();
    const outgoingImages = stagedImages.slice();
    const outgoingFiles = stagedFiles.slice();
    if (
      (!text && outgoingImages.length === 0 && outgoingFiles.length === 0) ||
      isSending
    )
      return;

    // Per-message token cap (Step 2) — mirrors the server's check in
    // main_ui/routes/chat.py so an oversized paste fails fast, without a
    // round trip, and WITHOUT clearing the composer.
    const extractedCharsProxy = outgoingFiles.reduce(
      (sum, item) => sum + item.file.size,
      0,
    );
    const estimatedTokens = estimateMessageTokens(
      text,
      extractedCharsProxy,
      outgoingImages.length,
    );
    if (estimatedTokens >= MAX_MESSAGE_TOKENS) {
      showError("Message is too long, shorten it or split it across multiple messages");
      return;
    }

    hideError();
    // Optimistically render the student bubble (with any attached image
    // thumbnails / file chips) + a "thinking" placeholder. As soon as the
    // first streamed delta arrives we morph the thinking bubble into the
    // tutor bubble.
    const previewSrcs = outgoingImages.map((item) => item.url);
    const attachmentNames = outgoingFiles.map((item) => item.file.name);
    const studentBubble = renderMessage("student", text, previewSrcs, attachmentNames);
    const tutorBubble = renderThinking();
    let tutorBubbleActive = false; // false until first delta lands
    const originalText = composerInput.value;
    composerInput.value = "";
    // Detach staged previews from the composer; the object URLs stay alive on
    // the rendered bubble and are revoked when the bubble is rolled back/cleared.
    stagedImages = [];
    stagedFiles = [];
    renderStagedPreviews();
    setSending(true);

    let body;
    let headers;
    if (outgoingImages.length > 0 || outgoingFiles.length > 0) {
      // Multipart so we can carry image/file uploads alongside the text fields.
      const form = new FormData();
      form.append("text", text);
      form.append("course", config.course);
      form.append("exercise", config.exercise);
      form.append("tutor", config.tutor);
      form.append("exercise_kind", config.exercise_kind || "exercise");
      if (conversationId) form.append("conversation_id", conversationId);
      for (const item of outgoingImages) {
        form.append("images", item.file, item.file.name);
      }
      for (const item of outgoingFiles) {
        form.append("files", item.file, item.file.name);
      }
      body = form; // browser sets the multipart Content-Type + boundary
      headers = undefined;
    } else {
      const payload = {
        text: text,
        course: config.course,
        exercise: config.exercise,
        tutor: config.tutor,
        exercise_kind: config.exercise_kind || "exercise",
      };
      if (conversationId) payload.conversation_id = conversationId;
      body = JSON.stringify(payload);
      headers = { "Content-Type": "application/json" };
    }

    const revokeOutgoing = () => {
      for (const item of outgoingImages) URL.revokeObjectURL(item.url);
    };

    const controller = new AbortController();
    currentChatController = controller;
    let sawDone = false;
    let streamError = null;
    let conversationLimitReached = false;

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
        // Pre-stream JSON errors (Step 3 / Step 4 fallbacks): message_too_long,
        // login_required (with `trigger`), conversation_limit. The server is
        // authoritative here — this is the fallback path when our client-side
        // pre-checks didn't already catch it (e.g. stale login state).
        let errorBody = null;
        try {
          errorBody = await response.json();
        } catch (_) {
          /* not JSON — fall through to the generic message below */
        }
        const errorCode = errorBody && errorBody.error;
        if (errorCode === "login_required") {
          openEmailModal({ mandatory: true, trigger: errorBody.trigger });
        } else if (errorCode === "conversation_limit") {
          lockConversation(errorBody.reason);
        } else if (errorCode === "message_too_long") {
          showError(
            (errorBody && errorBody.reason) ||
              "Message is too long, shorten it or split it across multiple messages",
          );
        } else {
          showError("Something went wrong, please try again");
        }
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
              appendRating(
                tutorBubble,
                parsed.data && parsed.data.tutor_message_id,
                0,
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
            // `conversation_tokens` (running total) rides along for parity
            // with the server; `conversation_limit_reached` is what actually
            // drives the lockout below.
            if (parsed.data && parsed.data.conversation_limit_reached === true) {
              conversationLimitReached = true;
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

      if (conversationLimitReached) {
        // Step 4: length-ceiling lockout takes priority over the login gate —
        // a locked composer makes further sends moot either way.
        lockConversation();
      } else {
        maybeShowEmailModal(studentMessageCount);
      }
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
    attachButton.addEventListener("click", () => {
      // Check login before even opening the file picker — addStagedFiles()
      // re-checks too (it also covers drag-drop and paste), but this avoids
      // popping the OS file dialog just to reject the selection.
      if (!hasEmailSet()) {
        openEmailModal({ mandatory: true, trigger: "attachment" });
        return;
      }
      imageInput.click();
    });
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
  emailSkip.addEventListener("click", () => {
    // Skip is hidden in mandatory mode, but guard anyway in case of a race.
    if (modalMandatory) return;
    closeEmailModal();
  });
  emailModal.addEventListener("click", (event) => {
    // Backdrop click = skip; clicks inside the card are ignored. Disabled
    // entirely while the modal is a mandatory login gate.
    if (event.target === emailModal && !modalMandatory) {
      closeEmailModal();
    }
  });

  // History sidebar + detail view wiring (Step 8)
  historyToggle.addEventListener("click", toggleSidebar);
  sidebarClose.addEventListener("click", closeSidebar);
  newChatButton.addEventListener("click", startNewChat);
  addEmailButton.addEventListener("click", () => openEmailModal({ manual: true }));
  detailBack.addEventListener("click", closeDetailView);

  // Unified Escape: close in z-order — detail > modal > sidebar
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!detailView.hidden) {
      closeDetailView();
    } else if (modalOpen) {
      if (!modalMandatory) closeEmailModal();
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
