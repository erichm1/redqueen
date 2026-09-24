from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('intakes', views.IntakeViewSet, basename='intake')
router.register('profiles', views.ProfileViewSet, basename='profile')

urlpatterns = [
    path('', include(router.urls)),
    path('persons/<int:person_id>/risk/', views.PersonRiskView.as_view(), name='person-risk'),
    path('compstat/', views.CompstatView.as_view(), name='compstat'),
]
