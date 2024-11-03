"""Runs the main code for the Salmon Run Notifier."""
import datetime
import json
import shutil
import signal
import sys
import time
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import apprise
import requests
import tomllib
from dateutil import tz
from loguru import logger

alert_file = Path("config/last.alert")


@dataclass
class Config:
    """Configuration settings for the Salmon Run Notifier.

    Attributes
    ----------
        local_timezone (str): The local timezone for the notifier.
        alert_quiet_start (int): The start hour of the quiet period.
        alert_quiet_end (int): The end hour of the quiet period.
        apprise_paths (list): The Apprise notification paths in a list.
        schedules_api (str): The API endpoint for fetching Salmon Run schedules.
        failure_threshold_hours (int): The number of hours to wait before notifying of consistent failures.

    """

    local_timezone: str
    alert_quiet_start: int
    alert_quiet_end: int
    apprise_paths: list
    schedules_api: str
    failure_threshold_hours: int


def load_config(config_path: Path, config_template_path: Path) -> Config:
    """Load configuration from a TOML file.

    Args:
    ----
        config_path (Path): The path to the configuration file.
        config_template_path (Path): The path to the configuration template file.

    Returns:
    -------
        Config: The loaded configuration settings.

    Raises:
    ------
        FileNotFoundError: If the configuration file is not found.
        KeyError: If any required configuration setting is missing.
        tomllib.TOMLDecodeError: If there is an error parsing the configuration file.

    """
    try:
        if config_path.exists() is False:
            logger.info("Configuration doesn't exist. Copying template.")
            config_path.parent.mkdir(parents=True, exist_ok=True)  # Make the config directory if it doesn't exist.
            shutil.copy(config_template_path, config_path)
            logger.info(f"Configuration template copied to {config_template_path}. Edit the configuration and restart the program. Exiting the lobby in 10 seconds.")
            time.sleep(10)
            sys.exit(66)  # Equivalent to 'EX_NOINPUT'
        with config_path.open("rb") as f:
            config_data = tomllib.load(f)
        settings = config_data["settings"]
        logger.info("Configuration loaded. Ready to ink some turf!")
        return Config(
            local_timezone=settings["local_timezone"],
            alert_quiet_start=settings["alert_quiet_start"],
            alert_quiet_end=settings["alert_quiet_end"],
            apprise_paths=settings["apprise_paths"],
            schedules_api=settings["schedules_api"],
            failure_threshold_hours=settings["failure_threshold_hours"],
        )
    except (FileNotFoundError, KeyError, tomllib.TOMLDecodeError) as e:
        logger.exception(f"Error loading configuration: {e}. Exiting the lobby.")
        sys.exit(1)


def get_schedules(schedules_api: str) -> Dict[str, Any]:  # noqa: FA100
    """Fetch and return the current and upcoming Salmon Run schedules.

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
    cache_path = Path("config/cache.temp")
    if cache_path.exists():
        with cache_path.open("r") as cache_file:
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
                return {
                    "Regular": cached_data["regularSchedules"]["nodes"],
                    "Big Run": cached_data["bigRunSchedules"]["nodes"],
                    "Eggstra Work": cached_data["teamContestSchedules"]["nodes"],
                }

    try:
        with Path("pyproject.toml").open("rb") as pyproject:
            version = tomllib.load(pyproject)["tool"]["poetry"]["version"]
        response = requests.get(schedules_api, headers={"User-Agent": f"Salmon Run Notifier - Version {version}"})  # noqa: S113
        response.raise_for_status()
        schedules = response.json()["data"]["coopGroupingSchedule"]
        with cache_path.open("w") as cache_file:
            # noinspection PyTypeChecker
            json.dump(schedules, cache_file)
        logger.debug("Fetched schedules successfully and updated cache. Ready to splat some Salmonids!")
        return {
            "Regular": schedules["regularSchedules"]["nodes"],
            "Big Run": schedules["bigRunSchedules"]["nodes"],
            "Eggstra Work": schedules["teamContestSchedules"]["nodes"],
        }
    except requests.RequestException as e:
        logger.exception(f"Failed to fetch schedules: {e}. The Salmonids are causing trouble!")
        return {"Regular": [], "Big Run": [], "Eggstra Work": []}


def tidy_schedules(schedules: Dict[str, Any], local_timezone: tz.tzfile) -> list:  # noqa: FA100
    """Reformat and tidy the schedules.

    Args:
    ----
        schedules (dict): A dictionary containing the schedules.
        local_timezone (tz.tzfile): The local timezone for the notifier.

    Returns:
    -------
        list: A flattened list of tidied schedules sorted by the time until the next rotation.

    Raises:
    ------
        KeyError: If there is an error accessing schedule data.

    """
    try:
        for schedule_type, rotations in schedules.items():
            for i, rotation in enumerate(rotations):
                start_time = datetime.datetime.fromisoformat(rotation["startTime"])
                end_time = datetime.datetime.fromisoformat(rotation["endTime"])
                updated_rotation = {
                    "seconds_until_rotation": start_time.timestamp() - datetime.datetime.now(tz=datetime.timezone.utc).timestamp(),
                    "stage": rotation["setting"]["coopStage"]["name"],
                    "boss": rotation["setting"]["boss"]["name"] if rotation["setting"]["boss"]["name"] is not None else "Random",
                    "weapons": [weapon["name"] if weapon["__splatoon3ink_id"] != "747937841598fff7" else "Grizzco Random" for weapon in rotation["setting"]["weapons"]],
                    "type": schedule_type,
                    "start_time": start_time.astimezone(local_timezone),
                    "end_time": end_time.astimezone(local_timezone),
                }
                # Remove unnecessary information
                for key in ["setting", "startTime", "endTime", "__splatoon3ink_king_salmonid_guess"]:
                    updated_rotation.pop(key, None)
                # Update the rotation in the schedules dictionary
                schedules[schedule_type][i] = updated_rotation

        # Flatten and sort schedules
        flattened_schedules = sorted(
            [rotation for rotations in schedules.values() for rotation in rotations],
            key=lambda x: x["seconds_until_rotation"],
        )
        logger.debug("Tidied schedules successfully. Ready for the next wave!")
        # Remove currently running rotations only if they have alerted previously
        new_alerts = [rotation for rotation in flattened_schedules if rotation["seconds_until_rotation"] > 0 or has_been_alerted(rotation) is False]

    except KeyError as e:
        logger.exception(f"Key error while tidying schedules: {e}. The Salmonids are messing with the data!")
        return []
    except Exception as e:  # noqa: BLE001
        logger.exception(f"Failed to tidy schedules: {e}. The ink is everywhere!")
        return []
    else:
        return new_alerts


def update_alert_file(rotation: dict) -> None:
    """Update the alert file with the latest alert.

    Args:
    ----
        rotation (dict): The rotation data.

    """
    if alert_file.exists():
        with alert_file.open("r") as file:
            alerts = json.load(file)
    else:
        alerts = []

    # Add the new alert
    alerts.append({"start_time": rotation["start_time"].isoformat()})

    # Keep only the last 3 alerts
    alerts = alerts[-3:]

    with alert_file.open("w") as file:
        # noinspection PyTypeChecker
        json.dump(alerts, file, indent=4)
    logger.debug("Alert file updated. Keeping track of the latest Salmon Run rotations.")


def has_been_alerted(rotation: dict) -> bool:
    """Check if the rotation has already been alerted.

    Args:
    ----
        rotation (dict): The rotation data.

    Returns:
    -------
        bool: True if the rotation has been alerted, False otherwise.

    """
    if not alert_file.exists():
        return False

    with alert_file.open("r") as file:
        alerts = json.load(file)

    for alert in alerts:
        if alert["start_time"] == rotation["start_time"].isoformat():
            logger.debug("Rotation has already been alerted. No need to splat again!")
            return True

    return False


def send_notification(rotation: dict, notifier: apprise.Apprise) -> None:
    """Send a notification for the given rotation, and check and update the alert file.

    Args:
    ----
        rotation (dict): The rotation data.
        notifier (apprise.Apprise): The Apprise notifier instance.

    Raises:
    ------
        KeyError: If there is a missing key in the rotation data.

    """
    if has_been_alerted(rotation):
        logger.info("Notification already sent for this rotation. Skipping this wave of Salmonids.")
        return
    try:
        weapons_list = "\n".join(f"Weapon {i + 1}: {weapon}" for i, weapon in enumerate(rotation["weapons"]))
        notification = (
            f"Salmon Run rotation start: {rotation['start_time'].strftime('%A %#d %B at %#I:%M%p')}\n"
            f"Rotation end: {rotation['end_time'].strftime('%A %#d %B at %#I:%M%p')}\n"
            f"Map: {rotation['stage']}\n"
            f"{weapons_list}\n"
            f"Boss: {rotation['boss']}\n"
            f"Type: {rotation['type']}\n"
            f"More details: https://splatoon3.ink/salmonrun"
        )
        logger.info(notification)
        notifier.notify(body=notification)
        update_alert_file(rotation)
    except KeyError as e:
        logger.exception(f"Missing key in rotation data: {e}. Looks like a Salmonid snatched it!")
    except Exception as e:  # noqa: BLE001
        logger.exception(f"Failed to send notification: {e}. Splatted while sending alert!")


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


# noinspection PyUnusedLocal
def terminate(sigterm: signal.SIGTERM, frame: types.FrameType) -> None:  # noqa: ARG001
    """Terminate cleanly. Needed for stopping swiftly when docker sends the command to stop.

    Args:
    ----
        sigterm (signal.Signal): The termination signal.
        frame: The execution frame.

    """
    logger.info(f"Termination signal sent: {datetime.datetime.now()}")  # noqa: DTZ005
    sys.exit(0)


def main() -> None:
    """Run the main loop."""
    signal.signal(signal.SIGTERM, terminate)
    config_path = Path.cwd() / "config" / "salmon_config.toml"
    config_template_path = Path.cwd() / "salmon_config_template.toml"
    config = load_config(config_path, config_template_path)

    local_timezone = tz.gettz(config.local_timezone)
    failure_threshold = config.failure_threshold_hours * 3600  # Convert hours to seconds

    notifier = apprise.Apprise()
    for notification_destination in config.apprise_paths:
        notifier.add(notification_destination)
    failure_start_time = None

    while True:
        try:
            schedules = tidy_schedules(get_schedules(config.schedules_api), local_timezone)
            if not schedules:
                if failure_start_time is None:
                    failure_start_time = time.time()
                elif time.time() - failure_start_time > failure_threshold:
                    notify_failure(notifier)
                    failure_start_time = None  # Reset failure start time after notification
                logger.warning("No schedules available, retrying in 60 seconds. The Salmonids are hiding!")
                time.sleep(60)
                continue

            failure_start_time = None  # Reset failure start time on success
            next_rotation = schedules[0]
            next_start_hour = next_rotation["start_time"].hour

            if config.alert_quiet_start <= next_start_hour < config.alert_quiet_end:
                logger.info(f"Next rotation occurs during quiet hours ({next_rotation["start_time"].strftime("%A %d %B at %H:%M")}), alert will be sent at the end of the quiet hours. Don't get cooked, stay off the hook!")
                alert_time = next_rotation["start_time"].replace(hour=config.alert_quiet_end, minute=0)
                sleep_seconds = alert_time.timestamp() - datetime.datetime.now(tz=local_timezone).timestamp()
            else:
                logger.info("Next rotation occurs outside quiet hours, alert will be sent at the moment of rotation. Time to ink up!")
                sleep_seconds = next_rotation["seconds_until_rotation"]

            # Calculate days, hours, minutes, and seconds
            days, remainder = divmod(sleep_seconds, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)
            notification_send_time = datetime.datetime.now(tz=local_timezone) + datetime.timedelta(seconds=sleep_seconds)
            notification_send_time_str = notification_send_time.strftime("%A %#d %B at %#I:%M%p")
            if sleep_seconds > 0:
                logger.info(f"Notifying in {int(days)} days, {int(hours)} hours, {int(minutes)} minutes, and {int(seconds)} seconds (on {notification_send_time_str}). Get ready to splat!")
                time.sleep(sleep_seconds)
            else:
                logger.info(f"Notifying immediately (rotation started {notification_send_time_str}). Ink it up!")
            send_notification(next_rotation, notifier)
        except Exception as e:  # noqa: BLE001
            logger.exception(f"An error occurred in the main loop. Waiting for a minute then trying again: {e}. Ran out of ink!")
            time.sleep(60)  # Wait a bit before retrying


if __name__ == "__main__":
    main()
