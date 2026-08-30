"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
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
from django.http import JsonResponse
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

from apps.broadcasts.views import BroadcastImagePresignView
from apps.evidence.views import EvidencePresignView
from apps.tasks.views import VoicePresignView
from apps.users.views import ProfilePicturePresignView


def healthz(_request):
    """Liveness probe for the load balancer -- no auth, no DB, no cache.

    The ALB target group health-checks this path (docs/ops/aws-deploy-from-scratch.md
    §14); it must stay a plain Django view so it never touches Postgres/Redis and
    isn't gated by DRF authentication.
    """
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path('healthz', healthz, name='healthz'),
    path('admin/', admin.site.urls),
    # OpenAPI 3 schema + browsable docs (ROADMAP.md Phase 13). /schema/ returns the
    # raw spec; /docs/ and /redoc/ are the two HTML explorers over it.
    path('api/v1/schema/', SpectacularAPIView.as_view(), name='schema'),
    path(
        'api/v1/docs/',
        SpectacularSwaggerView.as_view(url_name='schema'),
        name='swagger-ui',
    ),
    path(
        'api/v1/redoc/',
        SpectacularRedocView.as_view(url_name='schema'),
        name='redoc',
    ),
    path('api/v1/auth/', include('apps.auth.urls')),
    path('api/v1/tasks/', include('apps.tasks.urls')),
    # Comments/Evidence nest under the same /tasks/ prefix but live in their own
    # apps -- Django tries each include() at a shared prefix in order until one matches.
    path('api/v1/tasks/', include('apps.comments.urls')),
    path('api/v1/tasks/', include('apps.evidence.urls')),
    path('api/v1/labels/', include('apps.labels.urls')),
    path('api/v1/tenant/', include('apps.tenants.urls')),
    path('api/v1/sticky-notes/', include('apps.sticky_notes.urls')),
    path('api/v1/broadcast-notices/', include('apps.broadcasts.urls')),
    path('api/v1/search/', include('apps.search.urls')),
    path('api/v1/nudges/', include('apps.notifications.urls')),
    path('api/v1/notifications/', include('apps.notifications.notification_urls')),
    path('api/v1/platform-admin/', include('apps.platform_admin.urls')),
    # /me, /me/profile-picture, /users/:userId/profile-picture[/file] -- no
    # single shared prefix with the rest of this app's routes, so mounted at
    # bare api/v1/ and left to apps.users.urls to define full sub-paths.
    path('api/v1/', include('apps.users.urls')),
    path('api/v1/upload/presign/', EvidencePresignView.as_view(), name='evidence-presign'),
    path('api/v1/upload/voice-presign/', VoicePresignView.as_view(), name='voice-presign'),
    path(
        'api/v1/upload/broadcast-image-presign/',
        BroadcastImagePresignView.as_view(),
        name='broadcast-image-presign',
    ),
    path(
        'api/v1/upload/profile-picture-presign/',
        ProfilePicturePresignView.as_view(),
        name='profile-picture-presign',
    ),
]
