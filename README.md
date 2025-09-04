# Idealista Updater

This Python script automates the retrieval of real estate data from the Idealista API, updates a historical CSV file, and sends a summary notification to a Telegram bot.

## Features

- Authenticates with the Idealista API using OAuth2.
- Fetches property listings for both rent and sale in a specified area.
- Updates a historical CSV file, avoiding duplicate entries.
- Calculates basic statistics and average prices.
- Sends a summary message to a Telegram chat via bot.

## Requirements

- Python 3.8 or higher
- `requests`
- `pandas`

Install dependencies with:

```
pip install -r requirements.txt
```

## Configuration

1. **Idealista API Credentials:**  
   Set your `CLIENT_ID` and `CLIENT_SECRET` in the script.

2. **Telegram Bot Credentials:**  
   Set your `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the script.

3. **CSV Path:**  
   Adjust the `CSV_PATH` variable to your desired location.

## Usage

Run the script manually:

```
python update_idealista.py
```

The script will:
- Retrieve new property data from Idealista.
- Update the CSV file with new entries.
- Send a summary notification to your Telegram chat.

## License

This project is licensed under the Apache License 2.0.  
See [LICENSE](https://www.apache.org/licenses/LICENSE-2.0) for
