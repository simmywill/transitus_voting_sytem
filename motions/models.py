from django.db import models
from django.utils import timezone as tz


class Motion(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_OPEN = "open"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_OPEN, "Open"),
        (STATUS_CLOSED, "Closed"),
    ]

    event = models.ForeignKey(
        "voters.VotingSession",
        on_delete=models.CASCADE,
        related_name="motions",
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    display_order = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        db_index=True,
    )
    allow_vote_change = models.BooleanField(default=True)
    reveal_results = models.BooleanField(default=False)
    auto_close_seconds = models.PositiveIntegerField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "display_order"], name="uniq_motion_order_per_event"
            ),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        """
        Ensure display_order stays unique per event by auto-appending new motions
        to the end when no order was provided.
        """
        if self.display_order == 0 and self.event_id:
            existing_max = (
                Motion.objects.filter(event_id=self.event_id)
                .exclude(pk=self.pk)
                .order_by("-display_order")
                .values_list("display_order", flat=True)
                .first()
                or 0
            )
            self.display_order = existing_max + 1
        super().save(*args, **kwargs)

    @property
    def is_open(self):
        return self.status == self.STATUS_OPEN

    @property
    def is_closed(self):
        return self.status == self.STATUS_CLOSED

    def mark_open(self):
        self.status = self.STATUS_OPEN
        self.opened_at = tz.now()
        self.save(update_fields=["status", "opened_at", "updated_at"])

    def mark_closed(self):
        self.status = self.STATUS_CLOSED
        now = tz.now()
        self.closed_at = now
        self.save(update_fields=["status", "closed_at", "updated_at"])


class MotionVote(models.Model):
    CHOICE_YES = "yes"
    CHOICE_NO = "no"
    CHOICE_ABSTAIN = "abstain"
    CHOICES = [
        (CHOICE_YES, "Yes"),
        (CHOICE_NO, "No"),
        (CHOICE_ABSTAIN, "Abstain"),
    ]

    motion = models.ForeignKey(
        Motion, on_delete=models.CASCADE, related_name="votes", db_index=True
    )
    voter_id = models.CharField(max_length=128, db_index=True)
    choice = models.CharField(max_length=12, choices=CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["motion", "voter_id"], name="uniq_vote_per_motion_voter"
            ),
        ]
        indexes = [
            models.Index(fields=["motion", "choice"]),
        ]

    def __str__(self):
        return f"{self.voter_id} -> {self.choice} on {self.motion_id}"
