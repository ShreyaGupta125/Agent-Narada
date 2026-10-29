// ============================================================
// AGENT NARADA — upload page behaviour (Admin and Super Admin)
//
// This page only collects the form and sends it. Django checks the
// role, checks the file, stores it, and decides the status:
// PENDING for an Admin, APPROVED for a Super Admin.
// apiRequest() comes from api.js and currentUser from header.js,
// which the page loads before this file.
// ============================================================

const uploadForm = document.getElementById("upload-form");
const uploadButton = document.getElementById("upload-button");
const uploadIntro = document.getElementById("upload-intro");
const uploadError = document.getElementById("upload-error");
const uploadSuccess = document.getElementById("upload-success");

const titleInput = document.getElementById("doc-title");
const descriptionInput = document.getElementById("doc-description");
const fileInput = document.getElementById("doc-file");
const forStudents = document.getElementById("for-students");
const forTeachingStaff = document.getElementById("for-teaching-staff");
const forNonTeachingStaff = document.getElementById("for-non-teaching-staff");

// The words shown in front of an error message for each field.
const UPLOAD_LABELS = {
  title: "Title",
  description: "Description",
  file: "File",
  access: "Access",
};

/** Turn Django's error reply into readable lines. */
function describeUploadErrors(data) {
  const lines = [];
  for (const [field, messages] of Object.entries(data)) {
    const text = Array.isArray(messages) ? messages.join(" ") : String(messages);
    lines.push(UPLOAD_LABELS[field] ? UPLOAD_LABELS[field] + ": " + text : text);
  }
  return lines.join("\n") || "The document could not be uploaded.";
}

/** Tell the user what will happen to their upload. */
async function showIntro() {
  const user = await currentUser;
  if (!user) return;
  uploadIntro.textContent = user.permissions.includes("approve_document")
    ? "As Super Admin, your upload is approved immediately and becomes part of Agent Narada's knowledge."
    : "Your upload will wait as Pending until the Super Admin approves it.";
}

/**
 * Ask before uploading, naming the groups that will and will NOT get
 * answers from the document, so a missing tick is noticed now and not
 * later in the chat. Returns false if the user wants to go back.
 */
function confirmReaders() {
  const groups = [
    [forStudents, "Students"],
    [forTeachingStaff, "Teaching staff"],
    [forNonTeachingStaff, "Non-teaching staff"],
  ];
  const yes = groups.filter(([box]) => box.checked).map(([, label]) => label);
  const no = groups.filter(([box]) => !box.checked).map(([, label]) => label);
  if (yes.length === 0) return true; // Django explains that one group is needed

  return window.confirm(
    'Upload "' + titleInput.value.trim() + '"?\n\n' +
      "Will get answers from it: " + yes.join(", ") + "\n" +
      (no.length ? "Will NOT get answers from it: " + no.join(", ") + "\n" : "") +
      "\nThis can be changed later on the documents page (Change readers)."
  );
}

async function handleUpload(event) {
  event.preventDefault(); // stop the browser reloading the page

  uploadError.hidden = true;
  uploadSuccess.hidden = true;
  if (!confirmReaders()) return;
  uploadButton.disabled = true;
  uploadButton.textContent = "Uploading...";

  // FormData is how a browser sends a file together with other fields.
  const form = new FormData();
  form.append("title", titleInput.value.trim());
  form.append("description", descriptionInput.value.trim());
  form.append("file", fileInput.files[0]);
  form.append("for_students", forStudents.checked);
  form.append("for_teaching_staff", forTeachingStaff.checked);
  form.append("for_non_teaching_staff", forNonTeachingStaff.checked);

  try {
    const result = await apiRequest("POST", "/api/documents/", form);

    if (result.ok) {
      // Django answers 201 only after the text was read and stored, so a
      // successful upload is always ready to be searched (once approved).
      uploadSuccess.textContent =
        'Uploaded "' + result.data.title + '". Status: ' + result.data.status_label + ".\n" +
        "Text read and stored: " + result.data.passage_count +
        (result.data.passage_count === 1 ? " passage." : " passages.");
      uploadSuccess.hidden = false;
      uploadForm.reset();
    } else {
      uploadError.textContent = describeUploadErrors(result.data);
      uploadError.hidden = false;
    }
  } catch (error) {
    uploadError.textContent = "Cannot reach the server. Please check that it is running.";
    uploadError.hidden = false;
  }

  uploadButton.disabled = false;
  uploadButton.textContent = "Upload document";
}

uploadForm.addEventListener("submit", handleUpload);

showIntro();
