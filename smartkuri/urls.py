from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

# --- Swagger imports ---
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

# --- Swagger schema view ---
schema_view = get_schema_view(
    openapi.Info(
        title="SmartKuri API",
        default_version='v1',
        description="API documentation for SmartKuri",
        terms_of_service="https://www.yourproject.com/terms/",
        contact=openapi.Contact(email="support@yourproject.com"),
        license=openapi.License(name="MIT License"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),
)

urlpatterns = [

    # ===============================
    # Django Admin
    # ===============================
    path('admin/', admin.site.urls),

    # ===============================
    # Core / Home
    # ===============================
    path('', include('core.urls')),

    # ===============================
    # WEB APPS
    # ===============================
    path('accounts/', include('accounts.urls', namespace='accounts')),
    path('adminpanel/', include('adminpanel.urls')),
    path('members/', include('members.urls')),
    path('chitti/', include('chitti.urls')),
    path('payments/', include('payments.urls')),
    path('collectors/', include('collectors.urls', namespace='collectors')),

    # Optional redirect
    path(
        'accounts/admin-dashboard/',
        RedirectView.as_view(url='/adminpanel/dashboard/')
    ),

    # ===============================
    # REST API v1
    # ===============================
    path('api/v1/', include('accounts.api.v1.urls')),
    path('api/v1/', include('chitti.api.v1.urls')),
    path('api/v1/', include('members.api.v1.urls')),
    path('api/v1/', include('payments.api.v1.urls')),
    path('api/v1/', include('collectors.api.v1.urls')),

    # ===============================
    # Swagger / API Docs
    # ===============================
    path(
        'api/v1/swagger/',
        schema_view.with_ui('swagger', cache_timeout=0),
        name='schema-swagger-ui'
    ),
    path(
        'api/v1/redoc/',
        schema_view.with_ui('redoc', cache_timeout=0),
        name='schema-redoc'
    ),
    path(
        'api/v1/swagger.json',
        schema_view.without_ui(cache_timeout=0),
        name='schema-json'
    ),
]

# ===============================
# Static & Media (DEV only)
# ===============================
if settings.DEBUG:
    urlpatterns += static(
        settings.STATIC_URL,
        document_root=settings.STATIC_ROOT
    )
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT
    )
