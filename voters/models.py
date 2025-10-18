from django.db import models
from django.contrib.auth.models import User
import qrcode
from django.conf import settings
import os
from django.core.files.base import ContentFile
import uuid
from django.utils import timezone as tz

# Create your models here.


class Voter(models.Model):
    voter_id = models.AutoField(primary_key=True)
    session = models.ForeignKey('VotingSession', on_delete=models.CASCADE , related_name='voters')  # Use a string reference
    Fname = models.CharField(max_length=100)
    Lname = models.CharField(max_length=100)
    is_verified = models.BooleanField(default=False)
    has_finished = models.BooleanField(default=False)

    

    def __str__(self):
        return f"{self.Fname} {self.Lname}"


import uuid
import qrcode
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.contrib.auth.models import User
from django.utils.http import urlencode
from django.conf import settings
from io import BytesIO 

class VotingSession(models.Model):
    session_id = models.AutoField(primary_key=True)
    # New stable UUID for public entry and cross-host lookups
    session_uuid = models.UUIDField(default=uuid.uuid4, unique=True, db_index=True)
    title = models.CharField(max_length=200)
    unique_url = models.URLField(unique=True, blank=True, null=True)
    is_active = models.BooleanField(default=False)
    admin = models.ForeignKey(User, on_delete=models.CASCADE)  # session creator/admin
    qr_code = models.ImageField(upload_to='qr_codes/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    total_voters = models.IntegerField(default=0)
    current_voters = models.IntegerField(default=0)

 

    def generate_qr_code(self, request):
        """
        Ensure this session has a stable share URL tied to this record's
        UUID, and generate a QR image for that URL.
        - unique_url is derived from self.session_uuid (stable), not a random UUID.
        - Always (re)generate the QR if requested by the caller.
        """
        protocol = 'https' if request.is_secure() else 'http'
        host = request.get_host()

        # Stable per-session URL using the canonical UUID for this session
        self.unique_url = f'{protocol}://{host}/voter_session/verify/{self.session_uuid}'
        print(f"Generated/updated unique URL: {self.unique_url}")
        self.save(update_fields=['unique_url'])

        # Generate QR code for the unique URL
        qr_image = qrcode.make(self.unique_url)

        qr_io = BytesIO()
        qr_image.save(qr_io, format='PNG')
        qr_io.seek(0)

        # Save the QR code image
        self.qr_code.save(f'qr_code_{self.session_id}.png', ContentFile(qr_io.read()), save=False)
        self.save(update_fields=['qr_code'])

    def get_uuid(self):
        # Expose the canonical UUID for this session
        return str(self.session_uuid)

    def ensure_qr_file(self):
        """
        If a unique_url exists but the QR image file is missing on disk or not set,
        regenerate the QR image without touching the unique_url.
        """
        if not self.unique_url:
            return
        try:
            # If file path exists and is present on disk, nothing to do
            if getattr(self, 'qr_code', None) and getattr(self.qr_code, 'path', None):
                if os.path.exists(self.qr_code.path):
                    return
        except Exception:
            pass

        # Recreate the QR image for the existing unique_url
        qr_image = qrcode.make(self.unique_url)
        qr_io = BytesIO()
        qr_image.save(qr_io, format='PNG')
        qr_io.seek(0)
        self.qr_code.save(f'qr_code_{self.session_id}.png', ContentFile(qr_io.read()), save=False)
        self.save(update_fields=['qr_code'])


    def __str__(self):
        return self.title


class VotingSegmentHeader(models.Model):
    session = models.ForeignKey(VotingSession, on_delete=models.CASCADE, related_name='segments')
    name = models.CharField(max_length=255)  # Name of the segment header, e.g., "President", "Treasurer"
    order = models.IntegerField(default=0)  # Field to store order

    class Meta:
        ordering = ['order']  # Ensures segments are returned in the specified order
    
    def __str__(self):
        return self.name

class Candidate(models.Model):
    name = models.CharField(max_length=255)
    photo = models.ImageField(upload_to='candidate_photos/', blank=True, null=True)
    voting_session = models.ForeignKey(VotingSession, on_delete=models.CASCADE)
    segment_header = models.ForeignKey(VotingSegmentHeader, on_delete=models.CASCADE, related_name='candidates')
    total_votes = models.IntegerField(default=0)

    
    def __str__(self):
        return self.name


class Vote(models.Model):
    voter = models.ForeignKey(Voter, on_delete=models.CASCADE)
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE)
    segment = models.ForeignKey(VotingSegmentHeader, on_delete=models.CASCADE)


# Anonymous handoff & ballot recording models
class AnonSession(models.Model):
    anon_id = models.CharField(max_length=64, primary_key=True)
    session = models.ForeignKey(VotingSession, on_delete=models.CASCADE)
    voter = models.ForeignKey('Voter', on_delete=models.SET_NULL, null=True, blank=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    spent_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_spent(self):
        return self.spent_at is not None


class RedirectCode(models.Model):
    code = models.CharField(max_length=64, primary_key=True)
    anon = models.ForeignKey(AnonSession, on_delete=models.CASCADE)
    session = models.ForeignKey(VotingSession, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    redeemed_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)


class Ballot(models.Model):
    ballot_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(VotingSession, on_delete=models.CASCADE, db_index=True)
    segment = models.ForeignKey('VotingSegmentHeader', on_delete=models.CASCADE, db_index=True)
    candidate = models.ForeignKey('Candidate', on_delete=models.CASCADE, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['session', 'segment'])]


class EventLog(models.Model):
    session = models.ForeignKey(VotingSession, on_delete=models.CASCADE)
    event_type = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    prev_hash = models.CharField(max_length=64, null=True, blank=True)
    this_hash = models.CharField(max_length=64, db_index=True)


def log_event(session, event_type, payload):
    from .models import EventLog as _EventLog  # local import to avoid cycles
    import hashlib, json
    last = _EventLog.objects.filter(session=session).order_by('-id').first()
    prev_hash = last.this_hash if last else ''
    body = json.dumps({
        'prev_hash': prev_hash,
        'event_type': event_type,
        'payload': payload,
    }, sort_keys=True)
    this_hash = hashlib.sha256(body.encode('utf-8')).hexdigest()
    return _EventLog.objects.create(
        session=session,
        event_type=event_type,
        payload=payload,
        prev_hash=prev_hash,
        this_hash=this_hash,
    )
