from django.urls import path

from . import views

# All of these sit under /api/documents/ (see config/urls.py).
urlpatterns = [
    path("", views.DocumentListView.as_view(), name="api-documents"),
    path("<int:document_id>/", views.DocumentDetailView.as_view(), name="api-document-detail"),
    path("<int:document_id>/file/", views.DocumentFileView.as_view(), name="api-document-file"),
    path("<int:document_id>/approve/", views.DocumentApproveView.as_view(), name="api-document-approve"),
    path("<int:document_id>/reject/", views.DocumentRejectView.as_view(), name="api-document-reject"),
]
