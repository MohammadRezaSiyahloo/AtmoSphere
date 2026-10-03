import datetime
import json
from copy import deepcopy
from unittest.mock import Mock, patch

import requests
from django.contrib.auth.models import User
from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import City
from .views import fetch_city_weather, get_api_response


class LocationFeedbackTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    @patch('weather.views.get_api_response')
    def test_unknown_city_shows_error_without_saving(self, api):
        # requests treats HTTP 404 responses as false, although they exist.
        response = requests.Response()
        response.status_code = 404
        api.return_value = response
        user = User.objects.create_user(username='feedback-user')
        for authenticated in [False, True]:
            with self.subTest(authenticated=authenticated):
                client = Client()
                if authenticated:
                    client.force_login(user)
                result = client.post(reverse('add'), {'city': 'Unknown'}, follow=True)
                self.assertContains(result, 'Location not found.')
                self.assertContains(result, 'role="status"')
                self.assertNotIn('guest_cities', client.session)
                self.assertFalse(City.objects.exists())
                # Flash feedback is consumed by the redirected dashboard.
                self.assertNotContains(client.get(reverse('index')), 'Location not found.')

    @patch('weather.views.get_api_response', return_value=None)
    def test_api_failure_shows_service_error(self, api):
        response = self.client.post(reverse('add'), {'city': 'London'}, follow=True)
        self.assertContains(response, 'Weather service is unavailable.')
        self.assertNotIn('guest_cities', self.client.session)
        self.assertFalse(City.objects.exists())

    @patch('weather.views.get_api_response')
    def test_form_errors_are_visible_without_api_calls(self, api):
        for name in ['', 'x' * 101]:
            with self.subTest(name=name):
                response = self.client.post(reverse('add'), {'city': name}, follow=True)
                self.assertContains(response, 'app-message error')
        api.assert_not_called()

    @patch('weather.views.get_api_response')
    def test_geolocation_failures_show_feedback_without_saving(self, api):
        for response in [None, Mock(json=Mock(return_value={})),
                         Mock(json=Mock(side_effect=ValueError('Invalid JSON')))]:
            with self.subTest(response=response):
                if response is not None:
                    response.status_code = 200
                api.return_value = response
                result = self.client.post(reverse('geolocate'), {'lat': '51.5', 'lon': '-0.1'}, follow=True)
                self.assertContains(result, 'app-message error')
                self.assertNotIn('guest_cities', self.client.session)
                self.assertFalse(City.objects.exists())
        result = self.client.post(reverse('geolocate'), {}, follow=True)
        self.assertContains(result, 'Could not identify your location.')


class APIResponseTests(SimpleTestCase):
    @patch('weather.views.requests.get')
    def test_search_can_identify_http_404_without_changing_other_callers(self, get):
        response = requests.Response()
        response.status_code = 404
        get.return_value = response
        self.assertIsNone(get_api_response('https://example.invalid/weather'))
        self.assertIs(get_api_response('https://example.invalid/weather', allow_not_found=True), response)

    @patch('weather.views.requests.get')
    def test_other_http_errors_and_timeouts_remain_unavailable(self, get):
        for status in [401, 429, 500]:
            response = requests.Response()
            response.status_code = status
            get.return_value = response
            self.assertIsNone(get_api_response('https://example.invalid/weather', allow_not_found=True))
        get.side_effect = requests.Timeout()
        self.assertIsNone(get_api_response('https://example.invalid/weather', allow_not_found=True))


@override_settings(RATE_LIMIT_MAX_REQUESTS=1, RATE_LIMIT_WINDOW=60)
class RefreshLimitTests(TestCase):
    @patch('weather.views.fetch_city_weather')
    def test_refresh_all_and_single_city_obey_limits_and_window_reset(self, fetch):
        user = User.objects.create_user(username='refresh-user')
        City.objects.create(user=user, name='London')
        City.objects.create(user=user, name='Tokyo')
        self.addCleanup(cache.clear)
        fetch.side_effect = lambda city, *args: {'city': city, 'icon': 'sun.png', 'weather': 'Clear'}
        for authenticated in [False, True]:
            for refresh in ['all', 'London']:
                with self.subTest(authenticated=authenticated, refresh=refresh):
                    cache.clear()
                    fetch.reset_mock()
                    client = Client()
                    if authenticated:
                        client.force_login(user)
                        storage_key = user.pk
                    else:
                        session = client.session
                        session['guest_cities'] = ['London', 'Tokyo']
                        session.save()
                        storage_key = f'guest_{session.session_key}'
                    client.get(reverse('index'))  # Populate both cached cards.
                    self.assertEqual(fetch.call_count, 2)
                    client.get(reverse('index'), {'refresh': refresh})
                    expected_calls = 4 if refresh == 'all' else 3
                    self.assertEqual(fetch.call_count, expected_calls)
                    limited = client.get(reverse('index'), {'refresh': refresh})
                    self.assertEqual(fetch.call_count, expected_calls)
                    self.assertContains(limited, 'Refresh limit reached.')
                    self.assertTrue(all(city['from_cache'] for city in limited.context['cities']))
                    self.assertEqual(cache.get(f'rate_{storage_key}')['count'], 1)
                    cache.set(f'rate_{storage_key}', {
                        'count': 1,
                        'window_start': (timezone.now() - datetime.timedelta(seconds=61)).isoformat(),
                    }, 60)
                    resumed = client.get(reverse('index'), {'refresh': refresh})
                    self.assertEqual(fetch.call_count, expected_calls + (2 if refresh == 'all' else 1))
                    self.assertNotContains(resumed, 'Refresh limit reached.')


class ForecastFallbackTests(SimpleTestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.current = {
            'cod': 200, 'coord': {'lat': 51.5, 'lon': -0.1},
            'sys': {'country': 'GB', 'sunrise': 1700000000, 'sunset': 1700040000},
            'timezone': 0, 'weather': [{'main': 'Clear', 'icon': '01d'}],
            'main': {'temp': 21, 'feels_like': 20, 'temp_min': 18, 'temp_max': 23,
                     'pressure': 1013, 'humidity': 55},
            'visibility': 10000, 'wind': {'speed': 2, 'deg': 90}, 'clouds': {'all': 0},
        }

    def report(self, day):
        return {
            'dt_txt': f'{day} 12:00:00',
            'main': deepcopy(self.current['main']),
            'weather': [{'icon': '01d'}],
            'wind': {'speed': 2, 'deg': 90}, 'clouds': {'all': 0},
        }

    def fetch(self, forecast):
        with patch('weather.views.get_api_response', side_effect=[
            Mock(json=Mock(return_value=self.current)), forecast, None,
        ]):
            return fetch_city_weather('London', 'test-key', self.today)

    def test_missing_or_invalid_forecast_keeps_current_weather_visible(self):
        for forecast in [
            None, Mock(json=Mock(side_effect=ValueError('Invalid JSON'))),
            *[Mock(json=Mock(return_value=payload)) for payload in [
                {}, {'list': []}, {'list': None}, {'list': 'invalid'},
                {'cod': '503'}, None, [], {'list': [None, {}, {'weather': []}]},
            ]],
        ]:
            with self.subTest(forecast=forecast):
                data = self.fetch(forecast)
                self.assertEqual(data['temp'], 21)
                self.assertNotIn('error', data)
                self.assertEqual(data['next_3_days'], [])
                self.assertEqual(json.loads(data['hourly_today_json']), [])
                html = render_to_string('weather/weather-preview.html', {'city': data})
                self.assertIn('Current weather is still shown.', html)
                self.assertNotIn('Unable to load weather', html)

    def test_partial_forecast_skips_missing_days_and_bad_reports(self):
        tomorrow = self.today + datetime.timedelta(days=1)
        bad = self.report(tomorrow)
        bad['main'].pop('temp')
        forecast = Mock(json=Mock(return_value={'list': [None, bad, self.report(tomorrow)]}))
        data = self.fetch(forecast)
        self.assertEqual(len(data['next_3_days']), 1)
        self.assertEqual(data['next_3_days'][0]['today_short'], tomorrow.strftime('%a'))
        self.assertEqual(data['next_3_days'][0]['temp_max'], 21)
        self.assertEqual(data['next_3_days'][0]['wind_speed'], 7.2)

    def test_complete_forecast_preserves_existing_output(self):
        reports = [self.report(self.today + datetime.timedelta(days=i)) for i in range(1, 4)]
        # The hourly-today flow uses the city's date, which can differ from Django's timezone.
        city_today = datetime.datetime.now(datetime.timezone.utc).date()
        reports.append(self.report(city_today))
        data = self.fetch(Mock(json=Mock(return_value={'list': reports})))
        self.assertEqual(len(data['next_3_days']), 3)
        self.assertEqual(data['wind_speed'], 7.2)
        self.assertEqual(data['icon'], 'sun.png')
        self.assertEqual(json.loads(data['hourly_today_json']), [
            {'time': '12:00', 'temp': 21, 'icon': 'sun.png'},
        ])
        html = render_to_string('weather/weather-preview.html', {'city': data})
        self.assertNotIn('Some forecast data is unavailable.', html)
