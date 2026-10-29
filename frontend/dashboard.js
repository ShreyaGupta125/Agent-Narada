// ============================================================
// AGENT NARADA — dashboard numbers
//
// Shared by the Super Admin dashboard and the Admin dashboard.
// Each page says where its numbers come from (data-stats-url) and
// marks where each one goes (data-stat). This file fetches them from
// Django and fills them in. Django sends each dashboard's numbers to
// its own role only.
// apiRequest() comes from api.js, which the page loads before this file.
// ============================================================

const dashboard = document.getElementById("dashboard");
const statsError = document.getElementById("stats-error");

/**
 * Follow a dotted path into the reply.
 * readPath({users: {total: 12}}, "users.total") gives 12.
 */
function readPath(data, path) {
  let value = data;
  for (const key of path.split(".")) {
    if (value === undefined || value === null) return undefined;
    value = value[key];
  }
  return value;
}

async function loadStats() {
  let result;
  try {
    result = await apiRequest("GET", dashboard.dataset.statsUrl);
  } catch (error) {
    statsError.textContent = "Cannot reach the server. Please check that it is running.";
    statsError.hidden = false;
    return;
  }

  if (!result.ok) {
    // Not logged in any more, or the role has changed.
    // Django sends this user to their own start page.
    window.location.href = "/";
    return;
  }

  for (const element of document.querySelectorAll("[data-stat]")) {
    const value = readPath(result.data, element.dataset.stat);
    element.textContent = value === undefined ? "-" : value;
  }
}

loadStats();
