
document.addEventListener("DOMContentLoaded", () => {
    const root = document.documentElement;

    // ========================================
    // 1. THEME HANDLING
    // ========================================
    const savedTheme = localStorage.getItem("smarttrip-theme");
    const themeToggle = document.getElementById("themeToggle");

    function updateThemeIcon() {
        const icon = themeToggle?.querySelector("i");
        if (!icon) return;
        if (root.classList.contains("dark")) {
            icon.className = "fa-solid fa-sun text-warning";
        } else {
            icon.className = "fa-solid fa-moon";
        }
    }

    if (savedTheme === "dark") {
        root.classList.add("dark");
    }
    updateThemeIcon();

    themeToggle?.addEventListener("click", () => {
        root.classList.toggle("dark");

        localStorage.setItem(
            "smarttrip-theme",
            root.classList.contains("dark") ? "dark" : "light"
        );
        updateThemeIcon();
    });

    // ========================================
    // 2. FLOATING AI CHATBOT
    // ========================================
    const fab = document.getElementById("aiFab");
    const chat = document.getElementById("aiChat");
    const close = document.getElementById("aiClose");
    const chatBody = chat?.querySelector(".ai-chat-body");
    const chatForm = chat?.querySelector(".ai-chat-form");
    const chatInput = chatForm?.querySelector('input[name="question"]');

    function openChat() {
        if (!chat) return;

        chat.classList.add("open");
        chat.setAttribute("aria-hidden", "false");
        fab?.setAttribute("aria-expanded", "true");

        setTimeout(() => chatInput?.focus(), 100);
    }

    function closeChat() {
        if (!chat) return;

        chat.classList.remove("open");
        chat.setAttribute("aria-hidden", "true");
        fab?.setAttribute("aria-expanded", "false");
    }

    fab?.addEventListener("click", () => {
        if (chat?.classList.contains("open")) {
            closeChat();
        } else {
            openChat();
        }
    });

    close?.addEventListener("click", closeChat);

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closeChat();
    });

    // Add a message safely without interpreting HTML.
    function addMessage(text, sender = "ai") {
        if (!chatBody) return null;

        const message = document.createElement("div");

        message.className =
            sender === "user"
                ? "ai-message ai-user-message"
                : "ai-message";

        message.textContent = text;
        chatBody.appendChild(message);
        chatBody.scrollTop = chatBody.scrollHeight;

        return message;
    }

    // Use the trip-specific assistant endpoint when inside a trip.
    function getAssistantUrl() {
        const match = window.location.pathname.match(
            /^\/trips\/(\d+)\/?$/
        );

        if (match) {
            return `/trips/${match[1]}/assistant/`;
        }

        return chatForm?.getAttribute("action") || "/assistant/";
    }

    // ========================================
    // 3. CHAT FORM SUBMISSION
    // ========================================
    if (chatForm && chatInput && chatBody) {
        chatForm.addEventListener("submit", async (event) => {
            event.preventDefault();

            const question = chatInput.value.trim();

            if (!question) return;

            const sendButton = chatForm.querySelector(
                'button[type="submit"], button'
            );

            const originalButton = sendButton?.innerHTML;

            addMessage(question, "user");
            chatInput.value = "";

            if (sendButton) sendButton.disabled = true;

            const typingMessage = addMessage("Thinking...");

            try {
                const formData = new FormData(chatForm);
                formData.set("question", question);

                const response = await fetch(getAssistantUrl(), {
                    method: "POST",
                    body: formData,
                    credentials: "same-origin",
                    headers: {
                        "X-Requested-With": "XMLHttpRequest"
                    }
                });

                if (!response.ok) {
                    throw new Error(
                        `Assistant request failed: ${response.status}`
                    );
                }

                const html = await response.text();

                const parsedPage = new DOMParser().parseFromString(
                    html,
                    "text/html"
                );

                // IMPORTANT: Extract the answer paragraph only.
                // This avoids including the SmartTrip AI heading
                // and the Local assistant / LLM response label.
                const answerElement = parsedPage.querySelector(
                    ".assistant-answer p"
                );

                if (typingMessage) {
                    typingMessage.remove();
                }

                if (answerElement) {
                    const answerText = (
                        answerElement.innerText ||
                        answerElement.textContent ||
                        ""
                    ).trim();

                    if (answerText) {
                        addMessage(answerText);
                    } else {
                        addMessage(
                            "I couldn't find an answer. Please try again."
                        );
                    }
                } else {
                    addMessage(
                        "I couldn't read the response. " +
                        "Please open the full AI Assistant page and try again."
                    );
                }
            } catch (error) {
                if (typingMessage) {
                    typingMessage.remove();
                }

                addMessage(
                    "Sorry, I couldn't connect right now. " +
                    "Please check your connection and try again."
                );

                console.error("SmartTrip AI chat error:", error);
            } finally {
                if (sendButton) {
                    sendButton.disabled = false;

                    if (originalButton !== undefined) {
                        sendButton.innerHTML = originalButton;
                    }
                }

                chatInput.focus();
            }
        });
    }

    // ========================================
    // 4. BACK TO TOP BUTTON
    // ========================================
    const back = document.getElementById("backTop");

    window.addEventListener("scroll", () => {
        if (back) {
            back.classList.toggle("show", window.scrollY > 500);
        }
    });

    back?.addEventListener("click", () => {
        window.scrollTo({
            top: 0,
            behavior: "smooth"
        });
    });

    // ========================================
    // 5. FORM STYLING
    // ========================================
    document.querySelectorAll("input, select, textarea").forEach(
        (element) => {
            if (
                !element.classList.contains("form-control") &&
                !element.classList.contains("form-select") &&
                element.type !== "checkbox" &&
                element.type !== "radio" &&
                element.type !== "hidden" &&
                element.type !== "submit"
            ) {
                element.classList.add("form-control");
            }
        }
    );

    // ========================================
    // 6. CHAT SUGGESTION BUTTONS
    // ========================================
    document.querySelectorAll("[data-prompt]").forEach((button) => {
        button.addEventListener("click", () => {
            const input = document.getElementById("question");

            if (input) {
                input.value = button.dataset.prompt || "";
                input.focus();
            }
        });
    });
});
