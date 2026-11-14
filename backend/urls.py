"""
URL configuration for backend project.

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

from server import sms_views

urlpatterns = [
    path("api/", include("server.api_urls")),   # resident API for the Flutter app
    path("sms/twilio/", sms_views.incoming_sms, name="sms_incoming"),        # Twilio: incoming texts
    path("sms/twilio/status/", sms_views.sms_status, name="sms_status"),     # Twilio: delivery status
    path("", include("server.urls")),   # admin console at the site root (no leading slash)
    path("admin/", admin.site.urls),
]
