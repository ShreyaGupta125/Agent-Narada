// ============================================================
// AGENT NARADA — talking to the Django backend
//
// Shared by the login page and the chat page. Every request to
// the backend goes through apiRequest() below.
// ============================================================

/**
 * Read one cookie by name.
 * Django stores its CSRF token in a cookie called "csrftoken".
 */
function getCookie(name) {
  const cookies = document.cookie.split(";");
  for (const cookie of cookies) {
    const [key, value] = cookie.trim().split("=");
    if (key === name) return decodeURIComponent(value);
  }
  return "";
}

/**
 * Send a request to the Django backend and return its JSON reply.
 *
 * @param {string} method - "GET" or "POST"
 * @param {string} url    - for example "/api/auth/login/"
 * @param {object|FormData} [body] - data to send (not for GET). A plain
 *                          object is sent as JSON; a FormData (used for
 *                          file uploads) is sent as a form.
 * @returns {Promise<{ok: boolean, status: number, data: object}>}
 */
async function apiRequest(method, url, body) {
  const options = { method: method, headers: {} };

  if (method !== "GET") {
    // Django rejects any POST that does not carry this token. A page on
    // another website cannot read our cookie, so it cannot forge a request.
    options.headers["X-CSRFToken"] = getCookie("csrftoken");

    if (body instanceof FormData) {
      // A form that contains a file. The browser sets the right
      // Content-Type for it by itself.
      options.body = body;
    } else {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body || {});
    }
  }

  // The browser attaches the session cookie by itself. JavaScript never
  // sees or stores it.
  const response = await fetch(url, options);

  let data = {};
  try {
    data = await response.json();
  } catch (error) {
    // The reply was not JSON (for example an error page). Leave data empty.
  }

  return { ok: response.ok, status: response.status, data: data };
}
