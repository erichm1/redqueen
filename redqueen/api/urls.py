from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register('intakes', views.IntakeViewSet, basename='intake')
router.register('profiles', views.ProfileViewSet, basename='profile')
router.register('persons', views.PersonViewSet, basename='person')

urlpatterns = [
    # numeric-id route first: the router's UUID lookup would otherwise swallow it
    path('persons/<int:person_id>/risk/', views.PersonRiskView.as_view(), name='person-risk-by-id'),
    path('', include(router.urls)),
    path('compstat/', views.CompstatView.as_view(), name='compstat'),
]
