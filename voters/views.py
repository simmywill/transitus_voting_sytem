from django.shortcuts import render, redirect
from .models import VotingSession, Voter, Candidate, VotingSegmentHeader  # Import the Voter model
from .forms import VoterForm , VotingSessionForm
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
import logging
from django.db.models import Q
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect, get_object_or_404
import json
from django.urls import reverse



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
            return render(request, "landing_page.html")

        # Ensure password was submitted
        if not password:
            messages.error(request, "Must provide password")
            return render(request, "landing_page.html")

        # Authenticate user
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)  # Log in the user
            return redirect( "/admin_main_page")  # Redirect to admin main page
        else:
            messages.error(request, "Invalid username and/or password")
    
    return render(request, "voters/landing_page.html")  # Render login form if GET request


@login_required
def admin_main_page(request):
    return render(request, "voters/admin_main_page.html")


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
    return render(request, 'voters/create_session.html', {'form': form})



@login_required
def manage_session(request, session_id):
    # Fetch the session and its related data (if any) for display purposes
    session = get_object_or_404(VotingSession, session_id=session_id, admin=request.user)
    
    # Retrieve any existing segments and candidates associated with this session
    segments = VotingSegmentHeader.objects.filter(session=session).prefetch_related('candidate_set')
    
    return render(request, 'voters/manage_session.html', {
        'session': session,
        'segments': segments,
    })
    

@login_required
def add_segments(request, session_id):
    if request.method == 'POST':
        session = get_object_or_404(VotingSession, session_id=session_id, admin=request.user)
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
        return redirect('active_voting_session', session_id=session_id)



def active_voting_session(request, session_id):
    # Retrieve the voting session with the given ID
    session = get_object_or_404(VotingSession, session_id=session_id)

    # Retrieve all segments and their candidates associated with this session
    segments = VotingSegmentHeader.objects.filter(session=session).prefetch_related('candidates')

    context = {
        'session': session,
        'segments': segments,
    }
    return render(request, 'voters/voting_session.html', context)


@login_required
def list_voting_sessions(request):
    sessions = VotingSession.objects.filter(admin=request.user)  # Admin's own sessions
    return render(request, 'voters/list_sessions.html', {'sessions': sessions})

def delete_voting_session(request, session_id):
    session = VotingSession.objects.get(session_id=session_id)

    if request.method == 'POST':
        if 'confirm' in request.POST:  # User confirmed deletion
            session.delete()
            messages.success(request, f'Successfully deleted the session "{session.title}".')
            return redirect('list_voting_sessions')
        elif 'cancel' in request.POST:  # User canceled deletion
            messages.info(request, f'Deletion of session "{session.title}" was canceled.')
            return redirect('list_voting_sessions')

    return render(request, 'voters/delete_session.html', {'session': session})


def add_voters(request, session_id=None, session_uuid=None):
    # Determine which identifier to use
    if session_uuid:
        voting_session = get_object_or_404(VotingSession, unique_url__contains=f'{session_uuid}')
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
            if session_uuid:
                return redirect('voter_list', session_uuid=session_uuid)
            return redirect('voter_list', session_id=session_id)
    else:
        form = VoterForm()

    return render(
        request,
        "voters/create_voter.html",
        {
            'form': form,
            'session_id': session_id,
            'session_uuid': session_uuid,
            'session': voting_session,
        },
    )



@login_required
def voter_list(request, session_id=None, session_uuid=None):
    # Determine which identifier to use
    if session_uuid:
        voting_session = get_object_or_404(VotingSession, unique_url__contains=f'{session_uuid}')
    elif session_id:
        voting_session = get_object_or_404(VotingSession, session_id=session_id)
    else:
        raise Http404("Session identifier not provided.")

    search_query = request.GET.get('search', '')

    # Filter voters based on the associated session
    if search_query:
        voters = Voter.objects.filter(
            session=voting_session
        ).filter(
            Q(Fname__icontains=search_query) |
            Q(Lname__icontains=search_query) |
            Q(voter_id__icontains=search_query)
        )
    else:
        voters = Voter.objects.filter(session=voting_session)

    return render(
        request,
        'voters/voter_list.html',
        {
            'voters': voters,
            'voting_session': voting_session,
            'session_uuid': session_uuid,
            'session_id': session_id,
        },
    )



@login_required
def delete_voter(request, voter_id):

    session_uuid = request.GET.get('session_uuid')
    session_id = request.GET.get('session_id')


    if session_uuid:
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


@csrf_exempt
def delete_candidate(request, candidate_id):
    if request.method == 'POST':
        candidate = get_object_or_404(Candidate, id=candidate_id)
        candidate.delete()
        return JsonResponse({'success': True})  # Respond with success status
    return JsonResponse({'success': False, 'error': 'Invalid request method'}, status=400)

@csrf_exempt
def update_segment_order(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        segment_order = data.get('order', [])
        
        # Update each segment with the new order
        for order, segment_id in enumerate(segment_order):
            VotingSegmentHeader.objects.filter(id=segment_id).update(order=order)
        
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'failed'}, status=400)


@csrf_exempt
def update_segment(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        segment_id = data['segment_id']
        new_name = data['new_name']
        segment = VotingSegment.objects.get(id=segment_id)
        segment.name = new_name
        segment.save()
        return JsonResponse({'status': 'success'})
    return JsonResponse({'status': 'failed'}, status=400)

def delete_segment(request, segment_id):
    if request.method == 'POST':
        segment = get_object_or_404(VotingSegmentHeader, id=segment_id)
        segment.delete()
        return JsonResponse({'success': True})
    return JsonResponse({'error': 'Invalid request'}, status=400)


def activate_session(request, session_id):
    # Retrieve the session by its ID
    session = VotingSession.objects.get(session_id=session_id)

    # Generate the unique URL for the session (if not already done)
    if not session.unique_url:
        session.generate_qr_code(request)
        session.save()

    # Activate the session
    session.is_active = True
    session.save()

    return redirect('list_voting_sessions')


def voter_verification(request, session_uuid):
    # Retrieve the voting session based on the unique session UUID
    session = get_object_or_404(VotingSession, unique_url__contains=f'{session_uuid}')
    
    # Ensure the session is active and not closed
    if not session.is_active:
        raise Http404("This session is not active.")
    
    if request.method == 'POST':
        # Verify the name entered by the voter
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')

        # Check if the voter exists in the session
        voter = session.voters.filter(Fname=first_name, Lname=last_name).first()
        
        # Check if the name is valid
        if voter:
            # Save voter ID in session and redirect
            request.session['voter_id'] = voter.voter_id
            return redirect('voter_session', session_uuid=session_uuid)
        
        # If name is not valid, show an error message
        else:
            return render(request, 'voters/voter_verification.html', {
                'session': session,
                'session_uuid': session_uuid,
                'error_message': 'Please enter a valid name.'
            })
    
    # Render the verification page with a form
    return render(request, 'voters/voter_verification.html', {
        'session': session
    })


def voter_session(request, session_uuid):
    # Retrieve the voting session based on the unique session UUID
    session = get_object_or_404(VotingSession, unique_url__contains=f'{session_uuid}')
    
    # Check if the voter is verified
    voter_id = request.session.get('voter_id')
    if not voter_id:
        return redirect('voter_verification', session_uuid=session_uuid)
    
     # Verify the voter exists and belongs to the session
    voter = session.voters.filter(voter_id=voter_id).first()
    if not voter:
        del request.session['voter_id']  # Clear invalid voter_id
        return redirect('voter_verification', session_uuid=session_uuid)
    
    # Retrieve the segments in order
    segments = session.segments.order_by('order')
    current_segment = int(request.GET.get('segment', 0))
    remaining_segments = len(segments) - 1  # Precompute the subtraction
    
    # Display the current segment or redirect if voting is complete
    if current_segment < len(segments):
        segment = segments[current_segment]
        return render(
            request,
            'voters/voting_page.html',
            {
                'segment': segments,
                'current_segment': current_segment,
                'total_segments': len(segments),
                'remaining_segments': remaining_segments,
                'session_uuid': session_uuid  # Pass session_uuid for navigation
            }
        )
    else:
        # Voting completed
        return redirect('thank_you', session_uuid=session_uuid)



def submit_vote(request, session_uuid):
    # Retrieve the session based on the unique UUID
    session = get_object_or_404(VotingSession, unique_url__contains=f'{session_uuid}')
    
    voter_id = request.session.get('voter_id')
    if request.method == 'POST':
        candidate_id = request.POST.get('candidate')
        segment_id = request.POST.get('segment')

        # Save the vote in the database
        Vote.objects.create(
            voter_id=voter_id,
            candidate_id=candidate_id,
            segment_id=segment_id
        )
    
    # Redirect to the next voting page using session_uuid
    current_segment = int(request.GET.get('segment', 0))
    return redirect('voter_session', session_uuid=session_uuid, segment=current_segment + 1)


from django.db.models import Count

def tally_votes(request, session_uuid):
    # Retrieve the session based on the unique UUID
    session = get_object_or_404(VotingSession, unique_url__contains=f'{session_uuid}')
    segments = session.votingsegmentheader_set.all()

    # Calculate the vote tallies
    tally = {}
    for segment in segments:
        tally[segment.name] = segment.candidate_set.annotate(vote_count=Count('vote'))

    # Render the tally page
    return render(request, 'tally_votes.html', {'tally': tally, 'session': session})

