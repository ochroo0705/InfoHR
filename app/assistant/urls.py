from django.urls import path

from assistant import saved_views, views, ws_views

app_name = "assistant"

urlpatterns = [
    path("ask/", views.ask, name="ask"),
    path("pick/", views.pick, name="pick"),
    path("verify/", views.sql_verify, name="sql_verify"),
    path("workspace/", ws_views.workspace, name="workspace"),
    path("workspace/new/", ws_views.ws_new, name="ws_new"),
    path("workspace/open/<int:question_id>/", ws_views.ws_open, name="ws_open"),
    path("workspace/<int:pk>/", ws_views.workspace, name="workspace_tab"),
    path("workspace/<int:pk>/rename/", ws_views.ws_rename, name="ws_rename"),
    path("workspace/<int:pk>/close/", ws_views.ws_close, name="ws_close"),
    path("workspace/<int:pk>/table/", ws_views.ws_table, name="ws_table"),
    path("workspace/<int:pk>/chat/", ws_views.ws_chat, name="ws_chat"),
    path("workspace/<int:pk>/ask/", ws_views.ws_ask, name="ws_ask"),
    path("workspace/<int:pk>/undo/", ws_views.ws_undo, name="ws_undo"),
    path("workspace/<int:pk>/excel/", ws_views.ws_excel, name="ws_excel"),
    path("workspace/<int:pk>/print/", ws_views.ws_print, name="ws_print"),
    path("workspace/<int:pk>/copy/", ws_views.ws_copy, name="ws_copy"),
    path("workspace/<int:pk>/save/", ws_views.ws_save_table, name="ws_save_table"),
    path("saved/", saved_views.saved_list, name="saved_list"),
    path("saved/<int:pk>/", saved_views.saved_page, name="saved_page"),
    path("saved/<int:pk>/table/", saved_views.saved_table, name="saved_table"),
    path("saved/<int:pk>/excel/", saved_views.saved_excel, name="saved_excel"),
    path("saved/<int:pk>/print/", saved_views.saved_print, name="saved_print"),
    path("saved/<int:pk>/copy/", saved_views.saved_copy, name="saved_copy"),
    path("saved/<int:pk>/delete/", saved_views.saved_delete, name="saved_delete"),
]
