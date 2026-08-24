# Idealista Updater

This Python script automates the retrieval of real estate data from the Idealista API across separate locations (La Vall d'Uixó and Córdoba), updates independent historical CSV files, and sends summary notifications to a Telegram bot.

## Features

- **OAuth2 Authentication:** Connects to the Idealista API using client credentials.
- **Multi-location & Independent Searches:** Execute searches separately per location (La Vall d'Uixó 5km, Córdoba 5km) or altogether.
- **Anti-Loop & Quota Protections:** Hard page limit safeguards (`--max-pages`), duplicate page cycle detection, request timeouts (25s), exponential backoff retries on rate limits (HTTP 429), and request pacing (1.2s delay).
- **Independent Storage:** Updates separate historical CSV files (`historial_idealista.csv` and `historial_idealista_cordoba.csv`), deduplicating entries by `[propertyCode, updateDate]`.
- **Automated Staggered Workflows:** GitHub Actions runs each location independently at different hours to avoid API saturation.
- **Telegram Notifications:** Sends detailed summary statistics per location after each run.

## Requirements

- Python 3.8 or higher
- `requests`
- `pandas`
- `geopandas`
- `shapely`

Install dependencies with:

```bash
pip install -r requirements.txt
```

## Configuration

1. **Idealista API Credentials:**  
   Set your `CLIENT_ID` and `CLIENT_SECRET` via environment variables or GitHub Secrets.

2. **Telegram Bot Credentials:**  
   Set your `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` via environment variables or GitHub Secrets.

3. **Locations & CSV Paths:**  
   Configured in `LOCATIONS` inside `update_idealista.py`:
   - **La Vall d'Uixó (`vall`):** 5km radius -> `historial_idealista.csv` (with CUSEC geojson mapping).
   - **Córdoba (`cordoba`):** 5km radius -> `historial_idealista_cordoba.csv`.

## Usage

### Run for a specific location:

```bash
# Process only La Vall d'Uixó
python update_idealista.py --location vall

# Process only Córdoba
python update_idealista.py --location cordoba

# Process all locations
python update_idealista.py --location all
```

### Safety Options:

```bash
# Customize max pages per operation (default: 20)
python update_idealista.py --location cordoba --max-pages 15
```

## Scheduled GitHub Workflows

- **La Vall d'Uixó:** Runs daily at `09:10 UTC` via `.github/workflows/update_idealista_vall.yml`.
- **Córdoba:** Runs daily at `15:10 UTC` via `.github/workflows/update_idealista_cordoba.yml`.

## License

This project is licensed under the Apache License 2.0.  
See [LICENSE](https://www.apache.org/licenses/LICENSE-2.0) for details.
