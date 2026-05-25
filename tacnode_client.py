import json
import time
from urllib.parse import urljoin

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Refresh token when within 5 minutes of expiry.
_TOKEN_REFRESH_THRESHOLD_S = 300


class TacnodeClient:
    """Client for interacting with the Tacnode API.

    Handles authentication and provides methods for managing datasync jobs
    within context lakes.
    """

    def __init__(
        self,
        endpoint: str,
        region_endpoint: str,
        username: str,
        password: str,
    ):
        """Initialize the Tacnode client.

        Args:
            endpoint: Base URL for authentication-related API calls.
            region_endpoint: Base URL for region-specific API calls.
            username: Login username.
            password: Login password.
        """
        self._endpoint = endpoint.rstrip("/")
        self._region_endpoint = region_endpoint.rstrip("/")
        self._username = username
        self._password = password
        self._logged_in = False
        self._token = None
        self._expired_at = None

    def _url(self, path: str) -> str:
        """Build a full URL from the base endpoint and a relative path."""
        return urljoin(self._endpoint + "/", path.lstrip("/"))

    def _region_url(self, path: str) -> str:
        """Build a full URL from the region endpoint and a relative path."""
        return urljoin(self._region_endpoint + "/", path.lstrip("/"))

    def _ensure_logged_in(self):
        """Trigger login if not already authenticated or token is about to expire."""
        if not self._logged_in:
            self.login()
        elif (
            self._expired_at is not None
            and self._expired_at - time.time() < _TOKEN_REFRESH_THRESHOLD_S
        ):
            self.login()

    def _request(self, method: str, url: str, **kwargs):
        """Wrapper around requests.request that handles auth and error raising.

        Args:
            method: HTTP method (GET, POST, PUT, etc.).
            url: Full URL for the request.
            **kwargs: Passed through to requests.request (params, json, headers, etc.).

        Returns:
            The Response object from requests.
        """
        self._ensure_logged_in()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._token}"
        resp = requests.request(method, url, headers=headers, **kwargs)
        resp.raise_for_status()
        return resp

    def login(self):
        """Authenticate against the Tacnode API and store the session token.

        Returns:
            True when login succeeds.
        """
        resp = requests.post(
            self._url("/api/v1/accounts/self-service/login"),
            json={"identifier": self._username, "password": self._password},
        )
        resp.raise_for_status()
        self._logged_in = True

        payload = resp.json()
        self._token = payload["token"]
        self._expired_at = payload["expiredAt"] / 1000.0
        return True

    def list_datasync_jobs(
        self,
        context_lake_id: str,
        search_params: dict | None = None,
    ):
        """List datasync jobs for a context lake.

        Args:
            context_lake_id: ID of the context lake.
            search_params: Optional dict with search filters. Defaults to
                ``{"portType": "IMPORT", "pageNum": 1, "pageSize": 100}``.

        Returns:
            Parsed JSON response containing the list of jobs.
        """
        if search_params is None:
            search_params = {"portType": "IMPORT", "pageNum": 1, "pageSize": 100}
        search_param = json.dumps(search_params, separators=(",", ":"))
        resp = self._request(
            "GET",
            self._region_url(f"/api/v1/contextlakes/{context_lake_id}/datasync/jobs"),
            params={"searchParam": search_param},
        )
        return resp.json()

    def pause_datasync_job(
        self,
        context_lake_id: str,
        job_id: str,
        instance_id: str,
        is_drain: bool = True,
    ):
        """Pause a running datasync job instance.

        Args:
            context_lake_id: ID of the context lake.
            job_id: ID of the datasync job.
            instance_id: ID of the job instance to pause.
            is_drain: If True, drain in-flight work before pausing.

        Returns:
            Parsed JSON response from the API.
        """
        resp = self._request(
            "PUT",
            self._region_url(
                f"/api/v1/contextlakes/{context_lake_id}/datasync/jobs/"
                f"{job_id}/instances/{instance_id}/state",
            ),
            json={"targetState": "PAUSED", "isDrain": is_drain},
        )
        return resp.json()

    def resume_datasync_job(
        self,
        context_lake_id: str,
        job_id: str,
        instance_id: str,
        use_latest_configuration: bool = False,
    ):
        """Resume a paused datasync job instance.

        Args:
            context_lake_id: ID of the context lake.
            job_id: ID of the datasync job.
            instance_id: ID of the job instance to resume.
            use_latest_configuration: If True, apply the latest job configuration
                when resuming.

        Returns:
            Parsed JSON response from the API.
        """
        resp = self._request(
            "PUT",
            self._region_url(
                f"/api/v1/contextlakes/{context_lake_id}/datasync/jobs/"
                f"{job_id}/instances/{instance_id}/state"
            ),
            json={
                "targetState": "RUNNING",
                "useLatestConfiguration": use_latest_configuration,
            },
        )
        return resp.json()

    def query_datasync_job(self, context_lake_id: str, job_id: str):
        """Query details of a specific datasync job.

        Args:
            context_lake_id: ID of the context lake.
            job_id: ID of the datasync job.

        Returns:
            Parsed JSON response containing job details.
        """
        resp = self._request(
            "GET",
            self._region_url(
                f"/api/v1/contextlakes/{context_lake_id}/datasync/jobs/{job_id}"
            ),
            headers={"IgnoreError": "IgnoreError"},
        )
        return resp.json()

    def query_datasync_job_instance_state(
        self,
        context_lake_id: str,
        job_id: str,
        instance_id: str,
    ):
        """Query the state of a specific datasync job instance.

        Args:
            context_lake_id: ID of the context lake.
            job_id: ID of the datasync job.
            instance_id: ID of the job instance.

        Returns:
            Parsed JSON response containing the instance state.
        """
        resp = self._request(
            "GET",
            self._region_url(
                f"/api/v1/contextlakes/{context_lake_id}/datasync/jobs/"
                f"{job_id}/instances/{instance_id}"
            ),
            headers={"IgnoreError": "IgnoreError"},
        )
        return resp.json()
