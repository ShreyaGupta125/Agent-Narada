from django.urls import path

from . import views

# All of these sit under /api/auth/ (see config/urls.py).
urlpatterns = [
    path("login/", views.LoginView.as_view(), name="api-login"),
    path("logout/", views.LogoutView.as_view(), name="api-logout"),
    path("me/", views.MeView.as_view(), name="api-me"),
]
