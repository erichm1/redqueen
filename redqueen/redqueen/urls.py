"""
URL configuration for redqueen project.

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
    1. Import the include() function: from django.urls import include, path, reverse_lazy
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse_lazy
from drf_yasg import openapi
from drf_yasg.views import get_schema_view
from rest_framework import permissions

from web.views import PortalLoginView

schema_view = get_schema_view(
    openapi.Info(title='RedQueen API', default_version='v1'),
    public=False,
    permission_classes=[permissions.IsAuthenticated],
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='swagger'),
    # themed password pages must be routed explicitly: the admin app ships templates with the same names
    path('accounts/password_change/', auth_views.PasswordChangeView.as_view(
        template_name='web/password_change_form.html', success_url=reverse_lazy('password_change_done')),
        name='password_change'),
    path('accounts/password_change/done/', auth_views.PasswordChangeDoneView.as_view(
        template_name='web/password_change_done.html'), name='password_change_done'),
    # sign-in goes through the hellgate portal (web.views.PortalLoginView), then on to the app
    path('accounts/login/', PortalLoginView.as_view(), name='login'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('', include('web.urls')),
]
