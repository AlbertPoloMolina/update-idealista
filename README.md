# Idealista Updater

This Python script automates the retrieval of real estate data from the Idealista API across multiple locations (La Vall d'Uixó and Córdoba), updates independent historical CSV files, and sends summary notifications to a Telegram bot.

## Features

- Authenticates with the Idealista API using OAuth2.
- Supports multi-location queries with custom center coordinates and search radii (e.g. La Vall d'Uixó 5km, Córdoba 20km).
- Fetches property listings for both rent and sale with automatic pagination.
- Updates independent historical CSV files (`historial_idealista.csv` and `historial_idealista_cordoba.csv`), avoiding duplicate entries.
- Calculates basic statistics and average prices per location.
- Sends summary messages to a Telegram chat via bot for each location.

## Requirements

- Python 3.8 or higher
- `requests`
- `pandas`
- `geopandas`
- `shapely`

Install dependencies with:

```
pip install -r requirements.txt
```

## Configuration

1. **Idealista API Credentials:**  
   Set your `CLIENT_ID` and `CLIENT_SECRET` via environment variables or GitHub Secrets.

2. **Telegram Bot Credentials:**  
   Set your `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` via environment variables or GitHub Secrets.

3. **Locations & CSV Paths:**  
   Configured in `LOCATIONS` inside `update_idealista.py`:
   - **La Vall d'Uixó (5km):** `historial_idealista.csv` (with CUSEC geojson mapping).
   - **Córdoba (20km):** `historial_idealista_cordoba.csv`.

## Usage

Run the script manually:

```
python update_idealista.py
```

The script will:
- Retrieve new property data from Idealista for each configured location.
- Update each location's independent CSV file with new entries.
- Send summary notifications to your Telegram chat.

## License

This project is licensed under the Apache License 2.0.  
See [LICENSE](https://www.apache.org/licenses/LICENSE-2.0) for details.
