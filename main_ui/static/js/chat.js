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

    let conversationId = null;
    let isSending = false;
    let studentMessageCount = 0;

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

        try {
            const response = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
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
        } catch (err) {
            thinkingBubble.remove();
            studentBubble.remove();
            composerInput.value = originalText;
            showError("Cannot reach AskTIM. Check your connection and try again.");
        } finally {
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

    // Auto-focus the composer so an embedded iframe is immediately typable
    // (works once the iframe has focus; harmless on first paint otherwise).
    composerInput.focus();
    updateSendButton();
})();
