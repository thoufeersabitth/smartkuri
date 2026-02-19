from django.urls import path
from . import views

app_name = "core"  # Ithu important!

urlpatterns = [
    path('', views.home, name='home'),  # home view
]
