// ============================================================
// AGENT NARADA — manage users page behaviour (Super Admin only)
//
// Add, modify and delete accounts. This page only sends requests:
// Django decides whether the person using it is allowed to. Every
// other role receives 403 Forbidden from /api/users/.
// apiRequest() comes from api.js, which the page loads before this file.
// ============================================================

// ---------- 1. Find the elements we need ----------
const userForm = document.getElementById("user-form");
const formPanel = document.getElementById("form-panel");
const formTitle = document.getElementById("form-title");
const passwordLabel = document.getElementById("password-label");
const saveButton = document.getElementById("save-button");
const cancelButton = document.getElementById("cancel-button");
const formError = document.getElementById("user-form-error");
const formSuccess = document.getElementById("user-form-success");
const userRows = document.getElementById("user-rows");

const fields = {
  username: document.getElementById("new-username"),
  role: document.getElementById("new-role"),
  first_name: document.getElementById("new-first-name"),
  last_name: document.getElementById("new-last-name"),
  email: document.getElementById("new-email"),
  password: document.getElementById("new-password"),
  status: document.getElementById("new-status"),
};

// The words shown in front of an error message for each field.
const FIELD_LABELS = {
  username: "Username",
  role: "Role",
  first_name: "First name",
  last_name: "Last name",
  email: "Email",
  password: "Password",
  is_active: "Status",
};

// The account being modified, or null while the form adds a new account.
let editingUser = null;

// ---------- 2. The table of accounts ----------

/** Make one table cell. textContent keeps any HTML in the data harmless. */
function makeCell(text) {
  const cell = document.createElement("td");
  cell.textContent = text;
  return cell;
}

/** Make one small button for a table row. */
function makeRowButton(label, extraClass, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "row-button " + extraClass;
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

/** Fetch every account from Django and rebuild the table. */
async function loadUsers() {
  const result = await apiRequest("GET", "/api/users/");

  if (!result.ok) {
    // Not logged in any more, or no longer a Super Admin.
    // Django sends this user to their own start page.
    window.location.href = "/";
    return;
  }

  userRows.replaceChildren(); // remove the old rows
  for (const user of result.data) {
    const actions = document.createElement("td");
    actions.className = "row-actions";
    actions.append(makeRowButton("Modify", "", () => startEditing(user)));
    if (user.is_self) {
      // Your own account cannot be deleted. Django refuses it as well.
      actions.append(" (you)");
    } else {
      actions.append(makeRowButton("Delete", "row-button--danger", () => deleteUser(user)));
    }

    const row = document.createElement("tr");
    row.append(
      makeCell(user.username),
      makeCell(user.full_name || "-"),
      makeCell(user.role_label),
      makeCell(user.is_active ? "Active" : "Inactive"),
      actions
    );
    userRows.appendChild(row);
  }
}

// ---------- 3. Messages ----------

function showSuccess(message) {
  formError.hidden = true;
  formSuccess.textContent = message;
  formSuccess.hidden = false;
}

function showError(message) {
  formSuccess.hidden = true;
  formError.textContent = message;
  formError.hidden = false;
}

/**
 * Turn Django's error reply into readable lines.
 * Example reply: {"username": ["A user with that username already exists."]}
 */
function describeErrors(data) {
  const lines = [];
  for (const [field, messages] of Object.entries(data)) {
    const text = Array.isArray(messages) ? messages.join(" ") : String(messages);
    lines.push(FIELD_LABELS[field] ? FIELD_LABELS[field] + ": " + text : text);
  }
  return lines.join("\n") || "The request could not be completed.";
}

// ---------- 4. Add and modify (one form, two modes) ----------

/** Put the form into "modify" mode, filled with one account's details. */
function startEditing(user) {
  editingUser = user;

  fields.username.value = user.username;
  fields.role.value = user.role;
  fields.first_name.value = user.first_name;
  fields.last_name.value = user.last_name;
  fields.email.value = user.email;
  fields.password.value = "";
  fields.status.value = user.is_active ? "active" : "inactive";

  // A Super Admin may not change their own role or deactivate themselves,
  // so those two controls are locked. Django refuses it too.
  fields.role.disabled = user.is_self;
  fields.status.disabled = user.is_self;

  // The password is optional here: empty means "keep the current one".
  fields.password.required = false;
  passwordLabel.textContent = "New password (leave empty to keep)";

  formTitle.textContent = "Modify account: " + user.username;
  saveButton.textContent = "Save changes";
  cancelButton.hidden = false;
  formError.hidden = true;
  formSuccess.hidden = true;

  formPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  fields.username.focus();
}

/** Put the form back into "add" mode, empty. */
function stopEditing() {
  editingUser = null;
  userForm.reset();

  fields.role.disabled = false;
  fields.status.disabled = false;
  fields.password.required = true;
  passwordLabel.textContent = "Password";

  formTitle.textContent = "Add an account";
  saveButton.textContent = "Add account";
  cancelButton.hidden = true;
}

async function handleSave(event) {
  event.preventDefault(); // stop the browser reloading the page

  formError.hidden = true;
  formSuccess.hidden = true;
  saveButton.disabled = true;

  const data = {
    username: fields.username.value.trim(),
    role: fields.role.value,
    first_name: fields.first_name.value.trim(),
    last_name: fields.last_name.value.trim(),
    email: fields.email.value.trim(),
    password: fields.password.value,
    is_active: fields.status.value === "active",
  };

  try {
    // Adding sends POST to the list; modifying sends PATCH to one account.
    const result = editingUser
      ? await apiRequest("PATCH", "/api/users/" + editingUser.id + "/", data)
      : await apiRequest("POST", "/api/users/", data);

    if (result.ok) {
      const verb = editingUser ? "Account updated: " : "Account added: ";
      stopEditing(); // empties the form, including the password
      showSuccess(verb + result.data.username + " (" + result.data.role_label + ")");
      await loadUsers(); // show the change in the table
    } else {
      showError(describeErrors(result.data));
    }
  } catch (error) {
    showError("Cannot reach the server. Please check that it is running.");
  }

  saveButton.disabled = false;
}

// ---------- 5. Delete ----------

async function deleteUser(user) {
  // confirm() shows the browser's own OK / Cancel box.
  const confirmed = window.confirm(
    'Delete the account "' + user.username + '"?\n\nThis cannot be undone.'
  );
  if (!confirmed) return;

  try {
    const result = await apiRequest("DELETE", "/api/users/" + user.id + "/");

    if (result.ok) {
      if (editingUser && editingUser.id === user.id) stopEditing();
      showSuccess("Account deleted: " + user.username);
      await loadUsers();
    } else {
      showError(describeErrors(result.data));
    }
  } catch (error) {
    showError("Cannot reach the server. Please check that it is running.");
  }
}

// ---------- 6. Connect the behaviour to the page ----------
userForm.addEventListener("submit", handleSave);
cancelButton.addEventListener("click", stopEditing);

loadUsers();
