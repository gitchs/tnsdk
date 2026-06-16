import json
import logging
import time
from urllib.parse import urljoin

import requests
import urllib3

from models import CatalogList, Nodegroup, NodegroupList

logger = logging.getLogger(__name__)

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
        self._center_token = None
        self._region_token = None
        self._expired_at = None
        self._sso_completed = False
        self._session = requests.Session()

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
        """Wrapper around requests.Session.request that handles auth and error raising.

        On 401/403 against region endpoints, automatically falls back to
        the SSO flow (newer API versions), then retries once.

        Args:
            method: HTTP method (GET, POST, PUT, etc.).
            url: Full URL for the request.
            **kwargs: Passed through to session.request (params, json, headers, etc.).

        Returns:
            The Response object from requests.
        """
        self._ensure_logged_in()
        resp = self._do_request(method, url, **kwargs)
        # Fallback SSO for region endpoints that need a full session.
        if (
            resp.status_code in (401, 403)
            and url.startswith(self._region_endpoint)
            and not self._sso_completed
        ):
            logger.debug("region %s, falling back to SSO", resp.status_code)
            self._do_sso()
            resp = self._do_request(method, url, **kwargs)
        if not resp.ok:
            logger.error(
                "HTTP %s %s: %s", resp.status_code, resp.reason, resp.text[:500]
            )
        resp.raise_for_status()
        return resp

    def _do_request(self, method: str, url: str, **kwargs):
        """Send a single request with auth headers."""
        logger.debug("%s %s %s", method, url, kwargs)
        headers = kwargs.pop("headers", {})
        token = (
            self._region_token
            if self._region_token and url.startswith(self._region_endpoint)
            else self._center_token
        )
        headers["Authorization"] = f"Bearer {token}"
        logger.debug("request headers: %s", headers)
        return self._session.request(method, url, headers=headers, **kwargs)

    def login(self):
        """Login to center endpoint only.

        Obtains a center bearer token. Region SSO is deferred — it triggers
        automatically on the first 401/403 from a region endpoint.

        Returns:
            True when login succeeds.
        """
        resp = self._session.post(
            self._url("/api/v1/accounts/self-service/login"),
            json={"identifier": self._username, "password": self._password},
        )
        resp.raise_for_status()
        payload = resp.json()
        self._center_token = payload["token"]
        self._expired_at = payload["expiredAt"] / 1000.0
        self._sso_completed = False
        self._logged_in = True
        logger.debug("center login ok, token expires at %s", self._expired_at)
        return True

    def _do_sso(self):
        """Perform region SSO flow to establish a full region session.

        Called lazily when a region API request returns 401/403.
        """
        logger.debug("starting SSO flow")

        # Step 2: Get IDPs from region.
        idps_resp = self._session.get(
            self._region_url("/api/v1/accounts/self-service/idps"),
            headers={"Authorization": f"Bearer {self._center_token}"},
        )
        idps_resp.raise_for_status()
        idps = idps_resp.json()["idps"]
        if not idps:
            raise RuntimeError("no IDPs returned from region")
        idp_id = idps[0]["id"]
        logger.debug("got idp_id=%s", idp_id)

        # Step 3: Initiate SSO login on region (do NOT follow redirect).
        sso_resp = self._session.get(
            self._region_url("/api/v1/accounts/self-service/sso/login"),
            params={"id": idp_id, "return_to": "/contextlakes"},
            headers={"Authorization": f"Bearer {self._center_token}"},
            allow_redirects=False,
        )
        location = sso_resp.headers.get("Location", "")
        logger.debug("sso redirect location: %s", location)
        if "authRequest=" not in location:
            raise RuntimeError(f"no authRequest in SSO redirect: {location}")
        auth_request = location.split("authRequest=")[1].split("&")[0]
        logger.debug("authRequest=%s", auth_request)

        # Step 4: Confirm login on center.
        confirm_resp = self._session.post(
            self._url("/api/v1/accounts/self-service/confirmlogin"),
            json={"authRequest": auth_request},
            headers={"Authorization": f"Bearer {self._center_token}"},
        )
        confirm_resp.raise_for_status()
        confirm_payload = confirm_resp.json()
        logger.debug("confirmlogin: %s", confirm_payload)
        redirect_to = confirm_payload.get("redirectTo")
        if not redirect_to:
            raise RuntimeError(
                f"no redirectTo in confirmlogin response: {confirm_payload}"
            )

        # Step 5: Follow the callback URL to establish region session.
        cb_resp = self._session.get(
            redirect_to,
            headers={"Authorization": f"Bearer {self._center_token}"},
            allow_redirects=True,
        )
        cb_resp.raise_for_status()
        logger.debug("callback ok, %d cookies set", len(self._session.cookies))

        # Step 6: Verify region session and extract region token.
        verify_resp = self._session.get(
            self._region_url("/api/v1/accounts/whoami"),
        )
        if verify_resp.ok:
            body = verify_resp.json()
            logger.debug("region whoami: %s", json.dumps(body, ensure_ascii=False))
            region_token = body.get("token") or body.get("accessToken")
            if region_token:
                self._region_token = region_token
                logger.debug("region token: %s...", region_token[:20])
        else:
            logger.debug(
                "region whoami returned %s (non-fatal, session cookies are set)",
                verify_resp.status_code,
            )

        self._sso_completed = True

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

    def list_nodegroups(
        self,
        context_lake_id: str,
        page_num: int = 1,
        page_size: int = 10,
    ) -> NodegroupList:
        """List nodegroups for a context lake.

        Args:
            context_lake_id: ID of the context lake.
            page_num: Page number to retrieve (default 1).
            page_size: Number of items per page (default 10).

        Returns:
            NodegroupList model.
        """
        logger.debug(
            "list_nodegroups lake=%s page_num=%s page_size=%s",
            context_lake_id,
            page_num,
            page_size,
        )
        search_param = json.dumps(
            {"pageNum": page_num, "pageSize": page_size},
            separators=(",", ":"),
        )
        resp = self._request(
            "GET",
            self._region_url(f"/api/v1/contextlakes/{context_lake_id}/nodegroups"),
            params={"searchParam": search_param},
            headers={"IgnoreError": "IgnoreError"},
        )
        return NodegroupList.model_validate(resp.json())

    def get_nodegroup(self, context_lake_id: str, instance_id: str) -> Nodegroup:
        """Get details of a specific nodegroup.

        Args:
            context_lake_id: ID of the context lake.
            instance_id: ID of the nodegroup instance.

        Returns:
            Nodegroup model.
        """
        resp = self._request(
            "GET",
            self._region_url(
                f"/api/v1/contextlakes/{context_lake_id}/nodegroups/{instance_id}"
            ),
            headers={"IgnoreError": "IgnoreError"},
        )
        return Nodegroup.model_validate(resp.json())

    def resume_nodegroup(
        self,
        context_lake_id: str,
        instance_id: str,
        blocking: bool = False,
    ):
        """Resume a paused nodegroup.

        Args:
            context_lake_id: ID of the context lake.
            instance_id: ID of the nodegroup instance.
            blocking: If True, poll until state reaches RUNNING (max 15 min).

        Returns:
            Parsed JSON response from the state-change API.
        """
        return self._set_nodegroup_state(
            context_lake_id, instance_id, "RUNNING", blocking
        )

    def pause_nodegroup(
        self,
        context_lake_id: str,
        instance_id: str,
        blocking: bool = False,
    ):
        """Pause a running nodegroup.

        Args:
            context_lake_id: ID of the context lake.
            instance_id: ID of the nodegroup instance.
            blocking: If True, poll until state reaches PAUSED (max 15 min).

        Returns:
            Parsed JSON response from the state-change API.
        """
        return self._set_nodegroup_state(
            context_lake_id, instance_id, "PAUSED", blocking
        )

    def _set_nodegroup_state(
        self,
        context_lake_id: str,
        instance_id: str,
        target_state: str,
        blocking: bool,
    ):
        """Set nodegroup target state, optionally block until reached."""
        resp = self._request(
            "PUT",
            self._region_url(
                f"/api/v1/contextlakes/{context_lake_id}/nodegroups/{instance_id}/state"
            ),
            json={"targetState": target_state},
            headers={"IgnoreError": "IgnoreError"},
        )
        if not blocking:
            return resp.json()

        deadline = time.time() + 900  # 15 minutes
        while time.time() < deadline:
            ng = self.get_nodegroup(context_lake_id, instance_id)
            if ng.state == target_state:
                logger.debug("nodegroup %s reached state %s", instance_id, target_state)
                return ng
            logger.debug(
                "nodegroup %s state=%s, waiting for %s",
                instance_id,
                ng.state,
                target_state,
            )
            time.sleep(5)

        raise TimeoutError(
            f"nodegroup {instance_id} did not reach {target_state} within 15 minutes"
        )

    def resize_nodegroup(
        self,
        context_lake_id: str,
        instance_id: str,
        target_size: int,
        blocking: bool = False,
    ):
        """Resize a nodegroup to the target size.

        Nodegroup must be in RUNNING state, or a RuntimeError is raised.

        Args:
            context_lake_id: ID of the context lake.
            instance_id: ID of the nodegroup instance.
            target_size: Desired number of nodes.
            blocking: If True, poll until size reaches target (max 15 min).

        Returns:
            Nodegroup model if blocking, otherwise parsed JSON response.

        Raises:
            RuntimeError: If the nodegroup is not in RUNNING state.
        """
        ng = self.get_nodegroup(context_lake_id, instance_id)
        if ng.state != "RUNNING":
            raise RuntimeError(
                f"nodegroup {instance_id} is {ng.state}, must be RUNNING to resize"
            )

        resp = self._request(
            "PUT",
            self._region_url(
                f"/api/v1/contextlakes/{context_lake_id}/nodegroups/{instance_id}/size"
            ),
            json={"targetSize": target_size},
            headers={"IgnoreError": "IgnoreError"},
        )
        if not blocking:
            return resp.json()

        deadline = time.time() + 900  # 15 minutes
        while time.time() < deadline:
            ng = self.get_nodegroup(context_lake_id, instance_id)
            if ng.size == target_size:
                logger.debug("nodegroup %s reached size %s", instance_id, target_size)
                return ng
            logger.debug(
                "nodegroup %s size=%s, waiting for %s",
                instance_id,
                ng.size,
                target_size,
            )
            time.sleep(5)

        raise TimeoutError(
            f"nodegroup {instance_id} did not reach size {target_size} "
            f"within 15 minutes"
        )

    def list_catalogs(self, context_lake_id: str) -> CatalogList:
        """List catalogs for a context lake.

        Args:
            context_lake_id: ID of the context lake.

        Returns:
            CatalogList model.
        """
        search_param = json.dumps({"pageSize": 999999}, separators=(",", ":"))
        resp = self._request(
            "GET",
            self._region_url(f"/api/v1/contextlakes/{context_lake_id}/catalogs"),
            params={"searchParam": search_param},
            headers={"IgnoreError": "IgnoreError"},
        )
        return CatalogList.model_validate(resp.json())

    def create_nodegroup(
        self,
        context_lake_id: str,
        instance_name: str,
        catalog_name: str,
        target_size: int = 1,
        auto_pause: bool = False,
    ):
        """Create a nodegroup for a context lake.

        Looks up the catalog by name via list_catalogs. If found, passes
        the catalog ID; otherwise passes the name so the backend can
        auto-create it.

        Args:
            context_lake_id: ID of the context lake.
            name: Name for the new nodegroup instance.
            catalog_name: Name of the catalog to attach.
            target_size: Number of nodes (default 1).
            auto_pause: Enable auto-pause (default False).

        Returns:
            Parsed JSON response from the create API.
        """
        # Step 1: Check if catalog already exists by name.
        catalogs = self.list_catalogs(context_lake_id)
        catalog_id = None
        for c in catalogs.items:
            if c.name == catalog_name:
                catalog_id = c.id
                break

        body: dict = {
            "name": instance_name,
            "targetSize": target_size,
            "autoPauseCommand": {"enable": auto_pause},
        }

        if catalog_id is not None:
            body["catalog"] = {"id": catalog_id}
            logger.debug("catalog exists, using id=%s", catalog_id)
        else:
            body["catalog"] = {"name": catalog_name}
            logger.debug("catalog does not exist, passing name for auto-create")

        resp = self._request(
            "POST",
            self._region_url(f"/api/v1/contextlakes/{context_lake_id}/nodegroups"),
            json=body,
            headers={"IgnoreError": "IgnoreError"},
        )
        return resp.json()
