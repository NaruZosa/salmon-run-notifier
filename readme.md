# 🎮 Salmon Run Notifier 🐟

Welcome to the **Salmon Run Notifier**! This Python script fetches the current and upcoming Salmon Run schedules from Splatoon 3 and sends notifications using the Apprise library. It ensures you never miss a Salmon Run rotation by providing timely alerts. 🎉

## Table of Contents 📑

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Logging](#logging)
- [Error Handling](#error-handling)
- [Contributing](#contributing)

## Features ✨

- Fetches current and upcoming Salmon Run schedules.
- Sends notifications using Apprise.
- Handles errors gracefully and retries on failure.
- Notifies if there are consistent failures for more than a specified threshold.
- Configurable quiet hours to avoid notifications during your beauty sleep. 😴

## Requirements 📋

- Python 3.12+
- `apprise` library
- `requests` library
- `python-dateutil` library
- `loguru` library

## Installation 🛠️

1. Clone the repository:
    ```sh
    git clone https://github.com/NaruZosa/salmon-run-notifier.git
    cd salmon-run-notifier
    ```

2. Install the required libraries:
    ```sh
    pip install apprise requests python-dateutil loguru
    ```

## Configuration ⚙️


Create a `salmon_config.toml` file in the same directory as the script with the following content:

```toml
# Salmon Run Notifier Configuration File

[settings]
# The local timezone for the notifier (e.g., "America/New_York")
local_timezone = "Your/Timezone"

# The start hour of the quiet period (0 = midnight)
alert_quiet_start = 0  # Midnight

# The end hour of the quiet period (10 = 10 AM)
alert_quiet_end = 10  # 10 AM

# The Apprise notification paths in a list (e.g., ["tgram://<token>/<chat_id>"])
apprise_paths = ["tgram://your_telegram_token/your_chat_id"]

# The API endpoint for fetching Salmon Run schedules
schedules_api = "https://splatoon3.ink/data/schedules.json"

# The number of hours to wait before notifying of consistent failures
failure_threshold_hours = 6  # 6 hours
```

## Usage 🚀

Run the script using Python:
```sh
python salmon_run_notifier.py
```

## Logging 📜

The script uses the `loguru` library for logging. It logs debug information, errors, and notifications to help trace the flow of the program and identify issues.

## Error Handling 🛡️

The script includes robust error handling to manage exceptions during API calls, schedule processing, and notification sending. It retries on failure and notifies if there are consistent failures for more than 6 hours.

## Contributing 🤝

Contributions are welcome! Please fork the repository and submit a pull request with your changes. Let's make sure no Inkling or Octoling misses a (good) Salmon Run rotation ever again! 🦑

---

Feel free to reach out if you have any questions or need further assistance. Happy Salmon Running! 🐟🎮