"use strict";

(() => {
    const configEl = document.getElementById("tutor-config");
    const config = JSON.parse(configEl.textContent);

    const messageList = document.getElementById("message-list");
    const composerForm = document.getElementById("composer");
    const composerInput = document.getElementById("composer-input");
    const sendButton = document.getElementById("send-button");
    const errorBanner = document.getElementById("error-banner");
    const errorText = document.getElementById("error-text");
    const errorDismiss = document.getElementById("error-dismiss");

    const emailModal = document.getElementById("email-modal");
    const emailForm = document.getElementById("email-form");
    const emailInput = document.getElementById("email-input");
    const emailSubmit = document.getElementById("email-submit");
    const emailSkip = document.getElementById("email-skip");
    const emailError = document.getElementById("email-error");

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
        sendButton.disabled = isSending || composerInput.value.trim().length === 0;
    }

    function setSending(sending) {
        isSending = sending;
        composerInput.disabled = sending;
        updateSendButton();
    }

    function renderMessage(role, content) {
        const li = document.createElement("li");
        li.className = "message message-" + role;
        // textContent — never innerHTML — to prevent XSS from tutor or student text.
        li.textContent = content;
        messageList.appendChild(li);
        // Always auto-scroll to bottom. Known papercut: fights user scrolling.
        messageList.scrollTop = messageList.scrollHeight;
        return li;
    }

    function renderThinking() {
        const li = document.createElement("li");
        li.className = "message message-thinking";
        li.textContent = "AskTIM is thinking…";
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

    function updateEmailSubmit() {
        emailSubmit.disabled = !emailLooksValid(emailInput.value.trim());
    }

    function openEmailModal() {
        if (modalOpen) return;
        modalOpen = true;
        emailError.hidden = true;
        emailError.textContent = "";
        emailInput.value = "";
        updateEmailSubmit();
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
        const parts = [`Exercise ${Number.isFinite(exNumber) ? exNumber : c.exercise_number}`];
        if (c.last_active_at) {
            const d = new Date(c.last_active_at);
            parts.push(d.toLocaleDateString(undefined, { month: "short", day: "numeric" }));
        }
        const count = c.message_count;
        parts.push(`${count} ${count === 1 ? "message" : "messages"}`);
        return parts.join(" · ");
    }

    function formatFullDate(isoDate) {
        if (!isoDate) return "";
        const d = new Date(isoDate);
        return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
    }

    async function refreshSidebar({ showLoading = true } = {}) {
        if (showLoading) {
            sidebarList.innerHTML = "";
            showSidebarEmpty("Loading…");
        }
        try {
            const response = await fetch("/api/history");
            if (!response.ok) {
                if (showLoading) showSidebarEmpty("Could not load history.");
                return;
            }
            const data = await response.json();
            renderHistoryEntries(data.email, data.conversations);
        } catch (err) {
            if (showLoading) showSidebarEmpty("Could not load history.");
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
                `/api/conversation/${encodeURIComponent(targetConversationId)}`
            );
            if (!response.ok) {
                showError("Could not load that conversation.");
                return;
            }
            const data = await response.json();
            conversationId = data.id;
            studentMessageCount = (data.messages || []).filter(
                (m) => m.role === "student"
            ).length;
            for (const m of data.messages || []) {
                renderMessage(m.role, m.content);
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

    async function submitEmail(event) {
        event.preventDefault();
        const value = emailInput.value.trim();
        if (!emailLooksValid(value)) return;

        emailSubmit.disabled = true;
        emailError.hidden = true;

        try {
            const response = await fetch("/api/email", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ email: value }),
            });

            if (!response.ok) {
                let reason = "Could not save your email. Please try again.";
                try {
                    const body = await response.json();
                    if (body && body.reason) reason = body.reason;
                } catch (_) {
                    /* ignore body-parse errors */
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
            emailError.textContent = "Cannot reach AskTIM. Check your connection and try again.";
            emailError.hidden = false;
            emailSubmit.disabled = false;
        }
    }

    async function sendMessage() {
        const text = composerInput.value.trim();
        if (!text || isSending) return;

        hideError();
        // Optimistically render the student bubble + a "thinking" placeholder
        // where the tutor reply will land. Rollback both on error.
        const studentBubble = renderMessage("student", text);
        const thinkingBubble = renderThinking();
        const originalText = composerInput.value;
        composerInput.value = "";
        setSending(true);

        const payload = {
            text: text,
            course: config.course,
            exercise: config.exercise,
            tutor: config.tutor,
        };
        if (conversationId) {
            payload.conversation_id = conversationId;
        }

        const controller = new AbortController();
        currentChatController = controller;
        try {
            const response = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
                signal: controller.signal,
            });

            if (!response.ok) {
                let reason = "Something went wrong. Please try again.";
                try {
                    const body = await response.json();
                    if (body && body.reason) reason = body.reason;
                } catch (_) {
                    /* ignore body-parse errors */
                }
                thinkingBubble.remove();
                studentBubble.remove();
                composerInput.value = originalText;
                showError(reason);
                return;
            }

            const data = await response.json();
            conversationId = data.conversation_id;
            studentMessageCount = data.student_message_count;
            thinkingBubble.remove();
            renderMessage("tutor", data.reply);
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
                thinkingBubble.remove();
                studentBubble.remove();
            } else {
                thinkingBubble.remove();
                studentBubble.remove();
                composerInput.value = originalText;
                showError("Cannot reach AskTIM. Check your connection and try again.");
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

    errorDismiss.addEventListener("click", hideError);

    // Email modal wiring (Step 7)
    emailInput.addEventListener("input", updateEmailSubmit);
    emailForm.addEventListener("submit", submitEmail);
    emailSkip.addEventListener("click", () => closeEmailModal({ dismissed: true }));
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
    addEmailButton.addEventListener("click", openEmailModal);
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
