// ============================================================
// AGENT NARADA — document list behaviour (Admin and Super Admin)
//
// Admin:       "My Documents"      - their own uploads and each status.
// Super Admin: "Document Approval" - every upload, with Approve / Reject.
//
// Which buttons appear here is only for convenience. Django decides
// what is allowed: it sends an Admin only their own documents, and
// refuses approve / reject to everyone except the Super Admin.
// apiRequest() comes from api.js and currentUser from header.js,
// which the page loads before this file.
// ============================================================

// ---------- 1. Find the elements we need ----------
const documentsTitle = document.getElementById("documents-title");
const documentsIntro = document.getElementById("documents-intro");
const filterRow = document.getElementById("filter-row");
const uploaderHeading = document.getElementById("uploader-heading");
const tableScroll = document.getElementById("table-scroll");
const documentRows = document.getElementById("document-rows");
const emptyNote = document.getElementById("empty-note");
const documentsError = document.getElementById("documents-error");
const documentsSuccess = document.getElementById("documents-success");

let canApprove = false; // true for the Super Admin
let currentStatus = ""; // which filter is chosen ("" means all)

// ---------- 2. Small helpers ----------

function showDocumentsSuccess(message) {
  documentsError.hidden = true;
  documentsSuccess.textContent = message;
  documentsSuccess.hidden = false;
}

function showDocumentsError(message) {
  documentsSuccess.hidden = true;
  documentsError.textContent = message;
  documentsError.hidden = false;
}

/** Turn Django's error reply into one readable message. */
function describeError(data) {
  const parts = [];
  for (const messages of Object.values(data)) {
    parts.push(Array.isArray(messages) ? messages.join(" ") : String(messages));
  }
  return parts.join(" ") || "The request could not be completed.";
}

/** "2026-10-02T16:30:00+05:30" becomes "2 Oct 2026, 4:30 pm". */
function formatDate(isoText) {
  return new Date(isoText).toLocaleString("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/** Make an element with a class and text. textContent keeps data harmless. */
function make(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function makeRowButton(label, extraClass, onClick) {
  const button = make("button", "row-button " + extraClass, label);
  button.type = "button";
  button.addEventListener("click", onClick);
  return button;
}

// ---------- 3. The table ----------

function buildRow(doc) {
  const row = document.createElement("tr");

  // Document: title, then the description and file name in small text.
  const titleCell = make("td", "cell-wrap cell-main");
  titleCell.append(make("span", "cell-title", doc.title));
  if (doc.description) titleCell.append(make("span", "cell-note", doc.description));
  titleCell.append(make("span", "cell-note", doc.filename));
  // Whether the file's text was read, which is what answers come from.
  titleCell.append(
    doc.processed
      ? make(
          "span",
          "cell-note",
          "Text read: " + doc.passage_count + (doc.passage_count === 1 ? " passage" : " passages")
        )
      : make(
          "span",
          "cell-note cell-note--warning",
          "Text not read: not used for answers. Delete it and upload it again."
        )
  );
  row.append(titleCell);

  if (canApprove) row.append(make("td", "", doc.uploaded_by || "(deleted account)"));

  row.append(make("td", "", formatDate(doc.uploaded_at)));
  const accessCell = make("td", "cell-wrap", doc.access.join(", ") || "Nobody");
  row.append(accessCell);

  // Status: a badge, then who reviewed it and why it was rejected.
  const statusCell = make("td", "cell-wrap");
  statusCell.append(make("span", "badge badge--" + doc.status.toLowerCase(), doc.status_label));
  if (doc.reviewed_by) {
    statusCell.append(
      make("span", "cell-note", "by " + doc.reviewed_by + ", " + formatDate(doc.reviewed_at))
    );
  }
  if (doc.rejection_reason) {
    statusCell.append(make("span", "cell-note", "Reason: " + doc.rejection_reason));
  }
  row.append(statusCell);

  // Actions.
  const actions = make("td", "row-actions");

  // A plain link: the browser sends the session cookie, and Django
  // checks the role and ownership before it sends the file.
  const download = make("a", "row-button", "Download");
  download.href = doc.file_url;
  actions.append(download);

  // A document whose text was not read cannot be approved (Django refuses it too).
  if (canApprove && doc.status !== "APPROVED" && doc.processed) {
    actions.append(makeRowButton("Approve", "row-button--good", () => approveDocument(doc)));
  }
  if (canApprove && doc.status !== "REJECTED") {
    actions.append(makeRowButton("Reject", "row-button--danger", () => rejectDocument(doc)));
  }
  if (doc.can_change_access) {
    actions.append(makeRowButton("Change readers", "", () => editAccess(doc, accessCell)));
  }
  if (doc.can_delete) {
    actions.append(makeRowButton("Delete", "row-button--danger", () => deleteDocument(doc)));
  }
  row.append(actions);

  return row;
}

/** Fetch the documents for the chosen filter and rebuild the table. */
async function loadDocuments() {
  const query = currentStatus ? "?status=" + currentStatus : "";
  const result = await apiRequest("GET", "/api/documents/" + query);

  if (!result.ok) {
    // Not logged in any more, or the role has changed.
    // Django sends this user to their own start page.
    window.location.href = "/";
    return;
  }

  documentRows.replaceChildren(); // remove the old rows
  for (const doc of result.data) {
    documentRows.append(buildRow(doc));
  }
  // With nothing to list, show a short note instead of an empty table.
  const hasDocuments = result.data.length > 0;
  tableScroll.hidden = !hasDocuments;
  emptyNote.hidden = hasDocuments;
}

function chooseFilter(status) {
  currentStatus = status;
  for (const button of filterRow.querySelectorAll(".filter-button")) {
    const chosen = button.dataset.status === status;
    button.classList.toggle("filter-button--active", chosen);
    button.setAttribute("aria-pressed", chosen);
  }
  loadDocuments();
}

// ---------- 4. Approve, reject, delete ----------

/** Send one action to Django, then show the result and refresh the table. */
async function sendAction(method, url, body, successMessage) {
  try {
    const result = await apiRequest(method, url, body);
    if (result.ok) {
      showDocumentsSuccess(successMessage);
      await loadDocuments();
    } else {
      showDocumentsError(describeError(result.data));
    }
  } catch (error) {
    showDocumentsError("Cannot reach the server. Please check that it is running.");
  }
}

function approveDocument(doc) {
  const confirmed = window.confirm(
    'Approve "' + doc.title + '"?\n\nIt will become part of Agent Narada\'s knowledge for: ' +
      (doc.access.join(", ") || "nobody") + "."
  );
  if (!confirmed) return;
  sendAction("POST", "/api/documents/" + doc.id + "/approve/", {}, 'Approved "' + doc.title + '".');
}

function rejectDocument(doc) {
  // prompt() shows the browser's own box with a text field.
  // It gives null when Cancel is pressed.
  const reason = window.prompt('Why is "' + doc.title + '" being rejected?\n\nThe uploader will see this reason.');
  if (reason === null) return;
  sendAction(
    "POST",
    "/api/documents/" + doc.id + "/reject/",
    { reason: reason },
    'Rejected "' + doc.title + '".'
  );
}

function deleteDocument(doc) {
  const confirmed = window.confirm(
    'Delete "' + doc.title + '" and its file?\n\nThis cannot be undone.'
  );
  if (!confirmed) return;
  sendAction("DELETE", "/api/documents/" + doc.id + "/", undefined, 'Deleted "' + doc.title + '".');
}

// ---------- 5. Change who may read a document ----------

// The three groups, as Django names them and as the page shows them.
const ACCESS_GROUPS = [
  ["for_students", "Students"],
  ["for_teaching_staff", "Teaching staff"],
  ["for_non_teaching_staff", "Non-teaching staff"],
];

/** Swap the "Who may read" text for three tickboxes with Save and Cancel. */
function editAccess(doc, accessCell) {
  if (accessCell.querySelector("input")) return; // already open

  const boxes = {};
  const editor = make("div", "access-editor");
  for (const [field, label] of ACCESS_GROUPS) {
    const check = make("label", "check");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = doc.access.includes(label);
    boxes[field] = box;
    check.append(box, " " + label);
    editor.append(check);
  }

  const buttons = make("div", "access-editor-buttons");
  buttons.append(
    makeRowButton("Save", "row-button--good", () => saveAccess(doc, boxes)),
    makeRowButton("Cancel", "", () => loadDocuments())
  );
  editor.append(buttons);
  accessCell.replaceChildren(editor);
}

function saveAccess(doc, boxes) {
  const body = {};
  const chosen = [];
  for (const [field, label] of ACCESS_GROUPS) {
    body[field] = boxes[field].checked;
    if (boxes[field].checked) chosen.push(label);
  }
  if (chosen.length === 0) {
    showDocumentsError("Choose at least one group that may read this document.");
    return;
  }
  const confirmed = window.confirm(
    'Change who may get answers from "' + doc.title + '"?\n\nNow: ' +
      (doc.access.join(", ") || "nobody") + "\nNew: " + chosen.join(", ") +
      "\n\nThe change is used from the next question."
  );
  if (!confirmed) return;
  sendAction(
    "PATCH",
    "/api/documents/" + doc.id + "/",
    body,
    '"' + doc.title + '" can now be read by: ' + chosen.join(", ") + "."
  );
}

// ---------- 6. Start ----------

async function start() {
  const user = await currentUser;
  if (!user) return;

  canApprove = user.permissions.includes("approve_document");

  if (canApprove) {
    documentsTitle.textContent = "Document Approval";
    documentsIntro.textContent =
      "Review uploads. Only approved documents are used to answer questions.";
    uploaderHeading.hidden = false;
  } else {
    documentsTitle.textContent = "My Documents";
    documentsIntro.textContent =
      "Your uploads and their approval status. Only the Super Admin can approve them.";
  }

  for (const button of filterRow.querySelectorAll(".filter-button")) {
    button.addEventListener("click", () => chooseFilter(button.dataset.status));
  }

  // The Super Admin starts on what needs their attention; an Admin on everything.
  chooseFilter(canApprove ? "PENDING" : "");
}

start();
