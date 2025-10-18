import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model


class Command(BaseCommand):
    help = "Ensure an admin (superuser) exists based on env vars. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument(
            "--update-password",
            action="store_true",
            help="Update password if user exists and env password is set.",
        )

    def handle(self, *args, **options):
        username = os.getenv("DJANGO_SUPERUSER_USERNAME")
        email = os.getenv("DJANGO_SUPERUSER_EMAIL")
        password = os.getenv("DJANGO_SUPERUSER_PASSWORD")
        update_flag = options.get("update_password") or os.getenv("DJANGO_SUPERUSER_UPDATE_PASSWORD", "").lower() in ("1", "true", "yes")

        if not username:
            self.stdout.write("[ensure_admin] DJANGO_SUPERUSER_USERNAME not set; skipping.")
            return

        User = get_user_model()
        user = User.objects.filter(username=username).first()

        if user is None:
            if not password:
                self.stdout.write("[ensure_admin] No password provided for new user; set DJANGO_SUPERUSER_PASSWORD.")
                return
            # Create new superuser
            user = User(username=username, email=email or "")
            user.is_staff = True
            user.is_superuser = True
            user.set_password(password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f"[ensure_admin] Created superuser '{username}'."))
            return

        # User exists: optionally update email/password
        updates = []
        if email is not None and user.email != email:
            user.email = email
            updates.append("email")

        if update_flag and password:
            user.set_password(password)
            updates.append("password")

        changed = False
        if not user.is_staff:
            user.is_staff = True
            updates.append("is_staff")
        if not user.is_superuser:
            user.is_superuser = True
            updates.append("is_superuser")

        if updates:
            user.save()
            changed = True

        if changed:
            self.stdout.write(self.style.SUCCESS(f"[ensure_admin] Updated {', '.join(updates)} for '{username}'."))
        else:
            self.stdout.write(f"[ensure_admin] Superuser '{username}' already up-to-date.")

