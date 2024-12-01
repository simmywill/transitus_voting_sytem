from django.urls import path
from . import views

urlpatterns = [  
    path('edit-voter/<int:voter_id>/<int:session_id>/', views.edit_voter, name='edit_voter_by_id'),
    path('edit-voter-uuid/<int:voter_id>/<uuid:session_uuid>/', views.edit_voter, name='edit_voter_by_uuid'),
    path('delete-voter/<int:voter_id>/<int:session_id>/', views.delete_voter, name='delete_voter_by_id'),
    path('delete-voter-uuid/<int:voter_id>/<uuid:session_uuid>/', views.delete_voter, name='delete_voter_by_uuid'),
    #path('session/create/', views.create_voting_session, name='create_voting_session'),
    #path('session/list/', views.list_voting_sessions, name='list_voting_sessions'),
    path('session/delete/<int:session_id>/', views.delete_voting_session, name='delete_voting_session'),
    
]
