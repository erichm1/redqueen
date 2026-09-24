from django.urls import path

from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('intake/new/', views.intake_new, name='intake-new'),
    path('intakes/', views.intake_list, name='intake-list'),
    path('intakes/<int:pk>/', views.intake_detail, name='intake-detail'),
    path('intakes/<int:pk>/media/', views.intake_media, name='intake-media'),
    path('intakes/<int:pk>/annotated/', views.intake_annotated, name='intake-annotated'),
    path('profiles/', views.profile_list, name='profile-list'),
    path('profiles/<int:pk>/', views.profile_detail, name='profile-detail'),
    path('profiles/<int:pk>/review/', views.profile_review, name='profile-review'),
    path('profiles/<int:pk>/judgment/', views.profile_judgment, name='profile-judgment'),
    path('people/', views.person_list, name='person-list'),
    path('people/enroll/', views.person_enroll, name='person-enroll'),
    path('people/<int:pk>/', views.person_detail, name='person-detail'),
    path('people/<int:pk>/delete/', views.person_delete, name='person-delete'),
    path('audit/', views.audit_log, name='audit'),
]
