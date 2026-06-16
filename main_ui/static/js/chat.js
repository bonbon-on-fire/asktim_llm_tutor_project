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

  // Client-side mirror of utils/uploads.py caps. The server re-validates, so
  // these only exist to give fast, friendly feedback before upload.
  const ALLOWED_IMAGE_TYPES = ["image/png", "image/jpeg"];
  const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
  const MAX_IMAGES_PER_MESSAGE = 5;
  // Staged uploads for the next send: { file, url } (url is an object URL for
  // the preview thumbnail, revoked when cleared).
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

  function clearStagedImages() {
    for (const item of stagedImages) {
      URL.revokeObjectURL(item.url);
    }
    stagedImages = [];
    renderStagedPreviews();
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
      wrap.appendChild(img);
    }
    li.appendChild(wrap);
  }

  function renderMessage(role, content, imageSrcs) {
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
    messageList.appendChild(li);
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
        renderMessage(m.role, m.content, srcs);
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
        "Cannot reach AskTIM. Check your connection and try again.";
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
        "Cannot reach AskTIM. Check your connection and try again.";
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
    // Detach staged previews from the composer; the object URLs stay alive on
    // the rendered bubble and are revoked when the bubble is rolled back/cleared.
    stagedImages = [];
    renderStagedPreviews();
    setSending(true);

    let body;
    let headers;
    if (outgoingImages.length > 0) {
      // Multipart so we can carry image files alongside the text fields.
      const form = new FormData();
      form.append("text", text);
      form.append("course", config.course);
      form.append("exercise", config.exercise);
      form.append("tutor", config.tutor);
      if (conversationId) form.append("conversation_id", conversationId);
      for (const item of outgoingImages) {
        form.append("images", item.file, item.file.name);
      }
      body = form; // browser sets the multipart Content-Type + boundary
      headers = undefined;
    } else {
      const payload = {
        text: text,
        course: config.course,
        exercise: config.exercise,
        tutor: config.tutor,
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

  // Unified Escape: close in z-order — detail > modal > sidebar
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!detailView.hidden) {
      closeDetailView();
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
