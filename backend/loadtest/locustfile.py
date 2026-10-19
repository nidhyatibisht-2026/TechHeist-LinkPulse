"""Redirect latency test.  pip install locust  then:
    locust -f loadtest/locustfile.py --host http://localhost:8000 -u 200 -r 50 -t 1m --headless

Uses a real browser user agent: scripted user agents are (correctly) classified as
bots by LinkPulse and would not exercise the normal click path.
"""
from locust import FastHttpUser, between, task

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1")


class Visitor(FastHttpUser):
    wait_time = between(0.05, 0.3)

    @task(8)
    def popular_link(self):
        self.client.get("/diwali", headers={"User-Agent": UA}, allow_redirects=False, name="/[code] redirect")

    @task(2)
    def targeted_link(self):
        self.client.get("/get-app", headers={"User-Agent": UA}, allow_redirects=False, name="/[code] targeted")

    @task(1)
    def missing_code(self):
        with self.client.get("/does-not-exist", headers={"User-Agent": UA}, allow_redirects=False,
                             catch_response=True, name="/[code] 404") as r:
            if r.status_code == 404:
                r.success()
