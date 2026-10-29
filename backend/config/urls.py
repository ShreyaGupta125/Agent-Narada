"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import include, path

from accounts.views import UserDetailView, UserListView
from dashboard.views import AdminDashboardView, SuperAdminDashboardView

from . import views

urlpatterns = [
    path("admin/", admin.site.urls),
    # JSON endpoints called by the frontend's JavaScript
    path("api/auth/", include("accounts.urls")),
    path("api/users/", UserListView.as_view(), name="api-users"),
    path("api/users/<int:user_id>/", UserDetailView.as_view(), name="api-user-detail"),
    path("api/documents/", include("documents.urls")),
    path("api/chat/", include("chat.urls")),
    path("api/dashboard/super-admin/", SuperAdminDashboardView.as_view(), name="api-super-admin-dashboard"),
    path("api/dashboard/admin/", AdminDashboardView.as_view(), name="api-admin-dashboard"),
    # HTML pages. Each one is sent only to the roles allowed to see it.
    path("login/", views.login_page, name="login-page"),
    path("dashboard/super-admin/", views.super_admin_dashboard, name="super-admin-dashboard"),
    path("dashboard/admin/", views.admin_dashboard, name="admin-dashboard"),
    path("users/", views.users_page, name="users-page"),
    path("documents/", views.documents_page, name="documents-page"),
    path("documents/upload/", views.upload_page, name="upload-page"),
    path("", views.chat_page, name="chat-page"),
]
