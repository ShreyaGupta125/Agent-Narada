// ============================================================
// AGENT NARADA — the header's user box and the dashboards' section list
//
// Shared by every page a logged-in user sees (chat, dashboards).
// It shows who is logged in, handles the Log out button and, on the
// dashboard pages, builds the list of sections on the left.
// apiRequest() comes from api.js, which the page loads before this file.
// ============================================================

const userBox = document.getElementById("user-box");
const userName = document.getElementById("user-name");
const userRole = document.getElementById("user-role");
const logoutButton = document.getElementById("logout-button");
// Exists on the dashboard pages only, not on the chat page.
const sideNav = document.getElementById("side-nav");

// The sections each dashboard role sees.
// This list only decides what is displayed. Django decides what is
// allowed: every page and every API checks the role again.
const SECTIONS = {
  SUPER_ADMIN: [
    { label: "Overview", href: "/dashboard/super-admin/" },
    { label: "User Management", href: "/users/" },
    { label: "Document Approval", href: "/documents/" },
    { label: "Upload Document", href: "/documents/upload/" },
  ],
  ADMIN: [
    { label: "Overview", href: "/dashboard/admin/" },
    { label: "Upload Documents", href: "/documents/upload/" },
    { label: "My Documents", href: "/documents/" },
  ],
};

/** Build the section list for this user's role. */
function buildSideNav(user) {
  const heading = document.createElement("p");
  heading.className = "side-heading";
  heading.textContent = user.role_label;
  sideNav.append(heading);

  for (const section of SECTIONS[user.role] || []) {
    const item = document.createElement("a");
    item.href = section.href;
    item.className = "side-link";
    item.textContent = section.label;
    // Highlight the section whose address is the page we are on.
    if (section.href === window.location.pathname) {
      item.classList.add("side-link--active");
      item.setAttribute("aria-current", "page");
    }
    sideNav.append(item);
  }

  // On a phone the list is a row that scrolls sideways. Make sure the
  // current section is not hidden off the edge.
  const active = sideNav.querySelector(".side-link--active");
  if (active) active.scrollIntoView({ block: "nearest", inline: "nearest" });
}

/**
 * Ask Django who is logged in and show it in the header.
 *
 * The name and role shown here are for display only. Django checks the
 * session and the role again on every request, so changing them in the
 * browser gives no extra access.
 *
 * @returns {Promise<object|null>} the user's details, for the page's own script
 */
async function loadCurrentUser() {
  const result = await apiRequest("GET", "/api/auth/me/");

  if (!result.ok) {
    // No valid session: this browser is not logged in.
    window.location.href = "/login/";
    return null;
  }

  const user = result.data;
  userName.textContent = user.full_name || user.username;
  userRole.textContent = user.role_label;
  userBox.hidden = false;

  if (sideNav) buildSideNav(user);
  return user;
}

/**
 * Tell Django to end the session, then go to the login page.
 */
async function handleLogout() {
  logoutButton.disabled = true;
  await apiRequest("POST", "/api/auth/logout/");
  window.location.href = "/login/";
}

logoutButton.addEventListener("click", handleLogout);

// A page's own script can wait for this to learn who is logged in:
//   const user = await currentUser;
const currentUser = loadCurrentUser();
