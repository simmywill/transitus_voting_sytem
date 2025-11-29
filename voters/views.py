from django.shortcuts import render, redirect
from .models import VotingSession, Voter, Candidate, VotingSegmentHeader, ManualCheckCard  # Import the Voter model
from .forms import VoterForm , VotingSessionForm
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
import logging
from django.db.models import Q, Value
from django.db.models.functions import Concat
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect, get_object_or_404
import json
from django.urls import reverse
from django.http import Http404
from django.conf import settings
from django.template.loader import render_to_string
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.http import require_POST
from django.db import transaction
from django.db.models import Case, When, IntegerField
from django.middleware.csrf import get_token
from django.views.decorators.cache import never_cache
from io import BytesIO
import qrcode
import os





logger = logging.getLogger(__name__)


def home_page(request):
    return render(request, "voters/landing_page.html")
    
from django.contrib.auth import authenticate, login
from django.shortcuts import render, redirect
from django.contrib import messages

def login_view(request):
    """Log user in"""
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        # Ensure username was submitted
        if not username:
            messages.error(request, "Must provide username")
            return render(request, "voters/landing_page.html")

        # Ensure password was submitted
        if not password:
            messages.error(request, "Must provide password")
            return render(request, "voters/landing_page.html")

        # Authenticate user
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)  # Log in the user
            return redirect("list_voting_sessions")  # Redirect to admin main page
        else:
            messages.error(request, "Invalid username and/or password")
    
    return render(request, "voters/landing_page.html")  # Render login form if GET request

'''
@login_required
def admin_main_page(request):
    return redirect(request, "voters/list_voting_sessions")


@login_required
def create_voting_session(request):
    if request.method == 'POST':
        form = VotingSessionForm(request.POST)
        if form.is_valid():
            voting_session = form.save(commit=False)
            voting_session.admin = request.user
            voting_session.save()
            # Redirect to manage session page for the specific session_id
            return redirect('list_voting_sessions')
    else:
        form = VotingSessionForm()
    return render(request, 'voters/list_sessions.html', {'form': form})
'''


@login_required
@never_cache
def manage_session(request, session_id=None , session_uuid=None):
     # Determine the voting session
    if session_uuid:
        # Prefer canonical UUID; fallback to legacy unique_url contains
        try:
            voting_session = VotingSession.objects.get(session_uuid=session_uuid)
        except Exception:
            voting_session = get_object_or_404(VotingSession, unique_url__contains=f'{session_uuid}')
    elif session_id:
        voting_session = get_object_or_404(VotingSession, session_id=session_id)
    else:
        raise Http404("Session identifier not provided.")
    
    # Retrieve any existing segments and candidates associated with this session
    segments = (
        VotingSegmentHeader.objects
        .filter(session=voting_session)
        .prefetch_related('candidates')
        .order_by('order', 'id')
    )
    
    return render(request, 'voters/manage_session.html', {
        'session': voting_session,
        'segments': segments,
    })
    

@login_required
def add_segments(request, session_id):
    session = get_object_or_404(VotingSession, session_id=session_id, admin=request.user)
    if request.method == 'POST':
        print("Successfully received form data")

        # Iterate over all the keys in the POST data
        for key in request.POST:
            if key.startswith('segments['):  # Filter keys that belong to segments
                # Get the segment index from the key
                segment_index = key.split('[')[1].split(']')[0]
                if 'header' in key:
                    # Extract the header name for the segment
                    header_name = request.POST.get(f'segments[{segment_index}][header]')
                    if header_name:
                        print(f"Segment Header: {header_name}")
                        header = VotingSegmentHeader.objects.create(name=header_name, session=session)

                    # Loop through candidates for this segment
                    candidate_index = 0
                    while f'segments[{segment_index}][candidates][{candidate_index}][name]' in request.POST:
                        candidate_name = request.POST.get(f'segments[{segment_index}][candidates][{candidate_index}][name]')
                        candidate_photo = request.FILES.get(f'segments[{segment_index}][candidates][{candidate_index}][photo]')
                        if candidate_name and candidate_photo:
                            Candidate.objects.create(
                                name=candidate_name,
                                photo=candidate_photo,
                                voting_session=session,
                                segment_header=header
                            )
                        candidate_index += 1
        return redirect('add_segments', session_id=session_id)

    segments = (
        session.segments
        .prefetch_related('candidates')
        .order_by('order', 'id')
    )
    return render(request , 'voters/manage_session.html' , {
        'session' :  session,
        'segments': segments,
    })



@login_required
@never_cache
def active_voting_session(request, session_id):
    # Retrieve the voting session with the given ID
    session = get_object_or_404(VotingSession, session_id=session_id, admin=request.user)

    # Retrieve all segments and their candidates associated with this session
    segments = (
        VotingSegmentHeader.objects
        .filter(session=session)
        .prefetch_related('candidates')
        .order_by('order', 'id')
    )

    context = {
        'session': session,
        'segments': segments,
        'csrf_token_value': get_token(request),
    }
    return render(request, 'voters/voting_session.html', context)


@login_required
@require_POST
def update_segment_order(request):
    """
    Persist the user-defined order of segments.

    Expects JSON payload: { "order": [segment_id_1, segment_id_2, ...] }
    Updates VotingSegmentHeader.order to the index in the list (0-based).
    """
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    order_list = payload.get('order')
    if not isinstance(order_list, list) or not order_list:
        return JsonResponse({'success': False, 'error': 'Missing or invalid "order" list'}, status=400)

    # Deduplicate while preserving order; coerce to ints where possible
    seen = set()
    cleaned_ids = []
    for sid in order_list:
        try:
            sid_int = int(sid)
        except (TypeError, ValueError):
            continue
        if sid_int not in seen:
            seen.add(sid_int)
            cleaned_ids.append(sid_int)

    if not cleaned_ids:
        return JsonResponse({'success': False, 'error': 'No valid segment IDs'}, status=400)

    # Build CASE expression to update in a single query
    cases = [When(pk=sid, then=Value(idx)) for idx, sid in enumerate(cleaned_ids)]
    try:
        with transaction.atomic():
            updated = (VotingSegmentHeader.objects
                       .filter(pk__in=cleaned_ids, session__admin=request.user)
                       .update(order=Case(*cases, output_field=IntegerField())))
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

    return JsonResponse({'success': True, 'updated': int(updated)})


@login_required
@never_cache
def list_voting_sessions(request):
    if request.method == 'POST':
        form = VotingSessionForm(request.POST)
        if form.is_valid():
            voting_session = form.save(commit=False)
            voting_session.admin = request.user
            voting_session.save()
            return redirect('list_voting_sessions')
    else:
        form = VotingSessionForm()

    sessions = (
        VotingSession.objects
        .filter(admin=request.user)
        .order_by('-created_at', '-session_id')
    )
    # Best-effort: if a session has a unique_url but no QR file present, rebuild it.
    for s in sessions:
        try:
            if s.unique_url and (not getattr(s, 'qr_code', None) or not getattr(s.qr_code, 'path', None) or not os.path.exists(s.qr_code.path)):
                s.ensure_qr_file()
        except Exception:
            # Non-fatal; continue rendering list
            pass
    return render(request, 'voters/list_sessions.html', {
        'sessions': sessions,
        'form': form
    })


@never_cache
def qr_png(request, session_uuid):
    """Serve a QR PNG for the session's unique_url without relying on MEDIA.
    This avoids 404s in multi-instance environments with ephemeral disks.
    """
    try:
        session = VotingSession.objects.get(session_uuid=session_uuid)
    except Exception:
        session = get_object_or_404(VotingSession, unique_url__contains=f"{session_uuid}")

    if not session.unique_url:
        protocol = 'https' if request.is_secure() else 'http'
        host = request.get_host()
        # Point verification to the CIS verify_form route
        session.unique_url = f'{protocol}://{host}/verify/{session.session_uuid}'
        session.save(update_fields=['unique_url'])

    img = qrcode.make(session.unique_url)
    buf = BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    resp = HttpResponse(buf.getvalue(), content_type='image/png')
    resp['Cache-Control'] = 'no-store'
    return resp


@login_required
@require_POST
def activate_session(request, session_id):
    """Activate a voting session and ensure share link + QR are available.
    Returns JSON consumed by the front-end activation script.
    """
    session = get_object_or_404(VotingSession, session_id=session_id, admin=request.user)

    # Set active flag if not already
    if not session.is_active:
        session.is_active = True
        session.save(update_fields=['is_active'])

    # Ensure unique_url/QR exist; regenerate if either is missing
    if not session.unique_url or not getattr(session, 'qr_code', None):
        try:
            session.generate_qr_code(request)
        except Exception as e:
            return JsonResponse({'success': False, 'error': f'QR generation failed: {e}'}, status=500)

    dynamic_qr_url = request.build_absolute_uri(reverse('qr_png', args=[session.session_uuid]))
    payload = {
        'success': True,
        'session_uuid': session.get_uuid(),
        'unique_url': session.unique_url or '',
        'qr_code_url': (session.qr_code.url if getattr(session, 'qr_code', None) else dynamic_qr_url),
        'session_title': session.title,
        'results_url': request.build_absolute_uri(reverse('bbs_results', args=[session.session_uuid])),
    }
    return JsonResponse(payload)


@login_required
def delete_voting_session(request, session_id):
    session = get_object_or_404(VotingSession, session_id=session_id, admin=request.user)

    if request.method == 'POST':
        if 'confirm' in request.POST:  # User confirmed deletion
            session.delete()
            messages.success(request, f'Successfully deleted the session "{session.title}".')
            return redirect('list_voting_sessions')
        elif 'cancel' in request.POST:  # User canceled deletion
            messages.info(request, f'Deletion of session "{session.title}" was canceled.')
            return redirect('list_voting_sessions')

    return render(request, 'voters/delete_session.html', {'session': session})

"""
def add_voters(request , session_id=None, session_uuid=None):
    # Determine which identifier to use
    if session_uuid:
        voting_session = get_object_or_404(VotingSession, unique_url__contains=f'')
    elif session_id:
        voting_session = get_object_or_404(VotingSession, session_id=session_id)
    else:
        raise Http404("Session identifier not provided.")

    if request.method == "POST":
        form = VoterForm(request.POST)
        if form.is_valid():
            # Create a new voter
            voter = form.save(commit=False)
            voter.session = voting_session  # Assign the VotingSession instance
            voter.save()
            # Redirect based on the identifier
            # Send back a success response for AJAX
            return JsonResponse({"success": True, "message": "Voter added successfully!"})
        else:
            # Send back errors if the form is invalid
            return JsonResponse({"success": False, "errors": form.errors}, status=400)
    else:
        form = VoterForm()

    return render(
        request,
        "voters/voter_list.html",
        {
            'form': form,
            'session_id': session_id,
            'session_uuid': session_uuid,
            'session': voting_session,
        },
    )"""

@login_required
@never_cache
def voter_list(request, session_id=None, session_uuid=None):
    # Determine the voting session
    if session_uuid:
        voting_session = get_object_or_404(VotingSession, session_uuid=session_uuid)
    elif session_id:
        voting_session = get_object_or_404(VotingSession, session_id=session_id)
    else:
        raise Http404("Session identifier not provided.")
    
    print("Voting session:", voting_session)
    print("Unique URL:", voting_session.unique_url)

    voters = voting_session.voters.all()  # Retrieve all voters for the session

    # Counts
    verified_voters_count = voters.filter(is_verified=True).count()
    finished_voters_count = voters.filter(has_finished=True).count()
    total_voters_count = voters.count()
    is_active = voting_session.is_active

    # Extract UUID (canonical, independent of unique_url)
    extracted_uuid = str(voting_session.session_uuid)
    print(extracted_uuid)

    # Handle GET request (search functionality)
    if request.method == "GET":
        search_query = request.GET.get('search', '').strip()  # Get and strip the search query
        filter_state = request.GET.get('filter', 'all')
        
        if search_query:
            search_query = search_query.strip()
            
            # First, check if the entire query matches an exact first name or last name
            exact_matches = voters.filter(
                Q(Fname__iexact=search_query) | Q(Lname__iexact=search_query)
            )
            if exact_matches.exists():
                voters = exact_matches
            else:
                # Split the search query into first name and last name parts
                parts = search_query.split(' ')
                first_name = parts[0]
                last_name = parts[1] if len(parts) > 1 else ''

                # Construct a Q object for searching by first name and/or last name
                filters = Q()
                if first_name:
                    filters &= Q(Fname__icontains=first_name) 
                if last_name:
                    filters &= Q(Lname__icontains=last_name)

                # Filter voters based on constructed filters
                voters = voters.filter(filters)
        # Apply the selected filter
        if filter_state == 'verified':
            voters = voters.filter(is_verified=True)
        elif filter_state == 'not_verified':
            voters = voters.filter(is_verified=False)
        elif filter_state == 'verified_finished':
            voters = voters.filter(is_verified=True, has_finished=True)
        elif filter_state == 'all':
            pass  # No additional filtering, show all voters
        
        # Render the page with the searched voters
        return render(
            request,
            'voters/voter_list.html',
            {
                'form': VoterForm(),
                'voters': voters,
                'verified_voters_count': verified_voters_count,
                'finished_voters_count': finished_voters_count,
                'total_voters_count': total_voters_count,
                'voting_session': voting_session,
                'session_uuid': extracted_uuid,  # Pass the extracted UUID
                'session_id': session_id,
                'is_active': is_active,
                'csrf_token_value': get_token(request),
            },
        )

    # Handle POST request (adding a voter)
    elif request.method == "POST":
        form = VoterForm(request.POST)
        if form.is_valid():
            # Create a new voter
            voter = form.save(commit=False)
            voter.session = voting_session  # Assign the VotingSession instance
            voter.save()
            # Redirect to the voter list page
            if session_uuid:
                return redirect('voter_list', session_uuid=session_uuid)
            return redirect('voter_list', session_id=session_id)

        # Handle invalid form: render page with errors
        voters = voting_session.voters.all()  # Default voters (no search)
        return render(
            request,
            'voters/voter_list.html',
            {
                'form': form,
                'voters': voters,
                'verified_voters_count': voters.filter(is_verified=True).count(),
                'finished_voters_count': voters.filter(has_finished=True).count(),
                'total_voters_count': voters.count(),
                'voting_session': voting_session,
                'session_uuid': str(voting_session.session_uuid),
                'session_id': session_id,
                'is_active': voting_session.is_active,
                'csrf_token_value': get_token(request),
            },
        )



@login_required
def delete_voter(request, voter_id):

    session_uuid = request.GET.get('session_uuid')
    session_id = request.GET.get('session_id')


    if session_uuid:
        try:
            voter = Voter.objects.get(voter_id=voter_id, session__session_uuid=session_uuid)
        except Exception:
            voter = get_object_or_404(Voter, voter_id=voter_id, session__unique_url__contains=f'{session_uuid}')
    elif session_id:
        voter = get_object_or_404(Voter, voter_id=voter_id, session__session_id=session_id)
    else:
        raise Http404("Session identifier not provided.")

    if request.method == 'POST':
        voter.delete()
        if session_uuid:
            return redirect('voter_list', session_uuid=session_uuid)
        return redirect('voter_list', session_id=session_id)

    return render(request, 'voters/delete_voter.html', {'voter': voter})

@login_required
def edit_voter(request, voter_id):

    session_uuid = request.GET.get('session_uuid')
    session_id = request.GET.get('session_id')

    if session_uuid:
        try:
            voter = Voter.objects.get(voter_id=voter_id, session__session_uuid=session_uuid)
        except Exception:
            voter = get_object_or_404(Voter, voter_id=voter_id, session__unique_url__contains=f'{session_uuid}')
    elif session_id:
        voter = get_object_or_404(Voter, voter_id=voter_id, session__session_id=session_id)
    else:
        raise Http404("Session identifier not provided.")

    if request.method == 'POST':
        form = VoterForm(request.POST, instance=voter)
        if form.is_valid():
            form.save()
            if session_uuid:
                return redirect('voter_list', session_uuid=session_uuid)
            return redirect('voter_list', session_id=session_id)
    else:
        form = VoterForm(instance=voter)

    return render(request, 'voters/edit_voter.html', {'form': form, 'voter': voter})




from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from .models import Candidate, VotingSegmentHeader

@login_required
@never_cache
def edit_segment(request, segment_id):
    # Retrieve the segment to be edited
    segment = get_object_or_404(VotingSegmentHeader, id=segment_id)
    session_id = segment.session_id

    if request.method == "POST":
        # Update the segment name
        segment.name = request.POST.get('segment_name', segment.name)
        segment.save()

        # Update existing candidates
        existing_candidates = list(segment.candidates.all())
        for idx, candidate in enumerate(existing_candidates):
            candidate_name = request.POST.get(f'candidates[{idx}][name]')
            candidate_photo = request.FILES.get(f'candidates[{idx}][photo]')
            if candidate_name:
                candidate.name = candidate_name
            if candidate_photo:
                candidate.photo = candidate_photo
            candidate.save()

        # Process new candidates from dynamically added inputs
        # newCandidate_name[] and newCandidate_photo[] are expected as lists in POST data
        new_candidate_names = request.POST.getlist('newCandidate_name[]')
        new_candidate_photos = request.FILES.getlist('newCandidate_photo[]')
        print(len(new_candidate_names))
        # Loop through the names and photos, creating new Candidate objects
        for name, photo in zip(new_candidate_names, new_candidate_photos):
            if name and photo:  # Ensure both name and photo are provided
                new_candidate = Candidate(
                    name=name,
                    photo=photo,
                    voting_session=segment.session,
                    segment_header=segment
                )
                new_candidate.save()

        # Send a success response for the AJAX request
        return redirect('active_voting_session', session_id=session_id)

    # Context for the GET request to load the edit page
    context = {
        'segment': segment,
    }
    return render(request, 'voters/edit_segment.html', context)


from django.contrib.auth.decorators import login_required

@login_required
def delete_candidate(request, candidate_id):
    if request.method == 'POST':
        candidate = get_object_or_404(Candidate, id=candidate_id)
        session_admin = getattr(candidate.segment_header.session, 'admin', None)
        if request.user.is_authenticated and session_admin and request.user != session_admin:
            return JsonResponse({'success': False, 'error': 'Forbidden'}, status=403)
        if candidate.photo:
            candidate.photo.delete(save=False)
        candidate.delete()
        return JsonResponse({'success': True})
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)


@login_required
def create_candidate(request, segment_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    segment = get_object_or_404(VotingSegmentHeader, id=segment_id)
    session_admin = getattr(segment.session, 'admin', None)
    if request.user.is_authenticated and session_admin and request.user != session_admin:
        return JsonResponse({'success': False, 'error': 'Forbidden'}, status=403)

    default_name = 'Candidate Name'
    name = default_name
    photo = None

    content_type = request.content_type or ''
    if 'application/json' in content_type:
        try:
            payload = json.loads(request.body or '{}')
        except json.JSONDecodeError:
            payload = {}
        name = payload.get('name') or default_name
    else:
        name = request.POST.get('name') or default_name
        photo = request.FILES.get('photo')

    candidate = Candidate(
        name=(name or default_name).strip() or default_name,
        voting_session=segment.session,
        segment_header=segment,
    )

    if photo:
        candidate.photo = photo

    candidate.save()

    return JsonResponse({
        'success': True,
        'candidate': {
            'id': candidate.id,
            'name': candidate.name,
            'photo_url': candidate.photo.url if candidate.photo else None,
        }
    }, status=201)


@login_required
def update_candidate_name(request, candidate_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    candidate = get_object_or_404(Candidate, id=candidate_id)
    session_admin = getattr(candidate.segment_header.session, 'admin', None)
    if request.user.is_authenticated and session_admin and request.user != session_admin:
        return JsonResponse({'success': False, 'error': 'Forbidden'}, status=403)

    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        payload = {}

    name = (payload.get('name') or '').strip()
    if not name:
        return JsonResponse({'success': False, 'error': 'Name is required'}, status=400)

    candidate.name = name
    candidate.save(update_fields=['name'])

    return JsonResponse({'success': True, 'candidate': {'id': candidate.id, 'name': candidate.name}})


@login_required
def update_candidate_photo(request, candidate_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    candidate = get_object_or_404(Candidate, id=candidate_id)
    session_admin = getattr(candidate.segment_header.session, 'admin', None)
    if request.user.is_authenticated and session_admin and request.user != session_admin:
        return JsonResponse({'success': False, 'error': 'Forbidden'}, status=403)

    photo = request.FILES.get('photo')
    if not photo:
        return JsonResponse({'success': False, 'error': 'No photo supplied'}, status=400)

    if candidate.photo:
        candidate.photo.delete(save=False)
    candidate.photo = photo
    candidate.save(update_fields=['photo'])

    return JsonResponse({
        'success': True,
        'candidate': {
            'id': candidate.id,
            'photo_url': candidate.photo.url if candidate.photo else None,
        }
    })


@login_required
def remove_candidate_photo(request, candidate_id):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=405)

    candidate = get_object_or_404(Candidate, id=candidate_id)
    session_admin = getattr(candidate.segment_header.session, 'admin', None)
    if request.user.is_authenticated and session_admin and request.user != session_admin:
        return JsonResponse({'success': False, 'error': 'Forbidden'}, status=403)

    if candidate.photo:
        candidate.photo.delete(save=False)
        candidate.photo = None
        candidate.save(update_fields=['photo'])

    return JsonResponse({'success': True, 'candidate': {'id': candidate.id, 'photo_url': None}})

## Removed duplicate update_segment_order; the transaction-safe version earlier is used.


## Removed insecure unused update_segment endpoint

@login_required
def delete_segment(request, segment_id):
    if request.method == 'POST':
        segment = get_object_or_404(VotingSegmentHeader, id=segment_id)
        segment.delete()
        return JsonResponse({'success': True})
    return JsonResponse({'error': 'Invalid request'}, status=400)


## Removed duplicate activate_session definition (kept earlier, admin-checked)



from django.http import JsonResponse



def voter_verification(request, session_uuid):
    # Retrieve the voting session by canonical UUID, fallback to legacy unique_url contains
    try:
        session = VotingSession.objects.get(session_uuid=session_uuid)
    except Exception:
        session = get_object_or_404(VotingSession, unique_url__contains=f'{session_uuid}')
    
    # Ensure the session is active and not closed
    if not session.is_active:
        raise Http404("This session is not active.")


    error_message = None  # Initialize an error message variable
    submitted_first_name = ''
    submitted_last_name = ''

    if request.method == 'POST':
        # Verify the name entered by the voter
        submitted_first_name = (request.POST.get('first_name') or '').strip()
        submitted_last_name = (request.POST.get('last_name') or '').strip()

        if not submitted_first_name or not submitted_last_name:
            error_message = "Both first and last name are required."
        else:
            # Check if the voter exists in the session, case-insensitive
            voter = session.voters.filter(
                Fname__iexact=submitted_first_name,
                Lname__iexact=submitted_last_name
            ).first()

            # Check if the name is valid
            if voter:
                # Save voter ID in session and redirect
                if not voter.is_verified:
                    voter.is_verified = True
                    voter.save(update_fields=['is_verified'])
                request.session['voter_id'] = voter.voter_id
                return redirect('voter_session', session_uuid=session_uuid, voter_id=voter.voter_id)
            else:
                # Set an error message if the voter is not found
                error_message = "The name entered does not match any registered voter. Please try again."

    # Render the verification page with a form
    context = {
        'session': session,
        'error_message': error_message,
        'submitted_first_name': submitted_first_name,
        'submitted_last_name': submitted_last_name,
    }
    return render(request, 'voters/voter_verification.html', context)


from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from .models import VotingSession, Voter, Vote

def voter_session(request, session_uuid, voter_id):
    # Fetch the session and voter
    try:
        session = VotingSession.objects.get(session_uuid=session_uuid)
    except Exception:
        session = get_object_or_404(VotingSession, unique_url__contains=session_uuid)
    voter = get_object_or_404(Voter, voter_id=voter_id)

    # Ensure the voter is associated with the session
    if voter.session != session:
        return render(request, 'error.html', {'message': 'Unauthorized access.'})

    # Get the current segment
    current_segment = int(request.GET.get('segment', 1))
    segments = session.segments.all().order_by('order')  # Ensure ordering
    segment = segments[current_segment - 1]
    segment_ids = list(segments.values_list('id', flat=True))

    # Retrieve selected votes for the voter
    votes = Vote.objects.filter(voter=voter, segment__in=segments)
    selected_votes = {vote.segment_id: vote.candidate_id for vote in votes}

    # Get the selected candidate for the current segment
    selected_candidate_id = selected_votes.get(segment.id)

    context = {
        'session': session,
        'segment': segment,
        'current_segment': current_segment,
        'total_segments': segments.count(),
        'session_uuid': str(session.session_uuid),
        'voter_id': voter_id,  # Pass the voter_id in context
        'selected_candidate_id': selected_candidate_id,  # Pass selected candidate for the current segment
        'segment_ids_json': json.dumps(segment_ids),
    }
    return render(request, 'voters/voting_page.html', context)







def submit_vote(request, session_uuid , voter_id):
    if request.method == 'POST':
        # Disable legacy write path when anonymous handoff is enabled
        if getattr(settings, 'ANON_HANDOFF_ENABLED', False):
            return JsonResponse({'error': 'Anonymous handoff enabled. Use /api/cast via BBS.'}, status=400)
        print(f"Received POST request for session: {session_uuid}, voter: {voter_id}")
        voter = get_object_or_404(Voter,voter_id=voter_id)
        try:
            session = VotingSession.objects.get(session_uuid=session_uuid)
        except Exception:
            session = get_object_or_404(VotingSession, unique_url__contains=f'{session_uuid}')

        

        if not session:
            print(f"Session with UUID {session_uuid} not found.")
            return JsonResponse({'error': 'Session invalid'}, status=402)

        if not voter_id:
            print(f"Voter ID not found: {voter_id}")
            return JsonResponse({'error': 'Voter not authenticated'}, status=401)

        # Parse the incoming data
        try:
            data = json.loads(request.body)
            print(f"Parsed vote data: {data}")
            votes = data.get('votes', {})
        except json.JSONDecodeError:
            print(f"Error parsing JSON: {request.body}")
            return JsonResponse({'error': 'Invalid data'}, status=400)

        # Save votes and update tallies
        for segment_id, candidate_id in votes.items():
            print(f"Processing vote for segment: {segment_id}, candidate: {candidate_id}")
            segment = get_object_or_404(VotingSegmentHeader, id=segment_id, session=session)
            candidate = get_object_or_404(Candidate, id=candidate_id, segment_header__id=segment_id)


            # Save individual vote
            Vote.objects.create(
                voter_id=voter_id,
                candidate=candidate,
                segment=segment,
            )

            # Update candidate's total tally
            candidate.total_votes += 1
            candidate.save()
        
        # Mark the voter as having finished voting
        voter.has_finished = True
        voter.save()

        return JsonResponse({'success': True})

    print(f"Invalid request method: {request.method}")
    return JsonResponse({'error': 'Invalid request method'}, status=405)



from django.db.models import Count

from django.core.serializers import serialize

from django.db.models import Count, Max

def segment_results(request, session_uuid):
    # Admin-only: restrict to authenticated staff
    if not request.user.is_authenticated or not getattr(request.user, 'is_staff', False):
        return HttpResponseForbidden("Results are restricted to administrators.")
    try:
        session = VotingSession.objects.get(session_uuid=session_uuid)
    except Exception:
        session = get_object_or_404(VotingSession, unique_url__contains=f'{session_uuid}')
    segments = session.segments.all()

    # Calculate the vote tallies
    tally = []
    for segment in segments:
        # Annotate candidates with vote counts
        candidates = (
            segment.candidates
            .annotate(vote_count=Count('vote__id'))
            .order_by('-vote_count', 'name')
        )
        
        # Determine the winner
        winner = candidates.order_by('-vote_count').first() if candidates else None
        winner_data = {
            'id': winner.id,
            'name': winner.name,
            'votes': winner.vote_count,
            'photo_url': winner.photo.url
        } if winner else None
        
        # Append segment data with winner information
        tally.append({
            'segment_id': segment.id,
            'name': segment.name,
            'candidates': [{'id': c.id, 'name': c.name, 'votes': c.vote_count, 'photo_url': c.photo.url } for c in candidates],
            'winner': winner_data
        })

    # Render the tally page with serialized tally data
    return render(request, 'voters/results.html', {
        'tally': tally,
        'session': session,
        'segments_json': json.dumps(tally)  # Pass JSON-encoded data
    })



        


from django.shortcuts import render, get_object_or_404
from .models import Voter, Vote, VotingSession, VotingSegmentHeader, Candidate

def review_voter_results(request, voter_id, session_uuid):
    # Retrieve the voting session using session_uuid (canonical), fallback legacy
    try:
        session = VotingSession.objects.get(session_uuid=session_uuid)
    except Exception:
        session = get_object_or_404(VotingSession, unique_url__contains=f'{session_uuid}')
    
    # Get the voter from the database
    voter = get_object_or_404(Voter, voter_id=voter_id, session=session)
    
    # Retrieve all the segments the voter voted on
    votes = Vote.objects.filter(voter=voter)

    # Prepare the data to be displayed
    vote_details = []
    for vote in votes:
        segment = vote.segment
        candidate = vote.candidate
        vote_details.append({
            'segment_name': segment.name,
            'candidate_name': candidate.name,
            'candidate_photo': candidate.photo.url if candidate.photo else None,  # Assuming 'photo' is a field in the Candidate model
        })

    return render(request, 'voters/review_voter_results.html', {
        'voter': voter,
        'vote_details': vote_details,
        'session': session,
    })


@login_required
@never_cache
def manual_check_page(request, session_uuid):
    if not request.user.is_authenticated or not getattr(request.user, 'is_staff', False):
        return HttpResponseForbidden("Manual check is restricted to administrators.")
    try:
        voting_session = VotingSession.objects.get(session_uuid=session_uuid)
    except Exception:
        voting_session = get_object_or_404(VotingSession, unique_url__contains=f'{session_uuid}')

    voters = voting_session.voters.all()
    verified_voters_count = voters.filter(is_verified=True).count()
    finished_voters_count = voters.filter(has_finished=True).count()
    total_voters_count = voters.count()

    return render(
        request,
        'voters/manual_check.html',
        {
            'voting_session': voting_session,
            'session_uuid': str(voting_session.session_uuid),
            'verified_voters_count': verified_voters_count,
            'finished_voters_count': finished_voters_count,
            'total_voters_count': total_voters_count,
            'csrf_token_value': get_token(request),
        },
    )


@login_required
def manual_check_card(request, session_uuid):
    if not request.user.is_authenticated or not getattr(request.user, 'is_staff', False):
        return HttpResponseForbidden("Manual check is restricted to administrators.")
    try:
        session = VotingSession.objects.get(session_uuid=session_uuid)
    except Exception:
        session = get_object_or_404(VotingSession, unique_url__contains=f'{session_uuid}')

    try:
        index = int(request.GET.get('index', 0))
    except (TypeError, ValueError):
        index = 0
    index = max(0, index)

    cards_qs = (
        ManualCheckCard.objects
        .filter(session=session)
        .order_by('created_at', 'id')
        .prefetch_related('ballots__segment', 'ballots__candidate')
    )
    total = cards_qs.count()
    if total == 0:
        return JsonResponse({
            'ok': True,
            'total': 0,
            'card': None,
            'index': 0,
            'session': {
                'title': session.title,
                'session_id': session.session_id,
                'session_uuid': str(session.session_uuid),
            },
        })

    if index >= total:
        index = total - 1

    card = cards_qs[index]
    ballots = card.ballots.all()

    sorted_ballots = sorted(
        ballots,
        key=lambda b: (
            getattr(b.segment, 'order', 0) or 0,
            b.segment_id or 0,
            getattr(b.candidate, 'name', '')
        )
    )
    selections = []
    for ballot in sorted_ballots:
        selections.append({
            'segment_id': ballot.segment_id,
            'segment_name': ballot.segment.name,
            'candidate_id': ballot.candidate_id,
            'candidate_name': ballot.candidate.name,
            'candidate_photo': ballot.candidate.photo.url if ballot.candidate.photo else '',
        })

    return JsonResponse({
        'ok': True,
        'index': index,
        'total': total,
        'card': {
            'card_id': str(card.card_uuid),
            'created_at': card.created_at.isoformat(),
            'selections': selections,
            'sequence': index + 1,
        },
        'session': {
            'title': session.title,
            'session_id': session.session_id,
            'session_uuid': str(session.session_uuid),
        },
    })


def voter_counts(request, session_uuid):
    # Use canonical UUID field to support pre-activation fetching
    session = get_object_or_404(VotingSession, session_uuid=session_uuid)
    verified_count = session.voters.filter(is_verified=True).count()
    finished_count = session.voters.filter(has_finished=True).count()
    total_count = session.voters.count()
    return JsonResponse({
        'verified_voters': verified_count,
        'finished_voters': finished_count,
        'total_voters': total_count
    })


@login_required
def get_voters(request, session_id=None, session_uuid=None):
    # Determine which identifier to use
    if session_uuid:
        voting_session = get_object_or_404(VotingSession, session_uuid=session_uuid)
    
    elif session_id:
        voting_session = get_object_or_404(VotingSession, session_id=session_id)
        print(session_id)
    else:
        raise Http404("Session identifier not provided.")
    
    try:
        # Use the appropriate field based on what is provided
        if session_uuid:
            voters = Voter.objects.filter(session__session_uuid=session_uuid).values(
                'voter_id', 'Fname', 'Lname', 'is_verified', 'has_finished'
            )
        elif session_id:
            voters = Voter.objects.filter(session_id=session_id).values(
                'voter_id', 'Fname', 'Lname', 'is_verified', 'has_finished'
            )
        else:
            raise Http404("No valid session identifier found.")

        return JsonResponse({'voters': list(voters)})
    except Voter.DoesNotExist:
        return JsonResponse({'error': 'No voters found for the specified session'}, status=404)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
def create_segment(request, session_id):
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        payload = {}

    session = get_object_or_404(VotingSession, pk=session_id)
    name = (payload.get('name') or '').strip() or 'New Segment'

    seg = VotingSegmentHeader.objects.create(session=session, name=name)
    # if you use an "order" field, you can initialize it here as needed

    return JsonResponse({
        'success': True,
        'segment': {'id': seg.id, 'name': seg.name}
    }, status=201)


@login_required
@require_POST
def update_segment_name(request, segment_id):
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return HttpResponseBadRequest('Invalid JSON')

    name = (payload.get('name') or '').strip()
    if not name:
        return JsonResponse({'success': False, 'error': 'Name cannot be empty'}, status=400)

    seg = get_object_or_404(VotingSegmentHeader, pk=segment_id)
    seg.name = name
    seg.save(update_fields=['name'])

    return JsonResponse({'success': True, 'segment': {'id': seg.id, 'name': seg.name}})


@login_required
def get_voter_status(request, session_uuid):
    try:
        # Fetch the VotingSession object using the canonical UUID
        session = VotingSession.objects.get(session_uuid=session_uuid)


        # Fetch the search query parameter
        search_query = request.GET.get('search', '').strip()
        filter_state = request.GET.get('filter', 'all')


        # Retrieve the associated Voters
        voters = Voter.objects.filter(session=session)

        if search_query:  # Apply search filter if query exists
            normalized_query = " ".join(search_query.split())
            voters = voters.annotate(
                full_name=Concat('Fname', Value(' '), 'Lname'),
                reverse_full_name=Concat('Lname', Value(' '), 'Fname')
            ).filter(
                Q(Fname__icontains=search_query) |
                Q(Lname__icontains=search_query) |
                Q(voter_id__icontains=search_query) |
                Q(full_name__icontains=normalized_query) |
                Q(reverse_full_name__icontains=normalized_query)
            )

        # Apply filter selection if provided
        if filter_state == 'verified':
            voters = voters.filter(is_verified=True)
        elif filter_state == 'not_verified':
            voters = voters.filter(is_verified=False)
        elif filter_state == 'verified_finished':
            voters = voters.filter(is_verified=True, has_finished=True)
        # 'all' -> no additional filtering

        # Get counts for all voters in the session
        total_voters = Voter.objects.filter(session=session).count()
        verified_voters = Voter.objects.filter(session=session, is_verified=True).count()
        finished_voters = Voter.objects.filter(session=session, has_finished=True).count()

        html = render_to_string('voters/voter_list_partial.html', {
            'voters': voters,
            'session': session
        })

        return JsonResponse({
            'html': html,
            'total_voters': total_voters,
            'verified_voters': verified_voters,
            'finished_voters': finished_voters
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

