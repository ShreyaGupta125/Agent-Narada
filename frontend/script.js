// ============================================================
// AGENT NARADA — chat page behaviour
//
// This page only shows the conversation. Every question goes to the
// Django backend, which checks the login and the role before it
// produces an answer. The "Recent chats" panel lists the user's own
// conversations from the last 7 days; Django sends nobody else's. Each
// can be deleted, or all of them at once, after a confirmation.
// ============================================================

// ---------- 1. Find the elements we need ----------
// document.getElementById() looks up one element by its id attribute.
// We do this once here instead of searching the page on every keystroke.
const chatForm = document.getElementById("chat-form");
const userInput = document.getElementById("user-input");
const sendButton = document.getElementById("send-button");
const messagesBox = document.getElementById("messages");
const welcome = document.getElementById("welcome");
const chatArea = document.querySelector(".chat");
const historyList = document.getElementById("history-list");
const historyEmpty = document.getElementById("history-empty");
const newChatButton = document.getElementById("new-chat-button");
const clearHistoryButton = document.getElementById("clear-history-button");

// The conversation on screen. null for a new chat: Django creates the
// conversation when the first answer arrives and tells us its id.
let conversationId = null;

// true while an answer is on its way. Switching chats is paused then,
// so the answer cannot land in the wrong conversation.
let waiting = false;

// ---------- 2. Showing messages ----------

/**
 * Build one message bubble and put it into the conversation.
 *
 * @param {string} sender - "user" or "assistant"
 * @param {string} text   - the words to show
 * @returns {HTMLElement} the bubble, so its text can be changed later
 */
function addMessage(sender, text) {
  // createElement makes a new element in memory. It is not on the page
  // until we append it further down.
  const bubble = document.createElement("div");
  bubble.className = "message message--" + sender;

  const label = document.createElement("span");
  label.className = "message-sender";
  label.textContent = sender === "user" ? "You" : "Agent Narada";

  const body = document.createElement("span");
  body.className = "message-text";
  // textContent, never innerHTML: the browser treats this strictly as
  // text, so a question or an answer containing HTML can never run as code.
  body.textContent = text;

  bubble.append(label, body);
  messagesBox.appendChild(bubble); // now it appears on the page

  scrollToNewest();
  return bubble;
}

/** Keep the newest message in view. */
function scrollToNewest() {
  chatArea.scrollTop = chatArea.scrollHeight;
}

/**
 * Add the "Sources" line under an answer: the documents it came from,
 * with the section and page of each part used, for example
 *   Sources: Attendance Notice (3. Condonation); Exam Date Sheet (page 2)
 * A document used several times is named once, with all its references.
 */
function addSources(bubble, sources) {
  if (!sources || sources.length === 0) return;

  const referencesByTitle = new Map();
  for (const source of sources) {
    if (!referencesByTitle.has(source.title)) referencesByTitle.set(source.title, []);
    const parts = [];
    if (source.section) parts.push(source.section);
    if (source.page) parts.push("page " + source.page);
    const reference = parts.join(", ");
    const references = referencesByTitle.get(source.title);
    if (reference && !references.includes(reference)) references.push(reference);
  }

  const names = [];
  for (const [title, references] of referencesByTitle) {
    names.push(references.length > 0 ? title + " (" + references.join("; ") + ")" : title);
  }

  const line = document.createElement("span");
  line.className = "message-sources";
  line.textContent = "Sources: " + names.join("; ");
  bubble.appendChild(line);
}

/** Empty the conversation area and show the welcome hero again. */
function clearConversation() {
  messagesBox.replaceChildren();
  welcome.hidden = false;
}

/**
 * Lock or unlock the page while a question is being answered, so a
 * second question cannot be sent, and no other chat opened, before
 * the first reply arrives.
 */
function setWaiting(isWaiting) {
  waiting = isWaiting;
  userInput.disabled = isWaiting;
  sendButton.disabled = isWaiting;
  newChatButton.disabled = isWaiting;
  clearHistoryButton.disabled = isWaiting;
  for (const button of historyList.querySelectorAll("button")) button.disabled = isWaiting;
}

// ---------- 3. Asking the backend ----------
// apiRequest() comes from api.js, which the page loads before this file.

/**
 * Send the question to Django and return its reply:
 *   { answer: "...", sources: [{ title: "...", page: 3 }, ...],
 *     conversation_id: 12 }
 *
 * The backend — not this file — handles authentication, role
 * permissions, document retrieval, the language model and saving the
 * conversation.
 */
async function getReply(question) {
  const body = { question: question };
  if (conversationId !== null) body.conversation_id = conversationId;

  const result = await apiRequest("POST", "/api/chat/", body);

  if (result.status === 404) {
    // The conversation has expired (older than 7 days). The next
    // question starts a new one.
    conversationId = null;
    loadHistory();
  }

  if (result.status === 403) {
    // The session has ended (for example the user logged out in
    // another tab). Only the login page can fix that.
    window.location.href = "/login/";
    throw new Error("Your session has ended. Please log in again.");
  }

  if (!result.ok) {
    throw new Error(result.data.detail || "Something went wrong. Please try again.");
  }

  return result.data;
}

/**
 * Runs when the form is submitted, by the Send button or the Enter key.
 * Because the input and button sit inside a <form>, the browser gives us
 * Enter-key support for free — no key detection code needed.
 */
async function handleSubmit(event) {
  // Stop the browser reloading the page, which is a form's default action.
  event.preventDefault();

  // .trim() removes spaces at both ends, so " " does not count as a question.
  const question = userInput.value.trim();
  if (question === "") return;

  // First question: replace the hero with the conversation.
  welcome.hidden = true;

  addMessage("user", question);
  userInput.value = ""; // clear the box ready for the next question

  // Show a temporary bubble straight away. A real answer can take
  // several seconds, and an empty screen would look broken.
  const bubble = addMessage("assistant", "Thinking...");
  const bubbleText = bubble.querySelector(".message-text");
  bubble.classList.add("message--pending");
  setWaiting(true);

  try {
    const reply = await getReply(question);
    conversationId = reply.conversation_id;
    bubbleText.textContent = reply.answer;
    addSources(bubble, reply.sources);
  } catch (error) {
    // Either Django refused the question, or the server cannot be reached.
    bubbleText.textContent =
      error instanceof TypeError
        ? "Cannot reach the server. Please check that it is running."
        : error.message;
    bubble.classList.add("message--error");
  }

  bubble.classList.remove("message--pending");
  setWaiting(false);
  scrollToNewest();
  userInput.focus(); // put the cursor back so the user can keep typing

  // A new chat now appears in the list, and the one just used moves to the top.
  loadHistory();
}

// ---------- 4. Recent chats ----------

/** Highlight the conversation on screen in the list. */
function markActive() {
  for (const row of historyList.children) {
    const active = Number(row.dataset.id) === conversationId;
    row.classList.toggle("history-row--active", active);
    const item = row.querySelector(".history-item");
    if (active) item.setAttribute("aria-current", "true");
    else item.removeAttribute("aria-current");
  }
}

/**
 * Build one row of the list: the conversation's title (click to open it)
 * and a small delete button.
 */
function makeHistoryRow(conversation) {
  const row = document.createElement("div");
  row.className = "history-row";
  row.dataset.id = conversation.id;

  const item = document.createElement("button");
  item.type = "button";
  item.className = "history-item";
  item.textContent = conversation.title; // textContent: shown as plain text
  item.title = conversation.title; // the full title when the mouse rests on it
  item.disabled = waiting;
  item.addEventListener("click", () => openConversation(conversation.id));

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "history-delete";
  remove.textContent = "×";
  // What a screen reader says, and the tooltip: which chat it deletes.
  remove.setAttribute("aria-label", "Delete conversation: " + conversation.title);
  remove.title = "Delete this conversation";
  remove.disabled = waiting;
  remove.addEventListener("click", () => deleteConversation(conversation));

  row.append(item, remove);
  return row;
}

/** Fetch this user's conversations from Django and rebuild the list. */
async function loadHistory() {
  let result;
  try {
    result = await apiRequest("GET", "/api/chat/conversations/");
  } catch (error) {
    return; // server unreachable: keep the list as it is
  }
  if (!result.ok) return; // not logged in: header.js sends the user to /login/

  historyList.replaceChildren(); // remove the old rows
  for (const conversation of result.data) {
    historyList.appendChild(makeHistoryRow(conversation));
  }
  const hasHistory = result.data.length > 0;
  historyEmpty.hidden = hasHistory;
  clearHistoryButton.hidden = !hasHistory;
  markActive();
}

/** Show one of the user's earlier conversations, ready to continue. */
async function openConversation(id) {
  if (waiting) return;

  let result;
  try {
    result = await apiRequest("GET", "/api/chat/conversations/" + id + "/");
  } catch (error) {
    return;
  }
  if (!result.ok) {
    // It expired (or never was this user's). Refresh the list so it disappears.
    loadHistory();
    return;
  }

  conversationId = id;
  clearConversation();
  welcome.hidden = true;
  for (const message of result.data.messages) {
    const bubble = addMessage(message.sender, message.text);
    if (message.sender === "assistant") addSources(bubble, message.sources);
  }
  markActive();
  userInput.focus();
}

/** Start a fresh conversation. Django creates it with the first answer. */
function startNewChat() {
  if (waiting) return;
  conversationId = null;
  clearConversation();
  markActive();
  userInput.focus();
}

// ---------- 5. Deleting chats ----------
// confirm() shows the browser's own OK / Cancel box. Nothing is deleted
// unless OK is pressed. Django checks again that the chats are this
// user's own; anyone else's gives "not found".

/** Delete one conversation, after a confirmation. */
async function deleteConversation(conversation) {
  if (waiting) return;
  const confirmed = window.confirm(
    'Delete the conversation "' + conversation.title + '"?\n\nIt will be removed permanently.'
  );
  if (!confirmed) return;

  try {
    const result = await apiRequest("DELETE", "/api/chat/conversations/" + conversation.id + "/");
    // 404: it was already gone (for example deleted in another tab).
    if (!result.ok && result.status !== 404) {
      window.alert(result.data.detail || "The conversation could not be deleted. Please try again.");
      return;
    }
  } catch (error) {
    window.alert("Cannot reach the server. Please check that it is running.");
    return;
  }

  // If the deleted chat was on screen, start a new one.
  if (conversation.id === conversationId) startNewChat();
  loadHistory();
}

/** Delete every conversation of this user, after a confirmation. */
async function clearHistory() {
  if (waiting) return;
  const confirmed = window.confirm(
    "Delete ALL your conversations?\n\nThey will be removed permanently. This cannot be undone."
  );
  if (!confirmed) return;

  try {
    // Django also refuses to clear everything unless the request says so.
    const result = await apiRequest("DELETE", "/api/chat/conversations/", { confirm: true });
    if (!result.ok) {
      window.alert(result.data.detail || "Your history could not be cleared. Please try again.");
      return;
    }
  } catch (error) {
    window.alert("Cannot reach the server. Please check that it is running.");
    return;
  }

  startNewChat();
  loadHistory();
}

// ---------- 6. Connect the behaviour to the page ----------
// addEventListener means: "when this event happens on this element,
// run this function".
// (The header's user box and Log out button are handled by header.js.)
chatForm.addEventListener("submit", handleSubmit);
newChatButton.addEventListener("click", startNewChat);
clearHistoryButton.addEventListener("click", clearHistory);

loadHistory();
