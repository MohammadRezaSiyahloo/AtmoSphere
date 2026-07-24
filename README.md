# AtmoSphere

A Django weather app with dynamic backgrounds, city comparison, and per-user city storage.

## Features

- **Live weather data** — temperature, humidity, wind, visibility, pressure, cloudiness
- **Air quality index** — AQI with PM2.5 and PM10 readings
- **3-day forecast** — daily high/low with hourly breakdowns
- **City comparison** — side-by-side comparison with winner highlighting
- **Dynamic backgrounds** — weather-themed images that change on hover
- **Unit toggle** — switch between Celsius and Fahrenheit
- **Geolocation** — auto-detect location on first visit
- **Per-user cities** — login to save cities across sessions
- **Autocomplete** — 44k+ world cities for search suggestions
- **Caching** — 10-minute cache to reduce API calls
- **Rate limiting** — prevents API abuse
- **Responsive** — works on desktop, tablet, and mobile

## Tech Stack

- Python 3.14 / Django 6.0
- OpenWeatherMap API (weather, forecast, air pollution)
- SQLite (development)
- HTML / CSS / JavaScript (no frameworks)

## Setup

```bash
# Clone
git clone <repo-url>
cd Weather

# Virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Environment variables
cp .env.example .env
# Edit .env with your OpenWeatherMap API key

# Download background images
python download_bg_images.py

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
Weather/
├── root/                  # Django project config
│   ├── settings.py
│   └── urls.py
├── weather/               # Main app
│   ├── views.py           # Weather fetching, caching, rate limiting
│   ├── models.py          # City model (per-user)
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
├── download_bg_images.py  # One-time image downloader
├── manage.py
└── .env.example
```

## Usage

1. Register an account or login
2. Add cities using the search bar (autocomplete available)
3. Click forecast days for hourly details and extra data
4. Click "Compare Cities" to compare two cities side-by-side
5. Toggle °C/°F in the navbar
6. Click refresh on individual cards or "Refresh All"

## License

MIT
