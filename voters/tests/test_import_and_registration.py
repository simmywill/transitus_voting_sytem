from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from voters.models import VotingSession, Voter


class ImportAndSelfRegistrationTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(username="admin", password="pw")
        self.session = VotingSession.objects.create(title="Annual AGM", admin=self.admin)

    def test_csv_import_creates_unique_voters(self):
        self.client.login(username="admin", password="pw")
        csv_body = (
            "Fname,Lname,Email,Phone\n"
            "Ada,Lovelace,ada@example.com,12345\n"
            "Ada,Lovelace,ada@example.com,12345\n"  # duplicate should be skipped
        )
        upload = SimpleUploadedFile("voters.csv", csv_body.encode("utf-8"), content_type="text/csv")
        url = reverse("import_voters", args=[self.session.session_id])
        resp = self.client.post(url, {"file": upload})
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("imported"), 1)
        self.assertEqual(data.get("duplicates"), 1)
        voters = Voter.objects.filter(session=self.session)
        self.assertEqual(voters.count(), 1)
        voter = voters.first()
        self.assertEqual(voter.registration_source, Voter.SOURCE_IMPORT)
        self.assertEqual(voter.registration_status, Voter.STATUS_APPROVED)

    def test_self_registration_creates_pending_voter(self):
        url = reverse("self_register", args=[self.session.session_uuid])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(url, {
            "Fname": "Grace",
            "Lname": "Hopper",
            "email": "grace@example.com",
            "phone": "+1000000",
        })
        self.assertEqual(resp.status_code, 201, resp.content)
        voter = Voter.objects.get(session=self.session, Fname="Grace", Lname="Hopper")
        self.assertEqual(voter.registration_source, Voter.SOURCE_SELF)
        self.assertEqual(voter.registration_status, Voter.STATUS_PENDING)
        self.assertFalse(voter.is_verified)

    def test_self_registration_respects_disabled_flag(self):
        self.session.allow_self_registration = False
        self.session.save(update_fields=["allow_self_registration"])
        url = reverse("self_register", args=[self.session.session_uuid])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)
