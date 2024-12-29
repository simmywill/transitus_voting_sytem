"""
URL configuration for voting_system project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
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
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from voters import views as voters_views
from voters.views import manage_session, add_segments  , edit_segment

urlpatterns = [
    #path('admin/', admin.site.urls),
    #path('', voters_views.home_page, name = 'home_page'),
    path('list/<int:session_id>/', voters_views.voter_list, name = 'voter_list'),
    path('list-uuid/<uuid:session_uuid>/', voters_views.voter_list, name='voter_list'),
    path('', voters_views.login_view, name='login_view'),
    path('admin_main_page', voters_views.admin_main_page, name = 'admin_main_page'),
    path('create_session/', voters_views.create_voting_session, name = 'create_voting_session'),
    path('list_sessions/', voters_views.list_voting_sessions, name = 'list_voting_sessions'),
    path('manage_session/<int:session_id>/', voters_views.manage_session, name='manage_session'),
    path('manage_session-uuid/<uuid:session_uuid>/', voters_views.manage_session, name='manage_session'),
    path('delete_session/<int:session_id>/', voters_views.delete_voting_session, name = 'delete_voting_session'),
    path('add_segments/<int:session_id>/', voters_views.add_segments, name='add_segments'),
    path('voters/', include('voters.urls')),
    path('view_voting_session/<int:session_id>/', voters_views.active_voting_session, name = 'active_voting_session'),
    path('edit_segment/<int:segment_id>/', voters_views.edit_segment, name = 'edit_segment'),
    path('delete_candidate/<int:candidate_id>/', voters_views.delete_candidate, name = 'delete_candidate'),
    path('delete-segment/<int:segment_id>/', voters_views.delete_segment, name = 'delete_segment'),
    path('update-segment-order/', voters_views.update_segment_order, name='update_segment_order'),
    path('activate_session/<int:session_id>/', voters_views.activate_session, name = 'activate_session'),
    path('voter_session/verify/<uuid:session_uuid>/', voters_views.voter_verification, name = 'voter_verification'),
    path('voter_session/<uuid:session_uuid>/<int:voter_id>/', voters_views.voter_session, name = 'voter_session'),
    path('submit_vote/<uuid:session_uuid>/<int:voter_id>/', voters_views.submit_vote, name='submit_vote'),
    path('segment_results/<uuid:session_uuid>/', voters_views.segment_results, name = 'segment_results'),
    path('voter_counts/<uuid:session_uuid>/', voters_views.voter_counts, name = 'voter_counts'),
    path('get_voters-uuid/<uuid:session_uuid>/', voters_views.get_voters, name = 'get_voters'),
    path('get_voters/<int:session_id>/', voters_views.get_voters, name='get_voters'),
    path('get_voter_status/<uuid:session_uuid>/', voters_views.get_voter_status, name='get_voter_status'),





] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
