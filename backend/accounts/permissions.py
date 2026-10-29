"""Role-based authorization: what each role is allowed to do.

Authentication answered "who is this user?".
This file answers "what is this user allowed to do?".

Everything is decided from the tables below, on the server, on every request.
"""

from rest_framework.permissions import BasePermission

from .models import Role


class Action:
    """The things a user can do in Agent Narada."""

    # The chatbot (students and staff only)
    CHAT = "chat"
    VIEW_OWN_CHAT_HISTORY = "view_own_chat_history"
    DELETE_OWN_CHAT_HISTORY = "delete_own_chat_history"

    # Documents
    UPLOAD_DOCUMENT = "upload_document"  # upload and manage documents
    APPROVE_DOCUMENT = "approve_document"

    # Administration
    MANAGE_USERS = "manage_users"

    # Which dashboard a role may open
    SUPER_ADMIN_DASHBOARD = "super_admin_dashboard"
    ADMIN_DASHBOARD = "admin_dashboard"


# ---------- THE PERMISSION MATRIX ----------
# One row per role. To change what a role may do, change it here only.
# A role or action that is missing from this table is refused.
#
# There are three experiences:
#   Super Admin  -> control panel, no chatbot
#   Admin        -> document management, no chatbot
#   the others   -> the chatbot, and nothing else
CHATBOT_USER = {Action.CHAT, Action.VIEW_OWN_CHAT_HISTORY, Action.DELETE_OWN_CHAT_HISTORY}

ROLE_PERMISSIONS = {
    Role.SUPER_ADMIN: {
        Action.SUPER_ADMIN_DASHBOARD,
        Action.MANAGE_USERS,
        Action.UPLOAD_DOCUMENT,
        Action.APPROVE_DOCUMENT,
    },
    Role.ADMIN: {Action.ADMIN_DASHBOARD, Action.UPLOAD_DOCUMENT},
    Role.STUDENT: CHATBOT_USER,
    Role.TEACHING_STAFF: CHATBOT_USER,
    Role.NON_TEACHING_STAFF: CHATBOT_USER,
}

# ---------- ROLE ROUTING ----------
# The page each role is taken to after login. Django decides this from
# the role stored in the database; the user never chooses it.
CHAT_PAGE = "/"
SUPER_ADMIN_DASHBOARD_PAGE = "/dashboard/super-admin/"
ADMIN_DASHBOARD_PAGE = "/dashboard/admin/"

ROLE_HOME = {
    Role.SUPER_ADMIN: SUPER_ADMIN_DASHBOARD_PAGE,
    Role.ADMIN: ADMIN_DASHBOARD_PAGE,
    Role.STUDENT: CHAT_PAGE,
    Role.TEACHING_STAFF: CHAT_PAGE,
    Role.NON_TEACHING_STAFF: CHAT_PAGE,
}


def permissions_for(user):
    """Every action this user may perform (an empty set if none)."""
    if not user.is_authenticated or not user.is_active:
        return set()
    return ROLE_PERMISSIONS.get(user.role, set())


def user_can(user, action):
    """The single question the rest of the backend asks."""
    return action in permissions_for(user)


def home_page_for(user):
    """The page this user's role starts on."""
    return ROLE_HOME.get(user.role, CHAT_PAGE)


class HasPermission(BasePermission):
    """Base class. A view lists one of the subclasses below in its
    permission_classes, and Django REST Framework calls has_permission()
    before the view runs. Returning False produces "403 Forbidden"."""

    required_action = None

    def has_permission(self, request, view):
        return user_can(request.user, self.required_action)


class CanChat(HasPermission):
    required_action = Action.CHAT


class CanViewOwnChatHistory(HasPermission):
    required_action = Action.VIEW_OWN_CHAT_HISTORY


class CanDeleteOwnChatHistory(HasPermission):
    required_action = Action.DELETE_OWN_CHAT_HISTORY


class CanUploadDocuments(HasPermission):
    required_action = Action.UPLOAD_DOCUMENT


class CanApproveDocuments(HasPermission):
    required_action = Action.APPROVE_DOCUMENT


class CanManageUsers(HasPermission):
    required_action = Action.MANAGE_USERS


class CanOpenSuperAdminDashboard(HasPermission):
    required_action = Action.SUPER_ADMIN_DASHBOARD


class CanOpenAdminDashboard(HasPermission):
    required_action = Action.ADMIN_DASHBOARD
