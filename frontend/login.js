// ============================================================
// AGENT NARADA — login page behaviour
//
// This file only collects the username and password and sends them
// to Django. Django alone decides whether they are correct.
// ============================================================

const loginForm = document.getElementById("login-form");
const usernameInput = document.getElementById("username");
const passwordInput = document.getElementById("password");
const loginButton = document.getElementById("login-button");
const loginError = document.getElementById("login-error");

function showError(message) {
  loginError.textContent = message;
  loginError.hidden = false;
}

async function handleLogin(event) {
  event.preventDefault(); // stop the browser reloading the page

  loginError.hidden = true;
  // Disable the button while waiting, so one click cannot send two requests.
  loginButton.disabled = true;
  loginButton.textContent = "Logging in...";

  try {
    const result = await apiRequest("POST", "/api/auth/login/", {
      username: usernameInput.value.trim(),
      password: passwordInput.value,
    });

    if (result.ok) {
      // Django has set the session cookie and told us which page this
      // user's role starts on: a dashboard or the chatbot. Django refuses
      // the other pages anyway, so this is only the right first stop.
      window.location.href = result.data.home || "/";
      return;
    }

    showError(result.data.detail || "Login failed. Please try again.");
  } catch (error) {
    // fetch() itself failed: the server is not running or unreachable.
    showError("Cannot reach the server. Please check that it is running.");
  }

  passwordInput.value = "";
  loginButton.disabled = false;
  loginButton.textContent = "Log in";
}

loginForm.addEventListener("submit", handleLogin);
