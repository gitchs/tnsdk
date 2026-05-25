#!/usr/bin/env python3
import json
import logging

from tacnode_client import TacnodeClient


def main():
    client = TacnodeClient(
        endpoint="http://tacnode-center-00.icc.kcprd.com",
        region_endpoint="http://tacnode-region-00.icc.kcprd.com",
        username="",
        password="",
    )
    client.login()
    logging.info("logging success")

    payload = client.list_datasync_jobs("cll3teu72y")
    jobs = payload["items"]
    job = jobs[0]
    state_payload = client.query_datasync_job_instance_state(
        "cll3teu72y", job["id"], job["currentInstanceId"]
    )
    print(json.dumps(state_payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
