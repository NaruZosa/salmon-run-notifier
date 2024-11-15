"""Salmon Run Notifier: Notifies users of upcoming Salmon Run schedules."""

import datetime
import json
import operator
import shutil
import signal
import sys
import time
import tomllib
import types
from dataclasses import dataclass
from pathlib import Path
from pprint import pformat
from typing import Any

import apprise
import requests
from dateutil import tz
from loguru import logger

# Path for storing alerts and cached data
ALERT_FILE = Path("config/last.alert")
CACHE_FILE = Path("config/cache.temp")


@dataclass
class Config:
    """Configuration settings for the notifier.

    Attributes
    ----------
        local_timezone (str): The local timezone for the notifier.
        alert_quiet_start (int): The start hour of the quiet period.
        alert_quiet_end (int): The end hour of the quiet period.
        apprise_paths (list): The Apprise notification paths in a list.
        schedules_api (str): The API endpoint for fetching Salmon Run schedules.
        failure_threshold_hours (int): The number of hours to wait before notifying of consistent failures.
        simple_console_logger(bool): Whether to use a simpler console logger and silence DEBUG.

    """

    local_timezone: str
    alert_quiet_start: int
    alert_quiet_end: int
    apprise_paths: list
    schedules_api: str
    failure_threshold_hours: int
    simple_console_logger: bool


def load_config(config_path: Path, template_path: Path) -> Config:
    """Load configuration settings from a TOML file or create from template if missing.

    Args:
    ----
        config_path (Path): The path to the configuration file.
        template_path (Path): The path to the configuration template file.

    Returns:
    -------
        Config: The loaded configuration settings.

    Raises:
    ------
        FileNotFoundError: If the configuration file is not found.
        KeyError: If any required configuration setting is missing.
        tomllib.TOMLDecodeError: If there is an error parsing the configuration file.

    """

    if not config_path.exists():
        _copy_template(config_path, template_path)
        sys.exit(66)  # Exit to prompt the user to configure

    try:
        with config_path.open("rb") as f:
            config_data = tomllib.load(f)["settings"]
        return Config(**config_data)
    except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError):
        logger.exception("Error loading configuration. Exiting the lobby.")
        sys.exit(1)


def _copy_template(config_path: Path, template_path: Path) -> None:
    """Copy configuration template and notify user to set up."""
    logger.info("Configuration not found. Copying template.")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(template_path, config_path)
    logger.info(f"Config template copied to {config_path}. Please configure and restart. Exiting the lobby in 10 seconds.")
    time.sleep(10)


def get_schedules(schedules_api: str) -> dict[str, Any]:
    """Fetch schedules from cache or API.

    Args:
    ----
        schedules_api (str): The API endpoint for fetching Salmon Run schedules.

    Returns:
    -------
        dict: A dictionary containing the schedules for "Regular", "Big Run", and "Eggstra Work".

    Raises:
    ------
        requests.RequestException: If there is an error fetching the schedules.

    """

    if _cache_is_valid():
        logger.debug("Using cached schedules.")
        return _load_cached_data()

    try:
        response = requests.get(schedules_api, headers={"User-Agent": _get_user_agent()}, timeout=10)
        response.raise_for_status()
        schedules = response.json()["data"]["coopGroupingSchedule"]
        _cache_schedules(schedules)
        return _extract_schedule_nodes(schedules)
    except requests.RequestException:
        logger.exception("Failed to fetch schedules. The Salmonids are causing trouble!")
        return {"Regular": [], "Big Run": [], "Eggstra Work": []}


def _cache_is_valid() -> bool:
    """Check if the cached data is still valid.

    Returns
    -------
        bool: Whether the cached data is still valid.

    """

    if not CACHE_FILE.exists():
        return False

    with CACHE_FILE.open("r") as cache_file:
        cached_data = json.load(cache_file)
        # Find the earliest end_time, ignoring 'bannerImage' and any empty lists
        end_time = min(
            datetime.datetime.fromisoformat(rotation["endTime"]).timestamp()
            for schedule in cached_data.values() if schedule is not None and "nodes" in schedule
            for rotation in schedule["nodes"]
        )
    if time.time() < end_time:
        time_remaining = end_time - time.time()
        days, remainder = divmod(time_remaining, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, _ = divmod(remainder, 60)
        logger.debug(f"Using cached schedules. Cache expires in {int(days)} days, {int(hours)} hours, and {int(minutes)} minutes (next rotation).")
        return True
    return False


def _load_cached_data() -> dict[str, Any]:
    """Load cached schedules.

    Returns
    -------
        dict: The cached schedules.

    """

    with CACHE_FILE.open("r") as cache_file:
        cached_data = json.load(cache_file)
    return _extract_schedule_nodes(cached_data)


def _get_user_agent() -> str:
    """Return a user agent string for requests.

    Returns
    -------
        str: The user agent string.

    """

    # noinspection PyBroadException
    try:
        with local_file("pyproject.toml").open("rb") as pyproject:
            version = tomllib.load(pyproject)["tool"]["poetry"]["version"]
    except Exception:  # noqa: BLE001
        version = "Unknown"
    return f"Salmon Run Notifier - Version {version}"


def _cache_schedules(schedules: dict[str, Any]) -> None:
    """Write schedules to cache.

    Args:
    ----
        schedules (dict): A dictionary containing the schedules.

    """

    with CACHE_FILE.open("w") as cache_file:
        # noinspection PyTypeChecker
        json.dump(schedules, cache_file)
    logger.debug("Fetched schedules successfully and updated cache. Ready to splat some Salmonids!")


def _extract_schedule_nodes(schedules: dict[str, Any]) -> dict[str, Any]:
    """Extract and organize schedule nodes for Regular, Big Run, and Eggstra Work.

    Args:
    ----
        schedules (dict): A dictionary containing the schedules.

    Returns:
    -------
        dict: The schedule nodes for Regular, Big Run, and Eggstra Work.

    """

    return {
        "Regular": schedules["regularSchedules"]["nodes"],
        "Big Run": schedules["bigRunSchedules"]["nodes"],
        "Eggstra Work": schedules["teamContestSchedules"]["nodes"],
    }


def tidy_schedules(schedules: dict[str, Any], timezone: tz.tzfile) -> list:
    """Organize and return a list of sorted schedules.

    Args:
    ----
        schedules (dict): A dictionary containing the schedules.
        timezone (tz.tzfile): The local timezone for the notifier.

    Returns:
    -------
        list: A flattened list of tidied schedules sorted by the time until the next rotation.

    Raises:
    ------
        KeyError: If there is an error accessing schedule data.

    """

    # noinspection PyBroadException
    try:
        tidied_schedules = [
            _tidy_rotation(rotation, schedule_type, timezone)
            for schedule_type, rotations in schedules.items()
            for rotation in rotations
        ]

        # Flatten and sort schedules
        sorted_schedules = sorted(
            tidied_schedules, key=operator.itemgetter("seconds_until_rotation"),
        )
        logger.debug("Schedules tidied successfully. Ready for the next wave!")
        logger.trace(f"Schedules:\n"
                     f"{pformat(sorted_schedules)}")
        # Remove currently running rotations only if they have alerted previously
        return [rotation for rotation in sorted_schedules if rotation["seconds_until_rotation"] > 0 or not has_been_alerted(rotation)]

    except KeyError:
        logger.exception("Key error while tidying schedules. The Salmonids are messing with the data!")
        return []
    except Exception:  # noqa: BLE001
        logger.exception("Error tidying schedules. The ink is everywhere!")
        return []


def _tidy_rotation(rotation: dict, schedule_type: str, timezone: tz.tzfile) -> dict:
    """Reformat a single rotation.

    Args:
    ----
        rotation (dict): A dictionary containing the schedules.
        schedule_type (str): The schedule type.
        timezone (tz.tzfile): The local timezone for the notifier.

    Returns:
    -------
        The formatted schedule.

    """

    start_time = datetime.datetime.fromisoformat(rotation["startTime"])
    end_time = datetime.datetime.fromisoformat(rotation["endTime"])
    return {
        "seconds_until_rotation": start_time.timestamp() - datetime.datetime.now(tz=datetime.UTC).timestamp(),
        "stage": rotation["setting"]["coopStage"]["name"],
        "boss": rotation["setting"]["boss"]["name"] if rotation["setting"]["boss"] is not None else "Random",
        "weapons": [
            weapon["name"] if weapon["__splatoon3ink_id"] != "747937841598fff7" else "Grizzco Random"
            for weapon in rotation["setting"]["weapons"]
        ],
        "type": schedule_type,
        "start_time": start_time.astimezone(timezone),
        "end_time": end_time.astimezone(timezone),
    }


def has_been_alerted(rotation: dict) -> bool:
    """Check if rotation alert has already been sent.

    Args:
    ----
        rotation (dict): The rotation data.

    Returns:
    -------
        bool: True if the rotation alert has already been sent, False otherwise.

    """

    if not ALERT_FILE.exists():
        return False
    with ALERT_FILE.open("r") as file:
        alerts = json.load(file)
    if any(alert["start_time"] == rotation["start_time"].isoformat() for alert in alerts):
        logger.debug("Rotation has already been alerted. No need to splat again!")
        return True
    return False


def send_notification(rotation: dict, notifier: apprise.Apprise) -> None:
    """Send a notification for the Salmon Run rotation.

    Args:
    ----
        rotation (dict): The rotation data.
        notifier (apprise.Apprise): The Apprise notifier instance.

    Raises:
    ------
        KeyError: If there is a missing key in the rotation data.

    """

    if has_been_alerted(rotation):
        logger.info("Rotation already alerted. Not repeating this wave of Salmonids.")
        return

    # noinspection PyBroadException
    try:
        weapons_list = "\n".join(f"Weapon {i + 1}: {weapon}" for i, weapon in enumerate(rotation["weapons"]))
        notification_text = (
            f"Rotation start: {rotation['start_time'].strftime('%A %d %B at %I:%M%p').replace(" 0", " ")}\n"  # The 'replace' is to remove 0 padding the hours
            f"Rotation end: {rotation['end_time'].strftime('%A %d %B at %I:%M%p').replace(" 0", " ")}\n"  # The 'replace' is to remove 0 padding the hours
            f"Map: {rotation['stage']}\n"
            f"Boss: {rotation['boss']}\n"
            f"{weapons_list}\n"
            f"Type: {rotation['type']}\n"
            f"More details: https://splatoon3.ink/salmonrun"
        )
        logger.info(notification_text)
        notifier.notify(body=notification_text)
        _update_alert_file(rotation)
    except KeyError:
        logger.exception("Missing key in rotation data. Looks like a Salmonid snatched it!")
    except Exception:  # noqa: BLE001
        logger.exception("Error sending notification. Splatted while sending alert!")


def _update_alert_file(rotation: dict) -> None:
    """Record alerted rotations in a file.

    Args:
    ----
        rotation (dict): The rotation data.

    """

    alerts = []
    if ALERT_FILE.exists():
        with ALERT_FILE.open("r") as file:
            alerts = json.load(file)
    # Add the new alert
    alerts.append({"start_time": rotation["start_time"].isoformat()})
    with ALERT_FILE.open("w") as file:
        # noinspection PyTypeChecker
        json.dump(alerts[-3:], file, indent=4)  # Keep only last 3 alerts
    logger.debug("Alert file updated. Keeping track of the latest Salmon Run rotations.")


def notify_failure(notifier: apprise.Apprise) -> None:
    """Send a notification if there are failures for more than 6 hours.

    Args:
    ----
        notifier (apprise.Apprise): The Apprise notifier instance.

    """

    try:
        notification = "Salmon Run Notifier has encountered failures for more than 6 hours. The Salmonids are overwhelming us!"
        logger.warning(notification)
        notifier.notify(body=notification)
    except Exception as e:  # noqa: BLE001
        logger.exception(f"Failed to send failure notification: {e}. Notification splatted by a Charger!")


def local_file(file_name: str, *, resources_folder: bool = False) -> Path:
    """Pull file from exe if packaged with PyInstaller, otherwise pull file from next to Salmon Run Notifier.

    Args:
    ----
        file_name (str): The file name.
        resources_folder (bool): Whether to pull from the 'resources' subfolder.

    Returns:
        The path to the local file.

    """

    if resources_folder:
        file_name = Path("resources") / file_name
    if hasattr(sys, "_MEIPASS"):
        # noinspection PyProtectedMember
        return Path(sys._MEIPASS) / file_name   # noqa: SLF001  -  Packaged with PyInstaller, pull from exe.
    return Path.cwd() / file_name   # Not packaged with PyInstaller, pull from next to the Python file


def setup_logger(*, simple_console_logging: bool) -> None:
    """Configure loggers for the notifier.

    Args:
    ----
        simple_console_logging (bool): Whether to enable simpler console logging.

    """

    if simple_console_logging:
        logger.configure(handlers=[{"sink": sys.stderr, "level": "INFO", "format": "<level>{time:YYYY-MM-DD HH:mm:ss} [{level}]</level> - {message}"}])
    else:
        logger.configure(handlers=[{"sink": sys.stderr, "level": "DEBUG", "format": "<level>{time:YYYY-MM-DD HH:mm:ss} [{level}]</level> - {name}:{function}:{line} - {message}"}])
    logger.add(Path.cwd() / "config" / "logs" / "salmon_notifier.log", level="TRACE", format="{time:YYYY-MM-DD at HH:mm:ss} | {level} | {name}:{function}:{line} | {message}", rotation="50 MB", compression="zip", retention="1 week")


def setup_notifiers(apprise_paths: list[str]) -> apprise.Apprise:
    """Configure notifiers to send alerts to.

    Args:
    ----
        apprise_paths (list[str]): A list of apprise paths to notify.

    Returns:
    -------
        apprise.Apprise: The apprise notifier instance.

    """

    notifier = apprise.Apprise()
    for path in apprise_paths:
        if path == "tgram://your_telegram_token/your_chat_id":
            logger.info("You need to specify an apprise path in salmon_config.toml")
            time.sleep(10)
            sys.exit(66)
        notifier.add(path)
    return notifier


# noinspection PyUnusedLocal
def terminate(sigterm: signal.SIGTERM, frame: types.FrameType) -> None:  # noqa: ARG001
    """Terminate cleanly. Needed for respecting 'docker stop'.

    Args:
    ----
        sigterm (signal.Signal): The termination signal.
        frame: The execution frame.

    """

    logger.info(f"Termination signal received at {datetime.datetime.now()}.")  # noqa: DTZ005
    sys.exit(0)


def main() -> None:
    """Monitor and notify of Salmon Run rotations."""
    signal.signal(signal.SIGTERM, terminate)
    config = load_config(config_path=Path("config/salmon_config.toml"), template_path=local_file("salmon_config_template.toml", resources_folder=True))
    setup_logger(simple_console_logging=config.simple_console_logger)

    logger.info("Configuration loaded. Ready to ink some turf!")

    local_timezone = tz.gettz(config.local_timezone)
    if local_timezone is None:
        logger.info("You need to specify your local timezone in salmon_config.toml")
        time.sleep(10)
        sys.exit(66)
    logger.trace(f"Loaded timezone: {local_timezone}")
    logger.trace(f"Current time in {local_timezone}: {datetime.datetime.now(local_timezone)}")
    failure_threshold = config.failure_threshold_hours * 3600  # Convert hours to seconds

    notifiers = setup_notifiers(config.apprise_paths)

    failure_start_time = None

    while True:
        # noinspection PyBroadException
        try:
            # noinspection PyTypeChecker
            schedules = tidy_schedules(get_schedules(config.schedules_api), local_timezone)
            if not schedules:
                if failure_start_time is None:
                    failure_start_time = time.time()
                elif time.time() - failure_start_time > failure_threshold:
                    notify_failure(notifiers)
                    failure_start_time = None  # Reset failure start time after notification
                logger.warning("No schedules available, retrying in 60 seconds. The Salmonids are hiding!")
                time.sleep(60)
                continue

            failure_start_time = None  # Reset failure start time on success
            _sleep_until_rotation(next_rotation=schedules[0], config=config, local_timezone=local_timezone, notifiers=notifiers)

        except Exception:  # noqa: BLE001
            logger.exception("An error occurred in the main loop. Waiting for a minute then trying again. Ran out of ink!")
            time.sleep(60)  # Wait a bit before retrying


def _sleep_until_rotation(next_rotation: dict[str, Any], config: Config, local_timezone: tz.tz, notifiers: apprise.Apprise) -> None:
    """Sleep until the next rotation starts.

    Args:
    ----
        next_rotation (dict): The next rotation.
        config (Config): The config instance.
        local_timezone (tz.tz): The local timezone.
        notifiers (apprise.Apprise): The apprise notifier instance.

    """

    if next_rotation["seconds_until_rotation"] <= 0:
        # Rotation is in the past
        if _is_within_quiet_hours(datetime.datetime.now(tz=local_timezone), config):
            sleep_time = _calculate_sleep_until_quiet_end(datetime.datetime.now(tz=local_timezone), config, local_timezone)  # It's currently quiet hours, wait until the end of quiet hours
        else:
            sleep_time = 0
    elif _is_within_quiet_hours(next_rotation["start_time"], config):
        logger.info(f"Next rotation occurs during quiet hours ({next_rotation["start_time"].strftime("%A %d %B at %H:%M")}), alert will be sent at the end of the quiet hours. Don't get cooked, stay off the hook!")
        # noinspection PyTypeChecker
        sleep_time = _calculate_sleep_until_quiet_end(next_rotation["start_time"], config, local_timezone)
    else:
        logger.info("Next rotation occurs outside quiet hours, alert will be sent at the moment of rotation. Time to ink up!")
        sleep_time = next_rotation["seconds_until_rotation"]

    # Calculate days, hours, minutes, and seconds
    days, remainder = divmod(sleep_time, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    notification_send_time = datetime.datetime.now(tz=local_timezone) + datetime.timedelta(seconds=sleep_time)
    notification_send_time_str = notification_send_time.strftime("%A %d %B at %I:%M%p").replace(" 0", " ")  # The 'replace' is to remove 0 padding the hours
    if sleep_time > 0:
        logger.info(f"Notifying in {int(days)} days, {int(hours)} hours, {int(minutes)} minutes, and {int(seconds)} seconds (on {notification_send_time_str}). Get ready to splat!")
        time.sleep(sleep_time)
    else:
        logger.info(f"Notifying immediately (rotation started {notification_send_time_str}). Ink it up!")
    send_notification(next_rotation, notifiers)


def _is_within_quiet_hours(check_time: datetime.datetime, config: Config) -> bool:
    """Check if rotation falls within quiet hours.

    Args:
    ----
        check_time: (datetime.datetime): The time to check if within quiet hours.
        config (Config): Configuration settings containing quiet hour start and end times.

    Returns:
    -------
        Whether the rotation falls within quiet hours.

    """

    return config.alert_quiet_start <= check_time.hour < config.alert_quiet_end


def _calculate_sleep_until_quiet_end(reference_time: datetime.datetime, config: Config, timezone: tz.tzfile) -> int:
    """Calculate time to wait until quiet hours end.

    Args:
    ----
    reference_time (datetime.datetime): The time from which to calculate the wait time until the end of quiet hours.
    config (Config): Configuration settings containing quiet hour start and end times.
    timezone (tz.tzfile): The local timezone.

    Returns:
          The number of seconds until the end of the quiet hours.

    """

    # Set quiet end time to today's date with quiet end hour, in the same timezone
    quiet_end_time = reference_time.replace(hour=config.alert_quiet_end, minute=0, second=0)

    # If quiet end time is in the past (for today), add a day to move it to the next day
    if quiet_end_time <= datetime.datetime.now(timezone):
        quiet_end_time += datetime.timedelta(days=1)

    # Calculate the seconds until the end of quiet hours
    return int((quiet_end_time - datetime.datetime.now(timezone)).total_seconds())


if __name__ == "__main__":
    main()
