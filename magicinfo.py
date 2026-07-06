import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv


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
        "api_key": os.getenv("MAGICINFO_API_KEY", ""),
        "content_group": os.getenv("MAGICINFO_CONTENT_GROUP", "default"),
        "schedule_group": os.getenv("MAGICINFO_SCHEDULE_GROUP", "Расписание"),
        "schedule_name_1": os.getenv("MAGICINFO_SCHEDULE_NAME_1", "Расписание 1"),
        "schedule_name_2": os.getenv("MAGICINFO_SCHEDULE_NAME_2", "Расписание 2"),
        "device_type": os.getenv("MAGICINFO_DEVICE_TYPE", "SPLAYER"),
        "device_type_version": float(os.getenv("MAGICINFO_DEVICE_TYPE_VERSION", "2.0")),
        "debug": _env_bool("MAGICINFO_DEBUG"),
    }


class MagicInfoError(Exception):
    pass


class MagicInfoClient:
    def __init__(self, config):
        self._base = f"http://{config['host']}:{config['port']}/MagicInfo"
        self._headers = {"api_key": config["api_key"]}
        self._content_group_name = config["content_group"]
        self._schedule_group_name = config["schedule_group"]
        self._schedule_name_1 = config["schedule_name_1"]
        self._schedule_name_2 = config["schedule_name_2"]
        self._device_type = config["device_type"]
        self._device_type_version = config["device_type_version"]
        self._debug = config["debug"]

    def _request(self, method, path, params=None, json_body=None, data=None, files=None, timeout=30):
        url = f"{self._base}{path}"

        if self._debug:
            print(f"[DEBUG] {method} {url}")
            if params:
                print(f"[DEBUG]   params: {json.dumps(params, ensure_ascii=False)}")
            if json_body:
                print(f"[DEBUG]   body:   {json.dumps(json_body, ensure_ascii=False)}")
            if data:
                print(f"[DEBUG]   data:   {json.dumps(data, ensure_ascii=False)}")
            if files:
                print(f"[DEBUG]   files:  {list(files.keys())}")

        r = requests.request(
            method, url, headers=self._headers,
            params=params, json=json_body, data=data, files=files,
            timeout=timeout,
        )

        if self._debug:
            ct = r.headers.get("Content-Type", "")
            print(f"[DEBUG]   status: {r.status_code}  content-type: {ct}")
            raw = r.text[:1000]
            if r.text:
                print(f"[DEBUG]   raw:     {raw}")

        try:
            body = r.json()
        except ValueError:
            if not r.ok:
                print(f"[ERROR] {method} {url}  HTTP {r.status_code}: {r.text[:500]}")
                r.raise_for_status()
            raise MagicInfoError(
                f"Expected JSON response but got empty body or non-JSON content.\n"
                f"  Method: {method} {url}\n"
                f"  Status: {r.status_code}\n"
                f"  Content-Type: {r.headers.get('Content-Type', 'unknown')}\n"
                f"  Raw (first 500 chars): {r.text[:500]}"
            )

        if self._debug:
            body_preview = json.dumps(body, ensure_ascii=False, default=str)
            if len(body_preview) > 2000:
                body_preview = body_preview[:2000] + "..."
            print(f"[DEBUG]   response: {body_preview}")

        if r.ok and isinstance(body, dict) and body.get("status") == "Error":
            code = body.get("errorCode", "?")
            message = body.get("errorMessage", "unknown error")
            raise MagicInfoError(
                f"MagicINFO returned error (code={code}): {message}\n"
                f"  Method: {method} {url}\n"
                f"  Body: {json.dumps(json_body, ensure_ascii=False, default=str) if json_body else 'none'}"
            )

        if not r.ok:
            raise MagicInfoError(
                f"HTTP {r.status_code} on {method} {url}:\n{json.dumps(body, ensure_ascii=False, default=str)[:500]}"
            )

        return body

    def _get(self, path, params=None):
        return self._request("GET", path, params=params)

    def _post(self, path, json_body=None, data=None, files=None):
        return self._request("POST", path, json_body=json_body, data=data, files=files, timeout=60)

    def _put(self, path, json_body=None):
        return self._request("PUT", path, json_body=json_body)

    def _resolve_content_group_id(self):
        resp = self._get("/restapi/v1.0/cms/contents/groups")
        items = resp.get("items", [])
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
        for g in items:
            if g.get("groupName") == self._schedule_group_name:
                return g.get("groupId")
        available = [g.get("groupName", "?") for g in items]
        raise MagicInfoError(
            f"Schedule group '{self._schedule_group_name}' not found in MagicINFO.\n"
            f"  Available schedule groups: {', '.join(available) if available else '(none)'}"
        )

    def _upload_image(self, file_path, group_id):
        with open(file_path, "rb") as f:
            resp = self._post(
                "/restapi/v1.0/cms/contents/files",
                data={"contentType": "IMAGE", "groupId": str(group_id)},
                files={"file": (Path(file_path).name, f, "image/jpeg")},
            )
        items = resp.get("items", [])
        if items:
            return items[0].get("contentId")
        raise MagicInfoError(
            f"Failed to upload '{file_path}': no contentId in response.\n"
            f"  Response: {json.dumps(resp, ensure_ascii=False, default=str)[:500]}"
        )

    def _find_schedule(self, name, group_id):
        resp = self._post(
            "/restapi/v1.0/dms/schedule/contents/filter",
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
        for item in items:
            item_name = item.get("programName") or item.get("name") or ""
            if item_name == name:
                return item.get("programId") or item.get("id")
        return None

    def _build_schedule_payload(self, schedule_name, content_id, date_str, group_id):
        return {
            "scheduleName": schedule_name,
            "scheduleGroupId": str(group_id),
            "deviceType": self._device_type,
            "deviceTypeVersion": self._device_type_version,
            "itemList": [{
                "contentId": content_id,
                "scheduleType": "LFD",
                "startDate": date_str,
                "stopDate": date_str,
                "startTime": "00:00:00",
                "repeatType": "once",
                "duration": "86400",
                "playerMode": "single",
            }],
        }

    def _create_schedule(self, payload):
        return self._post("/restapi/v1.0/dms/schedule/contents", json_body=payload)

    def _update_schedule(self, program_id, payload):
        self._put(f"/restapi/v1.0/dms/schedule/contents/{program_id}", json_body=payload)

    def _deploy_schedule(self, program_id, payload):
        self._put(f"/restapi/v1.0/dms/schedule/contents/{program_id}/deploy", json_body=payload)

    def upload_and_schedule(self, image_path_1, image_path_2, date_obj):
        date_str = date_obj.strftime("%Y-%m-%d")

        print(f"\n--- MagicINFO: resolving groups ---")
        content_group_id = self._resolve_content_group_id()
        schedule_group_id = self._resolve_schedule_group_id()
        print(f"  Content group ID: {content_group_id}")
        print(f"  Schedule group ID: {schedule_group_id}")

        print(f"\n--- MagicINFO: uploading images ---")
        content_id_1 = self._upload_image(image_path_1, content_group_id)
        print(f"  Uploaded '{image_path_1}' -> contentId={content_id_1}")
        content_id_2 = self._upload_image(image_path_2, content_group_id)
        print(f"  Uploaded '{image_path_2}' -> contentId={content_id_2}")

        images = [
            (content_id_1, self._schedule_name_1),
            (content_id_2, self._schedule_name_2),
        ]

        print(f"\n--- MagicINFO: scheduling ---")
        for content_id, schedule_name in images:
            payload = self._build_schedule_payload(
                schedule_name, content_id, date_str, schedule_group_id
            )

            existing_id = self._find_schedule(schedule_name, schedule_group_id)

            if existing_id:
                print(f"  Updating schedule '{schedule_name}' (programId={existing_id})")
                self._update_schedule(existing_id, payload)
                self._deploy_schedule(existing_id, payload)
            else:
                print(f"  Creating schedule '{schedule_name}'")
                self._create_schedule(payload)
                created_id = self._find_schedule(schedule_name, schedule_group_id)
                if created_id:
                    self._deploy_schedule(created_id, payload)

        print("  Done.")


def upload_schedule_images(image_paths, date_obj):
    config = load_config()
    if config is None:
        print("MagicINFO integration disabled — skipping upload.")
        return

    client = MagicInfoClient(config)
    client.upload_and_schedule(image_paths[0], image_paths[1], date_obj)
