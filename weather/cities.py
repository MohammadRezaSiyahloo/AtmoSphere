"""Saved-city storage shared by the existing weather views."""

from django.db import transaction

from .models import City


GUEST_CITIES_KEY = 'guest_cities'


def get_saved_cities(request):
    if request.user.is_authenticated:
        return list(City.objects.filter(user=request.user).values_list('name', flat=True))
    return request.session.get(GUEST_CITIES_KEY, [])


def save_city(request, name):
    if request.user.is_authenticated:
        City.objects.get_or_create(user=request.user, name=name)
    else:
        cities = get_saved_cities(request)
        if name not in cities:
            # Assign a new list so Django marks the session as modified.
            request.session[GUEST_CITIES_KEY] = [name] + cities


def delete_city(request, name):
    if request.user.is_authenticated:
        City.objects.filter(user=request.user, name=name).delete()
    else:
        request.session[GUEST_CITIES_KEY] = [
            city for city in get_saved_cities(request) if city != name
        ]


def get_storage_key(request):
    if request.user.is_authenticated:
        return request.user.id
    # Keep guests' weather cache and refresh budgets separate from each other.
    if not request.session.session_key:
        request.session.create()
    return f'guest_{request.session.session_key}'


def migrate_guest_cities(request, user):
    if GUEST_CITIES_KEY not in request.session:
        return
    cities = request.session.get(GUEST_CITIES_KEY, [])
    # Commit all city writes before clearing the guest list; failures retain it.
    with transaction.atomic():
        for name in reversed(cities):
            City.objects.get_or_create(user=user, name=name)
    request.session.pop(GUEST_CITIES_KEY, None)
