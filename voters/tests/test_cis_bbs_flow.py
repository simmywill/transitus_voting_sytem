from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone as tz
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
import json, hmac, hashlib

from voters.models import (
    VotingSession,
    Voter,
    VotingSegmentHeader,
    Candidate,
    AnonSession,
    RedirectCode,
    ManualCheckCard,
)


@override_settings(CIS_ENFORCE_HOST=False)
class AnonFlowTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.admin = User.objects.create_user(username="admin", password="pw")
        self.session = VotingSession.objects.create(title="Test Session", admin=self.admin, is_active=True)
        self.segment = VotingSegmentHeader.objects.create(session=self.session, name="Chair", order=1)
        blob = b"GIF87a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        self.cand1 = Candidate.objects.create(
            name="Alice",
            voting_session=self.session,
            segment_header=self.segment,
            photo=ContentFile(blob, name="dot1.gif")
        )
        self.cand2 = Candidate.objects.create(
            name="Bob",
            voting_session=self.session,
            segment_header=self.segment,
            photo=ContentFile(blob, name="dot2.gif")
        )
        self.voter = Voter.objects.create(session=self.session, Fname="John", Lname="Doe")

    def _hmac(self, body: bytes) -> str:
        from django.conf import settings
        return hmac.new(settings.CIS_BBS_SHARED_SECRET.encode(), body, hashlib.sha256).hexdigest()

    def test_cis_redeem_hmac_accepts_and_sets_flags(self):
        # Prepare handoff
        anon = AnonSession.objects.create(anon_id="anon-1", session=self.session, voter=self.voter,
                                          expires_at=tz.now() + tz.timedelta(hours=1))
        rc = RedirectCode.objects.create(code="code-1", anon=anon, session=self.session,
                                         expires_at=tz.now() + tz.timedelta(minutes=10))

        body = json.dumps({"redirect_code": rc.code, "session_uuid": str(self.session.session_uuid)}).encode()
        sig = self._hmac(body)

        url = reverse('cis_api_redeem')
        resp = self.client.post(url, data=body, content_type='application/json', HTTP_X_CIS_SIGNATURE=sig)
        self.assertEqual(resp.status_code, 200, resp.content)
        data = resp.json()
        self.assertTrue(data.get('ok'))
        self.assertEqual(data.get('anon_id'), anon.anon_id)

        # Confirm redeemed and activated flags
        rc.refresh_from_db()
        anon.refresh_from_db()
        self.assertIsNotNone(rc.redeemed_at)
        self.assertIsNotNone(anon.activated_at)

    def test_cis_redeem_rejects_bad_sig(self):
        anon = AnonSession.objects.create(anon_id="anon-2", session=self.session,
                                          expires_at=tz.now() + tz.timedelta(hours=1))
        rc = RedirectCode.objects.create(code="code-2", anon=anon, session=self.session)

        body = json.dumps({"redirect_code": rc.code, "session_uuid": str(self.session.session_uuid)}).encode()
        # Deliberately wrong signature
        url = reverse('cis_api_redeem')
        resp = self.client.post(url, data=body, content_type='application/json', HTTP_X_CIS_SIGNATURE='bad')
        self.assertEqual(resp.status_code, 403)

    def test_bbs_cast_marks_spent_via_cis(self):
        # Prepare anon session which ballot_entry would normally set into session
        anon = AnonSession.objects.create(anon_id="anon-3", session=self.session, voter=self.voter,
                                          activated_at=tz.now())

        # Prime client session with anon context
        s = self.client.session
        s['ANON_ID'] = anon.anon_id
        s['ANON_SESSION_UUID'] = str(self.session.session_uuid)
        s.save()

        # Monkeypatch requests.post used by _cis_call in bbs_views to hit our Django view directly
        from voters import bbs_views
        orig_post = bbs_views.requests.post

        def fake_requests_post(url, data, headers, timeout):
            # Extract path and dispatch to Django client to exercise real CSRF-exempt + HMAC code
            from urllib.parse import urlparse
            parsed = urlparse(url)
            path = parsed.path
            # Forward the request with signature header
            r = self.client.post(path, data=data, content_type='application/json',
                                 HTTP_X_CIS_SIGNATURE=headers.get('X-CIS-Signature', ''))
            class R:
                status_code = r.status_code
                def json(self_inner):
                    return json.loads(r.content.decode() or '{}')
            return R()

        bbs_views.requests.post = fake_requests_post
        try:
            payload = {
                "session_uuid": str(self.session.session_uuid),
                "choices": [[self.segment.id, self.cand1.id]],
            }
            # Obtain a CSRF cookie by visiting a page that renders {% csrf_token %}
            self.client.get(reverse('cis_verify_form', args=[self.session.session_uuid]))
            csrftoken = self.client.cookies.get('csrftoken').value
            resp = self.client.post(
                reverse('bbs_api_cast'),
                data=json.dumps(payload),
                content_type='application/json',
                HTTP_X_CSRFTOKEN=csrftoken
            )
            self.assertEqual(resp.status_code, 200, resp.content)
            data = resp.json()
            self.assertTrue(data.get('ok'))
            cards = ManualCheckCard.objects.filter(session=self.session)
            self.assertEqual(cards.count(), 1)
            card = cards.first()
            self.assertEqual(card.ballots.count(), len(payload['choices']))

            # Verify anon marked spent and voter flag flipped
            anon.refresh_from_db()
            self.voter.refresh_from_db()
            self.assertIsNotNone(anon.spent_at)
            self.assertTrue(self.voter.has_finished)
        finally:
            bbs_views.requests.post = orig_post

    def test_ballot_entry_redirects_after_redeem(self):
        # Prepare code ready for redeem via ballot_entry
        anon = AnonSession.objects.create(
            anon_id="anon-4",
            session=self.session,
            voter=self.voter,
            expires_at=tz.now() + tz.timedelta(hours=1)
        )
        rc = RedirectCode.objects.create(
            code="code-redirect",
            anon=anon,
            session=self.session,
            expires_at=tz.now() + tz.timedelta(minutes=10)
        )

        from voters import bbs_views
        orig_post = bbs_views.requests.post

        def fake_requests_post(url, data, headers, timeout):
            from urllib.parse import urlparse
            parsed = urlparse(url)
            path = parsed.path
            response = self.client.post(
                path,
                data=data,
                content_type='application/json',
                HTTP_X_CIS_SIGNATURE=headers.get('X-CIS-Signature', '')
            )

            class R:
                status_code = response.status_code

                def json(self_inner):
                    return json.loads(response.content.decode() or '{}')

            return R()

        bbs_views.requests.post = fake_requests_post
        try:
            url = f"{reverse('bbs_ballot_entry', args=[self.session.session_uuid])}?handoff={rc.code}"
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302)
            self.assertEqual(resp['Location'], reverse('bbs_ballot_entry', args=[self.session.session_uuid]))

            # Session should now carry anon context and redeem should be marked
            session_data = self.client.session
            self.assertEqual(session_data.get('ANON_ID'), anon.anon_id)
            self.assertEqual(session_data.get('ANON_SESSION_UUID'), str(self.session.session_uuid))

            rc.refresh_from_db()
            self.assertIsNotNone(rc.redeemed_at)

            follow = self.client.get(resp['Location'])
            self.assertEqual(follow.status_code, 200)
        finally:
            bbs_views.requests.post = orig_post
