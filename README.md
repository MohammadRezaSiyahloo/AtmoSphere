# AtmoSphere

A Django weather app with dynamic backgrounds, city comparison, and saved locations for guests and registered users.

## Features

- **Live weather data** — temperature, humidity, wind, visibility, pressure, cloudiness
- **Air quality index** — AQI with PM2.5 and PM10 readings
- **3-day forecast** — daily high/low with hourly breakdowns
- **Forecast fallback** — current weather remains available when forecast data is missing; usable forecast days are retained
- **City comparison** — side-by-side comparison with winner highlighting
- **Dynamic backgrounds** — weather-themed images that change on hover
- **Unit toggle** — switch between Celsius and Fahrenheit
- **Geolocation** — auto-detect location on first visit
- **Per-user cities** — login to save cities across sessions
- **Guest mode** — search, save, view, compare, and remove locations without registration
- **Session-based saved locations** — guest city names are stored in Django sessions
- **Registered user accounts** — saved cities persist in the database across sessions and devices
- **Guest-to-account migration** — saved guest locations transfer automatically after login or registration, without duplicate entries
- **Autocomplete** — 44k+ world cities for search suggestions
- **Caching** — 60-minute cache to reduce API calls, configurable through `WEATHER_CACHE_TTL`
- **Rate limiting** — limits individual and bulk refresh requests per account or guest session
- **Location feedback** — visible messages for invalid searches, unavailable weather services, and failed location detection
- **Responsive** — works on desktop, tablet, and mobile

## Tech Stack

- Python 3.14 / Django 6.0
- OpenWeatherMap API (weather, forecast, air pollution)
- SQLite (development)
- HTML / CSS / JavaScript (no frameworks)

## Setup

```bash
# Clone
git clone https://github.com/MohammadRezaSiyahloo/AtmoSphere.git
cd AtmoSphere

# Virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Environment variables
cp .env.example .env
# Edit .env with your OpenWeatherMap API key

# Background images are included in weather/static/weather/images/bg/.
# Earlier setup instructions referenced download_bg_images.py;
# that script is not present in this repository and is not required.

# Migrate
python manage.py migrate

# Create admin user
python manage.py createsuperuser

# Run
python manage.py runserver
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Django secret key |
| `DEBUG` | `True` or `False` |
| `OPENWEATHERMAP_API_KEY` | Get one at [openweathermap.org](https://openweathermap.org/api) |

## Project Structure

```
AtmoSphere/
├── root/                  # Django project config
│   ├── settings.py
│   └── urls.py
├── weather/               # Main app
│   ├── views.py           # Weather fetching, caching, rate limiting
│   ├── models.py          # City model (per-user)
│   ├── cities.py          # Session/database storage helpers and migration
│   ├── signals.py         # Transfer guest cities after successful login
│   ├── tests.py           # Guest, account, and migration regression tests
│   ├── test_weather_resilience.py # Error feedback, refresh limits, forecast fallback tests
│   ├── forms.py           # Add city form
│   ├── templates/
│   │   ├── weather/       # Main templates
│   │   └── accounts/      # Auth templates
│   └── static/
│       ├── weather/       # CSS, JS, images
│       └── weather/images/
│           ├── icons/     # Weather icons
│           └── bg/        # Background images
├── accounts/              # Auth app (login/register)
├── manage.py
└── .env.example
```

The earlier project layout listed `download_bg_images.py` as a one-time image
downloader. Images are already committed; the current checkout does not include
that script.

## Usage

1. Open the homepage to use guest mode, or register an account or login
2. Add cities using the search bar (autocomplete available)
3. Click forecast days for hourly details and extra data
4. Click "Compare Cities" to compare two cities side-by-side
5. Toggle °C/°F in the navbar
6. Click refresh on individual cards or "Refresh All"
7. Remove a saved location using the delete button on its weather card

Guests can use the application without creating an account. Their saved locations
belong to their Django session and remain available while that session is valid.
Clearing cookies or allowing the session to expire can lose access to those
locations. Login or register in the same browser to transfer them automatically
to an account. Registered users receive persistent database storage.

## Technical Details

The existing weather views use small helpers to select storage based on
`request.user.is_authenticated`. Anonymous users store only city names under
`request.session['guest_cities']`; weather responses remain in the cache. Django's
existing session middleware and default database session backend handle session
persistence, so no guest model or additional dependency is needed.

Authenticated users continue to use the existing `City` model, its user foreign
key, newest-first ordering, and `(user, name)` uniqueness constraint. Both flows
use the same city form, OpenWeatherMap validation, weather processing, templates,
and add/delete/geolocation endpoints. Account cache keys remain unchanged; guests
use session-specific keys for weather caching and refresh rate limiting.

A `user_logged_in` signal receiver handles both the built-in login view and the
registration view's existing `login()` call. It transfers guest names with
`get_or_create()` inside a database transaction, then clears `guest_cities` only
after the writes succeed. Duplicate detection uses exact names, matching the
existing model constraint. Failed authentication leaves guest locations intact.
Logout retains account cities in the database and returns to guest mode.

No new schema migration is required. Run the normal `python manage.py migrate`
command on a fresh installation to create the existing city, authentication, and
session tables.

## Testing

With dependencies installed and the environment variables above configured:

```bash
python manage.py test weather
python manage.py check
python manage.py makemigrations --check --dry-run
```

Tests cover guest saving, viewing, deletion, geolocation, session isolation,
account storage and cache behavior, login and registration migration, duplicate
prevention, failed authentication, migration rollback, and logout. Additional
regressions cover location error feedback, individual and bulk refresh limits,
rate-limit window reset, and missing, malformed, partial, and complete forecasts. OpenWeatherMap
calls are mocked, so tests make no weather API requests; a placeholder
`OPENWEATHERMAP_API_KEY` is sufficient for testing.

## Roadmap

- Improve recovery options for weather API failures and unavailable forecasts.
- Evaluate canonical city identifiers to distinguish locations with the same name.
- Add shared caching and rate limiting when deploying across multiple workers.
- Expand accessibility checks and browser tests for the existing interface.

## License

MIT
