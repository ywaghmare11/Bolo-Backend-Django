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
from django.urls import include, path

from apps.broadcasts.views import BroadcastImagePresignView
from apps.evidence.views import EvidencePresignView
from apps.tasks.views import VoicePresignView

urlpatterns = [
    path('admin/', admin.site.urls),
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
    path('api/v1/upload/presign/', EvidencePresignView.as_view(), name='evidence-presign'),
    path('api/v1/upload/voice-presign/', VoicePresignView.as_view(), name='voice-presign'),
    path(
        'api/v1/upload/broadcast-image-presign/',
        BroadcastImagePresignView.as_view(),
        name='broadcast-image-presign',
    ),
]
