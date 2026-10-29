from django.urls import path

from . import views

# All of these sit under /api/chat/ (see config/urls.py).
urlpatterns = [
    path("", views.ChatView.as_view(), name="api-chat"),
    path("conversations/", views.ConversationListView.as_view(), name="api-conversations"),
    path(
        "conversations/<int:conversation_id>/",
        views.ConversationDetailView.as_view(),
        name="api-conversation-detail",
    ),
]
