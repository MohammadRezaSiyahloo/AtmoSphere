from django.shortcuts import render, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
import requests, datetime, collections, json
from django.views.generic import View

from .forms import AddCityForm
from .cities import get_saved_cities, save_city, delete_city, get_storage_key


def get_api_response(url, allow_not_found=False):
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return resp
    except requests.HTTPError as exc:
        # Search needs to distinguish an unknown city from an API outage.
        if allow_not_found and exc.response is not None and exc.response.status_code == 404:
            return exc.response
        return None
    except requests.RequestException:
        return None


def get_forecast_reports(response):
    """Keep usable forecast reports; missing optional data must not hide current weather."""
    if response is None:
        return []
    try:
        payload = response.json()
    except ValueError:
        return []
    reports = payload.get('list', []) if isinstance(payload, dict) else []
    if not isinstance(reports, list):
        return []
    valid_reports = []
    for report in reports:
        try:
            datetime.datetime.strptime(report['dt_txt'], '%Y-%m-%d %H:%M:%S')
            # These are the fields consumed by the existing forecast processor.
            for field in ('temp', 'feels_like', 'humidity', 'pressure'):
                round(report['main'][field])
            for field in ('speed', 'deg'):
                round(report['wind'][field])
            round(report['wind'].get('gust', report['wind']['speed']))
            round(report['clouds']['all'])
            if not isinstance(report['weather'][0]['icon'], str):
                continue
        except (KeyError, IndexError, TypeError, ValueError, OverflowError):
            continue
        valid_reports.append(report)
    return valid_reports


def fetch_city_weather(city, API_key, today):
    """Fetch and process all weather data for a city. Returns dict or None."""
    weather_resp = get_api_response(f'https://api.openweathermap.org/data/2.5/weather?q={city}&units=metric&appid={API_key}')
    if weather_resp is None:
        return {'city': city, 'error': True}
    city_weather = weather_resp.json()
    if city_weather.get('cod') != 200:
        return {'city': city, 'error': True}

    forecast_resp = get_api_response(f'https://api.openweathermap.org/data/2.5/forecast?q={city}&units=metric&cnt=32&appid={API_key}')
    city_forecast = {'list': get_forecast_reports(forecast_resp)}

    def get_icon(weather_icon):
        icons = {
            '01d': 'sun.png', '01n': 'moon.png',
            '02': 'cloud.png', '03': 'rain-cloud.png', '04': 'cloud-off.png',
            '09': 'cloud-rain.png', '10': 'cloud-drizzle.png', '11': 'cloud-lighning.png', '13': 'cloud-snow.png',
            '50': 'wind.png',
        }
        for key in icons.keys():
            if key in weather_icon:
                return icons[key]

    def get_next_3_days(today):
        return [today + datetime.timedelta(days=i) for i in range(1, 4)]

    def get_next_3_days_weather(next_3_days, city_forecast):
        next_3_days_reports = []
        next_3_days_weather_data = []

        for report in city_forecast['list']:
            next_3_days_reports.append({
                'dt_txt': report['dt_txt'],
                'temp': round(report['main']['temp']),
                'icon': report['weather'][0]['icon'],
                'feels_like': round(report['main']['feels_like']),
                'humidity': report['main']['humidity'],
                'pressure': report['main']['pressure'],
                'wind_speed': round(report['wind']['speed'] * 3.6, 1),
                'wind_deg': report['wind']['deg'],
                'wind_gust': round(report['wind'].get('gust', report['wind']['speed']) * 3.6, 1),
                'clouds': report['clouds']['all'],
            })

        for day in next_3_days:
            daily_temps = []
            daily_icons = []
            daily_hourly = []
            noon_report = None
            for report in next_3_days_reports:
                if str(day) in report['dt_txt']:
                    daily_temps.append(report['temp'])
                    daily_icons.append(report['icon'])
                    daily_hourly.append({
                        'time': report['dt_txt'].split(' ')[1][:5],
                        'temp': report['temp'],
                        'icon': get_icon(report['icon']),
                    })
                    if '12:00:00' in report['dt_txt']:
                        noon_report = report
            if not noon_report:
                for report in next_3_days_reports:
                    if str(day) in report['dt_txt']:
                        noon_report = report
                        break
            # Partial forecasts may have no reports for one or more days.
            if not daily_temps:
                continue
            day_data = {
                'today_short': day.strftime('%a'), 'temp_max': max(daily_temps), 'temp_min': min(daily_temps),
                'icon': get_icon(collections.Counter(daily_icons).most_common(1)[0][0]),
                'hourly': daily_hourly,
                'hourly_json': json.dumps(daily_hourly),
            }
            if noon_report:
                day_data.update({
                    'feels_like': noon_report['feels_like'],
                    'humidity': noon_report['humidity'],
                    'wind_speed': noon_report['wind_speed'],
                    'wind_gust': noon_report['wind_gust'],
                    'wind_deg': noon_report['wind_deg'],
                    'pressure': noon_report['pressure'],
                    'clouds': noon_report['clouds'],
                })
            next_3_days_weather_data.append(day_data)

        return next_3_days_weather_data

    # Air quality
    lat, lon = city_weather['coord']['lat'], city_weather['coord']['lon']
    aqi_data = {}
    aqi_resp = get_api_response(f'https://api.openweathermap.org/data/2.5/air_pollution?lat={lat}&lon={lon}&appid={API_key}')
    if aqi_resp:
        aqi_json = aqi_resp.json()
        if aqi_json.get('list'):
            aqi_main = aqi_json['list'][0]
            aqi_data = {
                'aqi': aqi_main['main']['aqi'],
                'pm2_5': round(aqi_main['components']['pm2_5'], 1),
                'pm10': round(aqi_main['components']['pm10'], 1),
            }

    sunrise_ts = city_weather['sys']['sunrise']
    sunset_ts = city_weather['sys']['sunset']
    tz_offset = city_weather['timezone']
    sunrise_dt = datetime.datetime.fromtimestamp(sunrise_ts, tz=datetime.timezone(datetime.timedelta(seconds=tz_offset)))
    sunset_dt = datetime.datetime.fromtimestamp(sunset_ts, tz=datetime.timezone(datetime.timedelta(seconds=tz_offset)))

    # Today's hourly
    city_tz = datetime.timezone(datetime.timedelta(seconds=tz_offset))
    city_now = datetime.datetime.now(tz=city_tz)
    city_today_str = city_now.strftime('%Y-%m-%d')
    hourly_today = []
    for report in city_forecast.get('list', []):
        if city_today_str in report['dt_txt']:
            hourly_today.append({
                'time': report['dt_txt'].split(' ')[1][:5],
                'temp': round(report['main']['temp']),
                'icon': get_icon(report['weather'][0]['icon']),
            })

    data = {
        'country': city_weather['sys']['country'], 'city': city,
        'weather': city_weather['weather'][0]['main'], 'icon': get_icon(city_weather['weather'][0]['icon']),
        'temp': round(city_weather['main']['temp']),
        'feels_like': round(city_weather['main']['feels_like']),
        'temp_min': round(city_weather['main']['temp_min']),
        'temp_max': round(city_weather['main']['temp_max']),
        'pressure': city_weather['main']['pressure'],
        'humidity': city_weather['main']['humidity'], 'visibility': round(city_weather['visibility'] / 100),
        'wind_speed': round(city_weather['wind']['speed'] * 3.6, 1),
        'wind_deg': city_weather['wind']['deg'],
        'wind_gust': round(city_weather['wind'].get('gust', city_weather['wind']['speed']) * 3.6, 1),
        'clouds': city_weather['clouds']['all'],
        'sunrise': sunrise_dt.strftime('%H:%M'),
        'sunset': sunset_dt.strftime('%H:%M'),
        'updated_at': timezone.localtime(timezone.now()).strftime('%H:%M'),
        'hourly_today_json': json.dumps(hourly_today),
        'next_3_days': get_next_3_days_weather(get_next_3_days(today), city_forecast),
        'fetched_at': timezone.now().isoformat(),
    }
    data.update(aqi_data)
    return data


class IndexView(View):
    def get(self, request):
        today = timezone.localdate(timezone.now())
        cities = get_saved_cities(request)
        storage_key = get_storage_key(request)
        refresh_city = request.GET.get('refresh', None)  # city name, 'all', or None
        cache_ttl = getattr(settings, 'WEATHER_CACHE_TTL', 600)

        # Rate limiting for refresh
        if refresh_city:
            rate_key = f'rate_{storage_key}'
            rate_data = cache.get(rate_key, {'count': 0, 'window_start': timezone.now().isoformat()})
            window_start = datetime.datetime.fromisoformat(rate_data['window_start'])
            if (timezone.now() - window_start).total_seconds() > getattr(settings, 'RATE_LIMIT_WINDOW', 60):
                rate_data = {'count': 0, 'window_start': timezone.now().isoformat()}
            if rate_data['count'] >= getattr(settings, 'RATE_LIMIT_MAX_REQUESTS', 10):
                refresh_city = None  # Rate limited
                messages.warning(request, 'Refresh limit reached. Please wait before refreshing again.')
            else:
                rate_data['count'] += 1
                cache.set(rate_key, rate_data, getattr(settings, 'RATE_LIMIT_WINDOW', 60))

        # Derive this only after rate limiting, including the "Refresh All" case.
        refresh_all = refresh_city == 'all'
        weather_data = []
        for city in cities:
            cache_key = f'weather_{storage_key}_{city}'
            needs_refresh = refresh_all or (refresh_city and refresh_city.lower() == city.lower())
            cached = None if needs_refresh else cache.get(cache_key)
            if cached:
                cached['from_cache'] = True
                weather_data.append(cached)
            else:
                data = fetch_city_weather(city, settings.OPENWEATHERMAP_API_KEY, today)
                if data and not data.get('error'):
                    data['from_cache'] = False
                    cache.set(cache_key, data, cache_ttl)
                weather_data.append(data)

        return render(request, 'weather/index.html', context={
            'cities': weather_data, 'form': AddCityForm,
            'today': today.strftime('%A'), 'today_date': today, 'today_short': today.strftime('%a'),
        })

    def post(self, request):
        form = AddCityForm(request.POST)
        if form.is_valid():
            API_key = settings.OPENWEATHERMAP_API_KEY
            city = form.cleaned_data.get('city', None)
            city_weather = get_api_response(f'https://api.openweathermap.org/data/2.5/weather?q={city}&units=metric&appid={API_key}', allow_not_found=True)
            if city_weather and city_weather.status_code == 200:
                save_city(request, city)
            elif city_weather is not None and city_weather.status_code == 404:
                messages.error(request, 'Location not found. Please check the city name and try again.')
            else:
                messages.error(request, 'Weather service is unavailable. Please try again later.')
            return redirect(reverse_lazy('index'))
        else:
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)
            return redirect(reverse_lazy('index'))


class CityDeleteView(View):
    def post(self, request):
        city_name = request.POST.get('city_name', None)
        delete_city(request, city_name)
        # Clear cache for deleted city
        cache.delete(f'weather_{get_storage_key(request)}_{city_name}')
        return redirect(reverse_lazy('index'))


class GeoLocateView(View):
    def post(self, request):
        lat = request.POST.get('lat')
        lon = request.POST.get('lon')
        if lat and lon:
            API_key = settings.OPENWEATHERMAP_API_KEY
            resp = get_api_response(f'https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&units=metric&appid={API_key}')
            if resp and resp.status_code == 200:
                try:
                    data = resp.json()
                except ValueError:
                    data = {}
                city_name = data.get('name') if isinstance(data, dict) else None
                if city_name:
                    save_city(request, city_name)
                else:
                    messages.error(request, 'Could not identify your location. Please search for a city instead.')
            else:
                messages.error(request, 'Weather service is unavailable. Please try again later.')
        else:
            messages.error(request, 'Could not identify your location. Please search for a city instead.')
        return redirect(reverse_lazy('index'))
