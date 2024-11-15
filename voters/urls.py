from django.urls import path
from . import views

urlpatterns = [  
    path('edit/<int:voter_id>/', views.edit_voter, name='edit_voter'),
    path('delete/<int:voter_id>/', views.delete_voter, name='delete_voter'),
    #path('session/create/', views.create_voting_session, name='create_voting_session'),
    #path('session/list/', views.list_voting_sessions, name='list_voting_sessions'),
    path('session/delete/<int:session_id>/', views.delete_voting_session, name='delete_voting_session'),
]
