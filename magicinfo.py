import json
import logging
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _env_bool(key, default=False):
    return os.getenv(key, str(default)).strip().lower() in ("true", "1", "yes")


def load_config():
    env_path = Path(".env")
    if env_path.exists():
        load_dotenv(env_path)

    if not _env_bool("MAGICINFO_ENABLED"):
        return None

    return {
        "host": os.getenv("MAGICINFO_HOST", ""),
        "port": int(os.getenv("MAGICINFO_PORT", "7001")),
        "username": os.getenv("MAGICINFO_USERNAME", "admin"),
        "password": os.getenv("MAGICINFO_PASSWORD", ""),
        "content_group": os.getenv("MAGICINFO_CONTENT_GROUP", "default"),
        "schedule_group": os.getenv("MAGICINFO_SCHEDULE_GROUP", "Расписание"),
        "schedule_name_1": os.getenv("MAGICINFO_SCHEDULE_NAME_1", "Расписание 1"),
        "schedule_name_2": os.getenv("MAGICINFO_SCHEDULE_NAME_2", "Расписание 2"),
        "device_type": os.getenv("MAGICINFO_DEVICE_TYPE", "LPLAYER"),
        "device_type_version": float(os.getenv("MAGICINFO_DEVICE_TYPE_VERSION", "1.0")),
        "device_group_ids": os.getenv("MAGICINFO_DEVICE_GROUP_IDS", ""),
    }


class MagicInfoError(Exception):
    pass


class MagicInfoClient:
    def __init__(self, config):
        self._base = f"http://{config['host']}:{config['port']}/MagicInfo"
        self._username = config["username"]
        self._password = config["password"]
        self._content_group_name = config["content_group"]
        self._schedule_group_name = config["schedule_group"]
        self._schedule_name_1 = config["schedule_name_1"]
        self._schedule_name_2 = config["schedule_name_2"]
        self._device_type = config["device_type"]
        self._device_type_version = config["device_type_version"]
        self._device_group_ids = config["device_group_ids"]
        self._token = None

    def _authenticate(self):
        resp = requests.post(
            f"{self._base}/restapi/v2.0/auth",
            headers={"Content-Type": "application/json"},
            json={"username": self._username, "password": self._password, "grantType": "password"},
            timeout=30,
        )
        if not resp.ok:
            raise MagicInfoError(
                f"Authentication failed (HTTP {resp.status_code}): {resp.text[:300]}"
            )
        data = resp.json()
        token = data.get("token")
        if not token:
            raise MagicInfoError(
                f"No token in auth response: {json.dumps(data, ensure_ascii=False)[:300]}"
            )
        self._token = token

    def _request(self, method, path, params=None, json_body=None, data=None, files=None, timeout=30):
        if self._token is None:
            self._authenticate()

        url = f"{self._base}{path}"
        headers = {"api_key": self._token}

        logger.debug("[DEBUG] %s %s", method, url)
        if params:
            logger.debug("[DEBUG]   params: %s", json.dumps(params, ensure_ascii=False))
        if json_body:
            body_str = json.dumps(json_body, ensure_ascii=False, default=str)
            if len(body_str) > 2000:
                body_str = body_str[:2000] + "..."
            logger.debug("[DEBUG]   body:   %s", body_str)
        if data:
            safe_data = {k: v for k, v in data.items()}
            logger.debug("[DEBUG]   data:   %s", json.dumps(safe_data, ensure_ascii=False))
        if files:
            logger.debug("[DEBUG]   files:  %s", list(files.keys()))

        r = requests.request(
            method, url, headers=headers,
            params=params, json=json_body, data=data, files=files,
            timeout=timeout,
        )

        logger.debug("[DEBUG]   status: %s  content-type: %s", r.status_code, r.headers.get("Content-Type", ""))
        raw = r.text[:2000]
        if raw:
            logger.debug("[DEBUG]   raw:     %s", raw)

        try:
            body = r.json()
        except ValueError:
            if not r.ok:
                logger.error("[ERROR] %s %s  HTTP %s: %s", method, url, r.status_code, r.text[:500])
                r.raise_for_status()
            raise MagicInfoError(
                f"Expected JSON response but got empty body or non-JSON content.\n"
                f"  Method: {method} {url}\n"
                f"  Status: {r.status_code}\n"
                f"  Content-Type: {r.headers.get('Content-Type', 'unknown')}\n"
                f"  Raw (first 500 chars): {r.text[:500]}"
            )

        if r.ok and isinstance(body, dict) and body.get("status") == "Error":
            code = body.get("errorCode", "?")
            message = body.get("errorMessage", "unknown error")
            raise MagicInfoError(
                f"MagicINFO returned error (code={code}): {message}\n"
                f"  Method: {method} {url}"
            )

        if not r.ok:
            err_body = json.dumps(body, ensure_ascii=False, default=str)[:500] if body else "empty"
            raise MagicInfoError(
                f"HTTP {r.status_code} on {method} {url}:\n{err_body}"
            )

        return body

    def _get(self, path, params=None):
        return self._request("GET", path, params=params)

    def _post(self, path, json_body=None, data=None, files=None):
        return self._request("POST", path, json_body=json_body, data=data, files=files, timeout=60)

    def _put(self, path, json_body=None):
        return self._request("PUT", path, json_body=json_body)

    def _delete(self, path):
        return self._request("DELETE", path)

    def _resolve_content_group_id(self):
        resp = self._get("/restapi/v1.0/cms/contents/groups")
        items = resp.get("items", [])
        if isinstance(items, dict):
            items = items.get("data", [])
        if not isinstance(items, list):
            items = []
        for g in items:
            if g.get("groupName") == self._content_group_name:
                return g.get("groupId")
        available = [g.get("groupName", "?") for g in items]
        raise MagicInfoError(
            f"Content group '{self._content_group_name}' not found in MagicINFO.\n"
            f"  Available content groups: {', '.join(available) if available else '(none)'}"
        )

    def _resolve_schedule_group_id(self):
        resp = self._get("/restapi/v1.0/dms/schedule/contents/groups")
        items = resp.get("items", [])
        if isinstance(items, dict):
            items = items.get("data", [])
        if not isinstance(items, list):
            items = []

        for g in items:
            if g.get("groupName") == self._schedule_group_name:
                return g.get("groupId")

        for g in items:
            children = self._get_child_schedule_groups(g.get("groupId"))
            for child in children:
                if child.get("groupName") == self._schedule_group_name:
                    return child.get("groupId")

        available = [g.get("groupName", "?") for g in items]
        raise MagicInfoError(
            f"Schedule group '{self._schedule_group_name}' not found in MagicINFO.\n"
            f"  Available root schedule groups: {', '.join(available) if available else '(none)'}"
        )

    def _get_child_schedule_groups(self, group_id):
        resp = self._get(f"/restapi/v1.0/dms/schedule/contents/groups/{group_id}/child")
        items = resp.get("items", [])
        if isinstance(items, dict):
            items = items.get("data", [])
        if not isinstance(items, list):
            return []
        return items

    def _upload_image(self, file_path, group_id):
        with open(file_path, "rb") as f:
            resp = self._post(
                "/restapi/v1.0/cms/contents/files",
                data={"contentType": "IMAGE", "groupId": str(group_id)},
                files={"file": (Path(file_path).name, f, "image/jpeg")},
            )
        items = resp.get("items", [])
        if isinstance(items, dict):
            items = items.get("data", [])
        if isinstance(items, list) and items:
            return items[0].get("contentId")
        raise MagicInfoError(
            f"Failed to upload '{file_path}': no contentId in response.\n"
            f"  Response: {json.dumps(resp, ensure_ascii=False, default=str)[:500]}"
        )

    def _find_program(self, name, group_id):
        resp = self._post(
            "/restapi/v2.0/dms/content-schedules/filter",
            json_body={
                "searchText": name,
                "groupId": str(group_id),
                "groupType": "ALL",
                "pageSize": 50,
                "startIndex": 1,
                "sortColumn": "modify_date",
                "sortOrder": "desc",
                "deviceType": self._device_type,
            },
        )
        items = resp.get("items", [])
        if isinstance(items, dict):
            items = items.get("data", [])
        if not isinstance(items, list):
            items = []
        for item in items:
            item_name = item.get("programName") or item.get("name") or ""
            if item_name == name:
                return item.get("programId") or item.get("id")
        return None

    def _get_program(self, program_id):
        resp = self._get(f"/restapi/v2.0/dms/content-schedules/{program_id}")
        return resp.get("items", {})

    def _update_program(self, program_id, program_data):
        self._put(f"/restapi/v2.0/dms/content-schedules/{program_id}", json_body=program_data)

    def _republish(self, program_id):
        ids = {}
        if self._device_group_ids:
            ids["ids"] = [g.strip() for g in self._device_group_ids.split(",") if g.strip()]
        self._put(f"/restapi/v2.0/dms/content-schedules/{program_id}/re-publish", json_body=ids)

    def _replace_event_for_date(self, program_data, date_str, content_id, content_name):
        channels = program_data.get("channels")
        if not isinstance(channels, list) or not channels:
            raise MagicInfoError(
                f"Schedule program has no channels. Cannot add events.\n"
                f"  Program data: {json.dumps(program_data, ensure_ascii=False, default=str)[:500]}"
            )
        channel = channels[0]
        frame = channel.get("frame")
        if not isinstance(frame, dict):
            raise MagicInfoError(
                f"Schedule channel has no frame. Cannot add events.\n"
                f"  Channel data: {json.dumps(channel, ensure_ascii=False, default=str)[:500]}"
            )
        frame_id = frame.get("frameId")
        if frame_id is None:
            raise MagicInfoError(
                f"Schedule frame has no frameId. Cannot add events.\n"
                f"  Frame data: {json.dumps(frame, ensure_ascii=False, default=str)[:500]}"
            )

        events = frame.get("events", [])
        events = [e for e in events if e.get("startDate") != date_str]
        events.append({
            "scheduleType": "00",
            "isSafetyLockSet": False,
            "isInfinitePlay": False,
            "startDate": date_str,
            "endDate": date_str,
            "startTime": "00:00:00",
            "durationInSeconds": 86399,
            "repeatType": "ONCE",
            "isAllDayPlay": True,
            "frameId": frame_id,
            "contentId": content_id,
            "contentName": content_name,
            "contentType": "IMAGE",
            "fileSize": 0,
            "playerMode": "single",
            "color": "#80cbff",
            "cifsSlideTransitionTime": 0,
            "isHW": False,
            "priority": len(events) + 1,
        })
        frame["events"] = events

    def upload_and_schedule(self, image_path_1, image_path_2, date_obj):
        date_str = date_obj.strftime("%Y-%m-%d")

        logger.info("--- MagicINFO: authenticating (v2) ---")
        self._authenticate()
        logger.info("  Authenticated as '%s'", self._username)

        logger.info("--- MagicINFO: resolving groups ---")
        content_group_id = self._resolve_content_group_id()
        schedule_group_id = self._resolve_schedule_group_id()
        logger.info("  Content group '%s' -> ID: %s", self._content_group_name, content_group_id)
        logger.info("  Schedule group '%s' -> ID: %s", self._schedule_group_name, schedule_group_id)

        logger.info("--- MagicINFO: uploading images ---")
        content_id_1 = self._upload_image(image_path_1, content_group_id)
        logger.info("  Uploaded '%s' -> contentId=%s", image_path_1, content_id_1)
        content_id_2 = self._upload_image(image_path_2, content_group_id)
        logger.info("  Uploaded '%s' -> contentId=%s", image_path_2, content_id_2)

        images = [
            (content_id_1, self._schedule_name_1, Path(image_path_1).stem),
            (content_id_2, self._schedule_name_2, Path(image_path_2).stem),
        ]

        logger.info("--- MagicINFO: scheduling ---")
        for content_id, schedule_name, image_title in images:
            logger.info("  Processing '%s'...", schedule_name)

            program_id = self._find_program(schedule_name, schedule_group_id)
            if not program_id:
                raise MagicInfoError(
                    f"Schedule '{schedule_name}' not found in MagicINFO group {schedule_group_id}.\n"
                    f"  Create it first via the MagicINFO web UI."
                )

            program = self._get_program(program_id)
            self._replace_event_for_date(program, date_str, content_id, image_title)
            self._update_program(program_id, program)
            logger.info("    Updated events for %s", date_str)

            self._republish(program_id)
            logger.info("    Re-published")

        logger.info("  Done.")


def upload_schedule_images(image_paths, date_obj):
    config = load_config()
    if config is None:
        logger.info("MagicINFO integration disabled — skipping upload.")
        return

    client = MagicInfoClient(config)
    client.upload_and_schedule(image_paths[0], image_paths[1], date_obj)
