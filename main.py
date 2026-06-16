#!/usr/bin/env python3
import json
import logging
import os

from tacnode_client import TacnodeClient


def main():
    client = TacnodeClient(
        endpoint=os.environ["TACNODE_ENDPOINT"],
        region_endpoint=os.environ["TACNODE_REGION_ENDPOINT"],
        username=os.environ["TACNODE_USERNAME"],
        password=os.environ["TACNODE_PASSWORD"],
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
