import json
from urllib.parse import urljoin, urlparse

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class TacnodeClient:
    def __init__(
        self,
        endpoint: str,
        region_endpoint: str,
        username: str,
        password: str,
    ):
        self._endpoint = endpoint.rstrip("/")
        self._region_endpoint = region_endpoint.rstrip("/")
        self._username = username
        self._password = password
        self._logged_in = False
        self._token = None

    def _url(self, path: str) -> str:
        return urljoin(self._endpoint + "/", path.lstrip("/"))

    def _region_url(self, path: str) -> str:
        return urljoin(self._region_endpoint + "/", path.lstrip("/"))

    def _ensure_logged_in(self):
        if not self._logged_in:
            self.login()

    def login(self):
        resp = requests.post(
            self._url("/api/v1/accounts/self-service/login"),
            json={"identifier": self._username, "password": self._password},
        )
        resp.raise_for_status()
        self._logged_in = True

        payload = resp.json()
        self._token = payload["token"]
        return True

    def list_datasync_jobs(
        self,
        context_lake_id: str,
        search_params: dict | None = None,
    ):
        self._ensure_logged_in()
        if search_params is None:
            search_params = {"portType": "IMPORT", "pageNum": 1, "pageSize": 100}
        search_param = json.dumps(search_params, separators=(",", ":"))
        resp = requests.get(
            self._region_url(f"/api/v1/contextlakes/{context_lake_id}/datasync/jobs"),
            params={"searchParam": search_param},
            headers={
                "Authorization": f"Bearer {self._token}",
            },
        )
        resp.raise_for_status()
        return resp.json()

    def pause_datasync_job(
        self,
        context_lake_id: str,
        job_id: str,
        instance_id: str,
        is_drain: bool = True,
    ):
        self._ensure_logged_in()
        resp = requests.put(
            self._region_url(
                f"/api/v1/contextlakes/{context_lake_id}/datasync/jobs/"
                f"{job_id}/instances/{instance_id}/state",
            ),
            json={"targetState": "PAUSED", "isDrain": is_drain},
            headers={
                "Authorization": f"Bearer {self._token}",
            },
        )
        resp.raise_for_status()
        return resp.json()

    def resume_datasync_job(
        self,
        context_lake_id: str,
        job_id: str,
        instance_id: str,
        use_latest_configuration: bool = False,
    ):
        self._ensure_logged_in()
        resp = requests.put(
            self._region_url(
                f"/api/v1/contextlakes/{context_lake_id}/datasync/jobs/"
                f"{job_id}/instances/{instance_id}/state"
            ),
            json={
                "targetState": "RUNNING",
                "useLatestConfiguration": use_latest_configuration,
            },
            headers={
                "Authorization": f"Bearer {self._token}",
            },
        )
        resp.raise_for_status()
        return resp.json()

    def query_datasync_job(self, context_lake_id: str, job_id: str):
        self._ensure_logged_in()
        resp = requests.get(
            self._region_url(
                f"/api/v1/contextlakes/{context_lake_id}/datasync/jobs/{job_id}"
            ),
            headers={
                "IgnoreError": "IgnoreError",
                "Authorization": f"Bearer {self._token}",
            },
        )
        resp.raise_for_status()
        return resp.json()

    def query_datasync_job_instance_state(
        self,
        context_lake_id: str,
        job_id: str,
        instance_id: str,
    ):
        self._ensure_logged_in()
        resp = requests.get(
            self._region_url(
                f"/api/v1/contextlakes/{context_lake_id}/datasync/jobs/"
                f"{job_id}/instances/{instance_id}"
            ),
            headers={
                "IgnoreError": "IgnoreError",
                "Authorization": f"Bearer {self._token}",
            },
        )
        resp.raise_for_status()
        return resp.json()
