from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie

from accounts.permissions import Action, home_page_for, user_can

# These views send the HTML pages from the frontend folder to the browser.
#
# Each page belongs to certain roles. Django checks the role before sending
# the page, so a user who types another role's address is not shown it.
#
# ensure_csrf_cookie makes Django set the "csrftoken" cookie, which the
# page's JavaScript must send back with every POST request.


def send_home(request):
    """Send a user who opened a page their role may not see to their own
    start page instead."""
    home = home_page_for(request.user)
    if home == request.path:
        # Their own start page refused them too (a role with no
        # permissions). Stop here rather than redirect in a circle.
        raise PermissionDenied
    return redirect(home)


def role_page(request, action, template):
    """Send the page only if the user's role has the given permission."""
    if not user_can(request.user, action):
        return send_home(request)
    return render(request, template)


@ensure_csrf_cookie
def login_page(request):
    # Someone already logged in has no reason to see the login form.
    if request.user.is_authenticated:
        return redirect(home_page_for(request.user))
    return render(request, "login.html")


# login_required: a visitor who is not logged in is sent to LOGIN_URL
# instead of receiving the page.


@login_required
@ensure_csrf_cookie
def chat_page(request):
    """The chatbot: students, teaching staff and non-teaching staff."""
    return role_page(request, Action.CHAT, "index.html")


@login_required
@ensure_csrf_cookie
def super_admin_dashboard(request):
    return role_page(request, Action.SUPER_ADMIN_DASHBOARD, "superadmin.html")


@login_required
@ensure_csrf_cookie
def admin_dashboard(request):
    return role_page(request, Action.ADMIN_DASHBOARD, "admin.html")


@login_required
@ensure_csrf_cookie
def documents_page(request):
    """The document list: Admin (own documents) and Super Admin (all)."""
    return role_page(request, Action.UPLOAD_DOCUMENT, "documents.html")


@login_required
@ensure_csrf_cookie
def upload_page(request):
    return role_page(request, Action.UPLOAD_DOCUMENT, "upload.html")


@login_required
@ensure_csrf_cookie
def users_page(request):
    # Even if this check were missing, /api/users/ would still refuse
    # every role except the Super Admin.
    return role_page(request, Action.MANAGE_USERS, "users.html")
