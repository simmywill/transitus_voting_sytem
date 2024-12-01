from django.db import models
from django.contrib.auth.models import User
import qrcode
from django.conf import settings
import os
from django.core.files.base import ContentFile

# Create your models here.


class Voter(models.Model):
    voter_id = models.AutoField(primary_key=True)
    session = models.ForeignKey('VotingSession', on_delete=models.CASCADE)  # Use a string reference
    Fname = models.CharField(max_length=100)
    Lname = models.CharField(max_length=100)

    

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
        protocol = 'https' if request.is_secure() else 'http'
        # Get the host dynamically from the request
        host = request.get_host()
        

        # Generate the unique URL
        self.unique_url = f'{protocol}://{host}/voter_session/verify/{uuid.uuid4()}'
        print(f"Generated unique URL: {self.unique_url}")
        self.save()
        


        # Generate QR code for the unique URL
        qr_image = qrcode.make(self.unique_url)

        qr_io = BytesIO()
        qr_image.save(qr_io, format='PNG')
        qr_io.seek(0)

        # Save the QR code image
        self.qr_code.save(f'qr_code_{self.session_id}.png', ContentFile(qr_io.read()), save=False)
        self.save()


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
    photo = models.ImageField(upload_to='candidate_photos/')
    voting_session = models.ForeignKey(VotingSession, on_delete=models.CASCADE)
    segment_header = models.ForeignKey(VotingSegmentHeader, on_delete=models.CASCADE, related_name='candidates')
    
    def __str__(self):
        return self.name


class Vote(models.Model):
    voter = models.ForeignKey(Voter, on_delete=models.CASCADE)
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE)
    segment = models.ForeignKey(VotingSegmentHeader, on_delete=models.CASCADE)
