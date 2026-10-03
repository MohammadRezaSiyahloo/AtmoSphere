from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import IntegrityError
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from .cities import migrate_guest_cities
from .models import City


class SavedCityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username='weather-user', password='test-password')
        self.api = patch('weather.views.get_api_response').start()
        self.api.return_value = Mock(status_code=200)
        self.weather = patch('weather.views.fetch_city_weather').start()
        self.weather.side_effect = lambda city, *args: {
            'city': city, 'icon': 'sun.png', 'weather': 'Clear',
        }
        self.addCleanup(patch.stopall)
        self.addCleanup(cache.clear)

    def set_guest_cities(self, cities, client=None):
        session = (client or self.client).session
        session['guest_cities'] = cities
        session.save()

    def test_guest_can_open_dashboard(self):
        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['cities'], [])
        self.assertContains(response, 'Guest locations')

    def test_guest_mutations_still_require_csrf_tokens(self):
        client = Client(enforce_csrf_checks=True)
        for endpoint, payload in [
            ('add', {'city': 'London'}),
            ('delete', {'city_name': 'London'}),
            ('geolocate', {'lat': '52.37', 'lon': '4.90'}),
        ]:
            with self.subTest(endpoint=endpoint):
                self.assertEqual(client.post(reverse(endpoint), payload).status_code, 403)
        self.api.assert_not_called()
        self.assertFalse(City.objects.exists())

    def test_delete_and_geolocation_still_require_post(self):
        self.set_guest_cities(['London'])
        for endpoint in ['delete', 'geolocate']:
            self.assertEqual(self.client.get(reverse(endpoint)).status_code, 405)
        self.assertEqual(self.client.session['guest_cities'], ['London'])

    def test_guest_saves_names_once_in_session_without_city_rows(self):
        for name in ['London', 'Tokyo', 'London']:
            self.assertRedirects(
                self.client.post(reverse('add'), {'city': name}),
                reverse('index'), fetch_redirect_response=False,
            )
        self.assertEqual(self.client.session['guest_cities'], ['Tokyo', 'London'])
        self.assertFalse(City.objects.exists())

    def test_guest_views_saved_cities_across_requests(self):
        self.client.post(reverse('add'), {'city': 'London'})
        for _ in range(2):
            response = self.client.get(reverse('index'))
            self.assertEqual([city['city'] for city in response.context['cities']], ['London'])
            self.assertContains(response, 'London')
        self.assertEqual(self.weather.call_count, 1)

    def test_guest_removes_city_and_its_cache(self):
        self.set_guest_cities(['Tokyo', 'London'])
        self.client.get(reverse('index'))
        key = f'weather_guest_{self.client.session.session_key}_London'
        self.assertIsNotNone(cache.get(key))
        self.client.post(reverse('delete'), {'city_name': 'London'})
        self.assertEqual(self.client.session['guest_cities'], ['Tokyo'])
        self.assertIsNone(cache.get(key))
        self.client.post(reverse('delete'), {'city_name': 'Missing'})
        self.assertEqual(self.client.session['guest_cities'], ['Tokyo'])

    def test_invalid_city_does_not_save_for_guest_or_account(self):
        for authenticated in [False, True]:
            if authenticated:
                self.client.force_login(self.user)
            for payload in [{'city': ''}, {'city': 'x' * 101}]:
                self.client.post(reverse('add'), payload)
            self.api.return_value = None
            self.client.post(reverse('add'), {'city': 'Unknown'})
            self.assertNotIn('guest_cities', self.client.session)
            self.assertFalse(City.objects.exists())

    def test_guests_have_separate_city_lists_caches_and_refresh_budgets(self):
        other = Client()
        self.set_guest_cities(['London'])
        self.set_guest_cities(['London'], other)
        self.client.get(reverse('index'), {'refresh': 'London'})
        other.get(reverse('index'), {'refresh': 'London'})
        first_key = self.client.session.session_key
        second_key = other.session.session_key
        self.assertNotEqual(first_key, second_key)
        self.assertEqual(cache.get(f'rate_guest_{first_key}')['count'], 1)
        self.assertEqual(cache.get(f'rate_guest_{second_key}')['count'], 1)
        self.assertIsNotNone(cache.get(f'weather_guest_{first_key}_London'))
        self.assertIsNotNone(cache.get(f'weather_guest_{second_key}_London'))
        self.client.post(reverse('delete'), {'city_name': 'London'})
        self.assertEqual(other.session['guest_cities'], ['London'])
        self.assertIsNotNone(cache.get(f'weather_guest_{second_key}_London'))

    def test_geolocation_saves_to_the_correct_storage(self):
        self.api.return_value.json.return_value = {'name': 'Amsterdam'}
        self.client.post(reverse('geolocate'), {'lat': '52.37', 'lon': '4.90'})
        self.assertEqual(self.client.session['guest_cities'], ['Amsterdam'])
        self.assertFalse(City.objects.exists())
        self.client.force_login(self.user)
        self.api.return_value.json.return_value = {'name': 'Tokyo'}
        self.client.post(reverse('geolocate'), {'lat': '35.68', 'lon': '139.69'})
        self.assertTrue(City.objects.filter(user=self.user, name='Tokyo').exists())
        self.assertNotIn('guest_cities', self.client.session)

    def test_account_still_uses_database_ordering_cache_and_delete(self):
        self.client.force_login(self.user)
        other_user = User.objects.create_user(username='other')
        other_city = City.objects.create(user=other_user, name='London')
        for name in ['London', 'Tokyo', 'London']:
            self.client.post(reverse('add'), {'city': name})
        self.assertEqual(list(self.user.cities.values_list('name', flat=True)), ['Tokyo', 'London'])
        self.assertNotIn('guest_cities', self.client.session)
        response = self.client.get(reverse('index'), {'refresh': 'London'})
        self.assertEqual([city['city'] for city in response.context['cities']], ['Tokyo', 'London'])
        key = f'weather_{self.user.id}_London'
        self.assertIsNotNone(cache.get(key))
        self.assertEqual(cache.get(f'rate_{self.user.id}')['count'], 1)
        self.assertNotContains(response, 'Guest locations')
        self.client.post(reverse('delete'), {'city_name': 'London'})
        self.assertFalse(self.user.cities.filter(name='London').exists())
        self.assertTrue(City.objects.filter(pk=other_city.pk).exists())
        self.assertIsNone(cache.get(key))

    def test_login_migrates_without_duplicates_and_clears_session(self):
        City.objects.create(user=self.user, name='London')
        self.set_guest_cities(['Tokyo', 'London', 'Tokyo'])
        session = self.client.session
        session['unrelated'] = 'preserved'
        session.save()
        response = self.client.post(reverse('login'), {
            'username': self.user.username, 'password': 'test-password',
        })
        self.assertRedirects(response, reverse('index'), fetch_redirect_response=False)
        self.assertCountEqual(self.user.cities.values_list('name', flat=True), ['Tokyo', 'London'])
        self.assertNotIn('guest_cities', self.client.session)
        self.assertEqual(self.client.session['unrelated'], 'preserved')
        self.client.get(reverse('index'))
        self.assertEqual(self.user.cities.count(), 2)

    def test_registration_migrates_cities(self):
        self.set_guest_cities(['Tokyo', 'London'])
        response = self.client.post(reverse('register'), {
            'username': 'new-user', 'email': 'new@example.com',
            'password': 'test-password', 'password_confirm': 'test-password',
        })
        self.assertRedirects(response, reverse('index'), fetch_redirect_response=False)
        new_user = User.objects.get(username='new-user')
        self.assertEqual(list(new_user.cities.values_list('name', flat=True)), ['Tokyo', 'London'])
        self.assertEqual(int(self.client.session['_auth_user_id']), new_user.pk)
        self.assertNotIn('guest_cities', self.client.session)

    def test_failed_login_or_registration_preserves_guest_cities(self):
        self.set_guest_cities(['London'])
        response = self.client.post(reverse('login'), {
            'username': self.user.username, 'password': 'wrong',
        })
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('register'), {
            'username': 'new-user', 'password': 'one', 'password_confirm': 'two',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.session['guest_cities'], ['London'])
        self.assertFalse(City.objects.exists())
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_without_guest_cities_preserves_account(self):
        City.objects.create(user=self.user, name='London')
        self.client.post(reverse('login'), {
            'username': self.user.username, 'password': 'test-password',
        })
        self.assertEqual(list(self.user.cities.values_list('name', flat=True)), ['London'])
        self.assertNotIn('guest_cities', self.client.session)

    def test_failed_migration_rolls_back_and_retains_guest_list(self):
        request = RequestFactory().get('/')
        request.session = {'guest_cities': ['Tokyo', 'London']}
        create_city = City.objects.get_or_create

        def fail_second_city(**kwargs):
            if kwargs['name'] == 'Tokyo':
                raise IntegrityError('Simulated database failure')
            return create_city(**kwargs)

        with patch('weather.cities.City.objects.get_or_create', side_effect=fail_second_city):
            with self.assertRaises(IntegrityError):
                migrate_guest_cities(request, self.user)
        self.assertFalse(self.user.cities.exists())
        self.assertEqual(request.session['guest_cities'], ['Tokyo', 'London'])

    def test_logout_keeps_account_cities_and_returns_to_guest_mode(self):
        City.objects.create(user=self.user, name='London')
        self.client.force_login(self.user)
        self.client.post(reverse('logout'))
        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['cities'], [])
        self.assertTrue(self.user.cities.filter(name='London').exists())
