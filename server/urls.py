# from django.urls import path

# from . import views

# urlpatterns = [
#     path("", views.index, name="index"),
# ]

"""CivicSpeak admin console – URLs. Include with: path("staff/", include("civicspeak.urls"))."""
from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "admin_console"

urlpatterns = [
    path("login/", auth_views.LoginView.as_view(template_name="admin_console/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),

    path("", views.ProposalListView.as_view(), name="proposal_list"),
    path("proposals/new/", views.ProposalCreateView.as_view(), name="proposal_create"),
    path("proposals/<int:pk>/", views.ProposalUpdateView.as_view(), name="proposal_edit"),
    path("proposals/<int:pk>/updates/", views.StatusUpdateCreateView.as_view(), name="update_create"),
    path("proposals/<int:pk>/impacts/", views.ImpactCreateView.as_view(), name="impact_create"),
    path("feedback/<int:pk>/<str:field>/", views.FeedbackToggleView.as_view(), name="feedback_toggle"),

    path("community/", views.CommunityPostListView.as_view(), name="community_list"),
    path("proposals/<int:pk>/community-post/", views.CommunityPostCreateView.as_view(), name="post_create"),
    path("community/<int:pk>/edit/", views.CommunityPostUpdateView.as_view(), name="post_edit"),
    path("community/<int:pk>/delete/", views.CommunityPostDeleteView.as_view(), name="post_delete"),
]

