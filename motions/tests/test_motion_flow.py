from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from motions.models import Motion
from motions.presence import PresenceTracker
from motions.services import open_motion, record_vote
from voters.models import VotingSession


class MotionFlowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="admin", password="pass", is_staff=True)
        self.session = VotingSession.objects.create(
            title="AGM",
            admin=self.admin,
            is_active=True,
            unique_url="http://example.com",
        )

    def test_only_one_motion_open(self):
        m1 = Motion.objects.create(event=self.session, title="One", status=Motion.STATUS_DRAFT)
        m2 = Motion.objects.create(event=self.session, title="Two", status=Motion.STATUS_DRAFT)
        open_motion(m1)
        open_motion(m2)
        m1.refresh_from_db()
        m2.refresh_from_db()
        self.assertTrue(m2.is_open)
        self.assertTrue(m1.is_closed)

    def test_vote_unique_and_change_behavior(self):
        motion = Motion.objects.create(
            event=self.session,
            title="Budget",
            status=Motion.STATUS_OPEN,
            allow_vote_change=True,
        )
        ok, data = record_vote(motion, "v1", "yes")
        self.assertTrue(ok)
        self.assertTrue(data["created"])
        ok, data = record_vote(motion, "v1", "no")
        self.assertTrue(ok)
        self.assertTrue(data["changed"])
        motion.allow_vote_change = False
        motion.save()
        ok, data = record_vote(motion, "v1", "abstain")
        self.assertFalse(ok)
        self.assertEqual(data["error"], "vote_locked")

    def test_close_motion_blocks_vote(self):
        motion = Motion.objects.create(
            event=self.session,
            title="Close me",
            status=Motion.STATUS_CLOSED,
        )
        ok, data = record_vote(motion, "v1", "yes")
        self.assertFalse(ok)
        self.assertEqual(data["error"], "motion_closed")

    def test_gated_entry_preserves_identity(self):
        client = Client()
        session = client.session
        session["ANON_ID"] = "abc"
        session["ANON_SESSION_UUID"] = str(self.session.session_uuid)
        session.save()

        resp = client.get(reverse("motions:gated_entry", args=[self.session.session_uuid]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(client.session.get("ANON_ID"), "abc")
        tokens = client.session.get("MOTION_ANON_IDS") or {}
        self.assertNotIn(str(self.session.session_uuid), tokens)

    def test_gated_entry_auto_provisions_motion_identity(self):
        client = Client()
        resp = client.get(reverse("motions:gated_entry", args=[self.session.session_uuid]))
        self.assertEqual(resp.status_code, 200)
        tokens = client.session.get("MOTION_ANON_IDS") or {}
        self.assertIn(str(self.session.session_uuid), tokens)
        self.assertTrue(tokens.get(str(self.session.session_uuid)))

    def test_presence_tracker(self):
        tracker = PresenceTracker()
        count = tracker.heartbeat(self.session.id, "voter-1")
        self.assertEqual(count, 1)
        tracker.mark_gone(self.session.id, "voter-1")
        self.assertEqual(tracker.count(self.session.id), 0)
