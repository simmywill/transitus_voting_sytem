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
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve as media_serve
from voters import views as voters_views
from voters import cis_views, bbs_views

urlpatterns = [
    #path('admin/', admin.site.urls),
    #path('', voters_views.home_page, name = 'home_page'),
    path('list/<int:session_id>/', voters_views.voter_list, name = 'voter_list'),
    path('list-uuid/<uuid:session_uuid>/', voters_views.voter_list, name='voter_list'),
    path('', voters_views.login_view, name='login_view'),
    #path('admin_main_page', voters_views.admin_main_page, name = 'admin_main_page'),
    #path('create_session/', voters_views.create_voting_session, name = 'create_voting_session'),
    path('list_sessions/', voters_views.list_voting_sessions, name = 'list_voting_sessions'),
    path('delete_session/<int:session_id>/', voters_views.delete_voting_session, name = 'delete_voting_session'),
    path('add_segments/<int:session_id>/', voters_views.add_segments, name='add_segments'),
    path('voters/', include('voters.urls')),
    path('view_voting_session/<int:session_id>/', voters_views.active_voting_session, name = 'active_voting_session'),
    path('edit_segment/<int:segment_id>/', voters_views.edit_segment, name = 'edit_segment'),
    path('delete_candidate/<int:candidate_id>/', voters_views.delete_candidate, name = 'delete_candidate'),
    path('segments/<int:segment_id>/candidates/', voters_views.create_candidate, name='create_candidate'),
    path('candidate/<int:candidate_id>/name/', voters_views.update_candidate_name, name='update_candidate_name'),
    path('candidate/<int:candidate_id>/photo/', voters_views.update_candidate_photo, name='update_candidate_photo'),
    path('candidate/<int:candidate_id>/photo/remove/', voters_views.remove_candidate_photo, name='remove_candidate_photo'),
    path('delete-segment/<int:segment_id>/', voters_views.delete_segment, name = 'delete_segment'),
    path('update-segment-order/', voters_views.update_segment_order, name='update_segment_order'),
    path('activate_session/<int:session_id>/', voters_views.activate_session, name = 'activate_session'),
    path('motions/', include('motions.urls')),
    path('voters/import/<uuid:session_uuid>/', voters_views.import_voters, name='import_voters_uuid'),
    path('voters/import-id/<int:session_id>/', voters_views.import_voters, name='import_voters'),
    path('voters/template/', voters_views.voter_template_download, name='voter_template_download'),
    path('sessions/<uuid:session_uuid>/register/', voters_views.self_register, name='self_register'),
    path('sessions/<int:session_id>/self-registration/', voters_views.toggle_self_registration, name='toggle_self_registration'),
    # Legacy verify path now points to CIS verify form for backward-compatible QR links
    path('voter_session/verify/<uuid:session_uuid>/', cis_views.verify_form, name='voter_verification'),
    path('voter_counts/<uuid:session_uuid>/', voters_views.voter_counts, name = 'voter_counts'),
    path('get_voters-uuid/<uuid:session_uuid>/', voters_views.get_voters, name = 'get_voters'),
    path('get_voters/<int:session_id>/', voters_views.get_voters, name='get_voters'),
    path('get_voter_status/<uuid:session_uuid>/', voters_views.get_voter_status, name='get_voter_status'),
    path('manual-check/<uuid:session_uuid>/', voters_views.manual_check_page, name='manual_check_page'),
    path('manual_check/<uuid:session_uuid>/', voters_views.manual_check_card, name='manual_check_card'),
    path('sessions/<int:session_id>/segments/', voters_views.create_segment, name='create_segment'),
    path('segment/<int:segment_id>/name/', voters_views.update_segment_name, name='update_segment_name'),
    # Dynamic QR image endpoint (serves PNG without relying on MEDIA persistence)
    path('qr/<uuid:session_uuid>.png', voters_views.qr_png, name='qr_png'),




]

# New CIS/BBS endpoints
urlpatterns += [
    # CIS (verify.agm.local)
    path('verify/<uuid:session_uuid>/', cis_views.verify_form, name='cis_verify_form'),
    path('api/verify', cis_views.api_verify, name='cis_api_verify'),
    path('api/redeem', cis_views.api_redeem, name='cis_api_redeem'),
    path('api/mark-spent', cis_views.api_mark_spent, name='cis_api_mark_spent'),
    path('voter_status/<uuid:session_uuid>/', cis_views.voter_status, name='cis_voter_status'),

    # BBS (vote.agm.local)
    path('ballot/<uuid:session_uuid>/', bbs_views.ballot_entry, name='bbs_ballot_entry'),
    path('api/cast', bbs_views.api_cast, name='bbs_api_cast'),
    path('results/<uuid:session_uuid>/', bbs_views.results, name='bbs_results'),
    path('thanks/<uuid:session_uuid>/', bbs_views.thanks, name='bbs_thanks'),
    path('api/cvr/<uuid:session_uuid>/', bbs_views.export_cvr, name='bbs_export_cvr'),
]


if not settings.USE_S3_MEDIA:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # Ensure MEDIA files are served even when DEBUG=False (Render). This is a
    # pragmatic fix for local/dev uploads when not using S3.
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', media_serve, {
            'document_root': settings.MEDIA_ROOT,
            'show_indexes': False,
        }),
    ]
