from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .cities import migrate_guest_cities


@receiver(user_logged_in, dispatch_uid='weather.migrate_guest_cities')
def transfer_guest_cities(sender, request, user, **kwargs):
    # Both LoginView and registration's login() emit this signal.
    if request is not None:
        migrate_guest_cities(request, user)
