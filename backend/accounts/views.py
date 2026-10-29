from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.core.cache import cache
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User
from .permissions import CanManageUsers, home_page_for, permissions_for
from .serializers import UserCreateSerializer, UserUpdateSerializer


def user_payload(user):
    """The facts about a user that are safe to send to the browser.
    The password is never included."""
    return {
        "username": user.username,
        "full_name": user.get_full_name(),
        "role": user.role,
        "role_label": user.get_role_display(),
        # Lets the frontend decide which buttons to show. Hiding a button
        # is only cosmetic: the backend checks the permission again.
        "permissions": sorted(permissions_for(user)),
        # The page this role starts on. The frontend goes there after
        # login; Django also refuses every page the role may not open.
        "home": home_page_for(user),
    }


def account_row(user, viewer):
    """One account as shown on the Super Admin's user management page."""
    return {
        "id": user.pk,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "full_name": user.get_full_name(),
        "email": user.email,
        "role": user.role,
        "role_label": user.get_role_display(),
        "is_active": user.is_active,
        # True for the Super Admin's own row, which they may not delete.
        "is_self": user == viewer,
    }


# Protection against guessing passwords: after this many wrong passwords
# for one username from one computer, that username is locked there for
# LOCKOUT_SECONDS. The count is kept in Django's cache (in memory), so it
# also resets when the server restarts.
MAX_FAILED_LOGINS = 5
LOCKOUT_SECONDS = 15 * 60
LOCKED_OUT = "Too many failed attempts. Please wait 15 minutes and try again."


def failed_login_key(request, username):
    """Where the count of wrong passwords is kept: one count per username
    (in lower case) and computer (its IP address)."""
    address = request.META.get("REMOTE_ADDR", "")
    return f"failed-logins:{address}:{username.strip().lower()}"


# csrf_protect: the request must carry the CSRF token Django gave this
# browser, so another website cannot submit the login form on a user's behalf.
@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    """POST /api/auth/login/  with {"username": ..., "password": ...}"""

    # Everyone must be able to reach the login endpoint, so it is the one
    # place where the "logged-in users only" default is switched off.
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        username = str(data.get("username", ""))
        password = str(data.get("password", ""))

        # Too many wrong passwords for this username from this computer:
        # refuse to even check, so passwords cannot be guessed one after
        # another (a "brute-force" attack).
        attempts_key = failed_login_key(request, username)
        if cache.get(attempts_key, 0) >= MAX_FAILED_LOGINS:
            return Response({"detail": LOCKED_OUT}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # authenticate() hashes the given password and compares it with the
        # stored hash. It returns the user, or None if anything is wrong.
        user = authenticate(request, username=username, password=password)
        if user is None:
            # Count the failure; the count disappears after LOCKOUT_SECONDS.
            cache.set(attempts_key, cache.get(attempts_key, 0) + 1, LOCKOUT_SECONDS)
            # One message for every failure, so an attacker cannot learn
            # whether a username exists.
            return Response(
                {"detail": "Invalid username or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # login() creates the session: Django stores it in the database and
        # sends the browser a cookie holding only the session's id.
        cache.delete(attempts_key)  # a successful login starts the count again
        login(request, user)
        return Response(user_payload(user))


class LogoutView(APIView):
    """POST /api/auth/logout/"""

    def post(self, request):
        # logout() deletes the session, so the browser's cookie stops working.
        logout(request)
        return Response({"detail": "Logged out."})


class MeView(APIView):
    """GET /api/auth/me/  -> who is logged in on this browser?"""

    def get(self, request):
        return Response(user_payload(request.user))


class UserListView(APIView):
    """Super Admin only.

    GET  /api/users/  -> every account and its role
    POST /api/users/  -> create an account with any of the five roles
    """

    # Checked before get() or post() runs. Any other role receives
    # 403 Forbidden, so only the Super Admin can ever hand out a role.
    permission_classes = [CanManageUsers]

    def get(self, request):
        users = User.objects.order_by("username")
        return Response([account_row(user, request.user) for user in users])

    def post(self, request):
        serializer = UserCreateSerializer(data=request.data)
        # On bad data this stops here and replies 400 with one message per
        # field, for example {"username": ["...already exists."]}.
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(account_row(user, request.user), status=status.HTTP_201_CREATED)


class UserDetailView(APIView):
    """Super Admin only. One account, chosen by its id in the address.

    PATCH  /api/users/<id>/  -> modify the account
    DELETE /api/users/<id>/  -> delete the account
    """

    permission_classes = [CanManageUsers]

    def patch(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        # partial=True: only the fields that were sent are checked and changed.
        serializer = UserUpdateSerializer(
            user, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        if user == request.user and serializer.validated_data.get("password"):
            # Changing a password ends that user's sessions. Keep the
            # Super Admin who changed their own password logged in.
            update_session_auth_hash(request, user)

        return Response(account_row(user, request.user))

    def delete(self, request, user_id):
        user = get_object_or_404(User, pk=user_id)
        if user == request.user:
            return Response(
                {"detail": "You cannot delete your own account."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
