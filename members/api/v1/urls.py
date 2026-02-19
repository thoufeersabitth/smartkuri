from django.urls import path

from members.api.v1.views import MemberCreateAPIView, MemberDeleteAPIView, MemberDetailAPIView, MemberListAPIView, MemberUpdateAPIView


urlpatterns = [
    path("members/", MemberListAPIView.as_view()),
    path("members/create/", MemberCreateAPIView.as_view()),
    path("members/<int:pk>/", MemberDetailAPIView.as_view()),
    path("members/<int:pk>/update/", MemberUpdateAPIView.as_view()),
    path("members/<int:pk>/delete/", MemberDeleteAPIView.as_view()),
]
