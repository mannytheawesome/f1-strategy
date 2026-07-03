"""
Shared MQTT live-data client for monitor_<track>.py scripts.

Per OpenF1 docs (openf1.org/auth.html): the live broker is at
mqtt.openf1.org:8883 over TLS. The OAuth2 access token (same one used for
authenticated REST access) is used as the MQTT password; username can be any
non-empty string. Topics mirror REST endpoints (v1/laps, v1/stints, etc.) and
are NOT session-scoped, so messages are filtered locally by session_key.
Tokens expire after 1hr with no documented MQTT-specific refresh mechanism,
so we proactively re-fetch and reconnect before expiry.

Reuses the OAuth2 token flow already wired up in data/live.py.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import json
import ssl
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from data.live import _fetch_oauth_token, OPENF1_USERNAME

MQTT_HOST = "mqtt.openf1.org"
MQTT_PORT = 8883
TOKEN_REFRESH_MARGIN_S = 300  # refresh 5 min before the 1hr token expires

TOPICS = ["v1/sessions", "v1/drivers", "v1/stints", "v1/laps",
          "v1/position", "v1/intervals", "v1/location"]


class MQTTSessionMonitor:
    """Connects to OpenF1's MQTT broker, subscribes to live-data topics for
    one session, and writes matching messages to <rec_dir>/mqtt_<topic>.jsonl.
    Call run_until(end) to block (processing messages on a background thread)
    until the given UTC end time.
    """

    def __init__(self, session_key: int, rec_dir: str, log_fn=print):
        self.session_key = session_key
        self.rec_dir = rec_dir
        self.log = log_fn
        self._client: mqtt.Client | None = None
        self._token_expires_at = 0.0
        self._stop = threading.Event()
        self._files: dict[str, "object"] = {}
        self._file_lock = threading.Lock()
        self._last_lap: dict[int, int] = {}
        self._last_logged_max_lap = -1
        self.message_count = 0

    def _write(self, topic: str, record: dict):
        slug = topic.replace("/", "_")
        path = os.path.join(self.rec_dir, f"mqtt_{slug}.jsonl")
        with self._file_lock:
            fh = self._files.get(slug)
            if fh is None:
                fh = open(path, "a")
                self._files[slug] = fh
            fh.write(json.dumps(record) + "\n")
            fh.flush()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0 or str(reason_code) == "Success":
            self.log(f"MQTT connected to {MQTT_HOST}:{MQTT_PORT}")
            for topic in TOPICS:
                client.subscribe(topic)
        else:
            self.log(f"⚠️  MQTT connect failed: {reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        if not self._stop.is_set():
            self.log(f"⚠️  MQTT disconnected unexpectedly: {reason_code}")

    def _on_message(self, client, userdata, msg):
        self.message_count += 1
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            return
        records = payload if isinstance(payload, list) else [payload]
        for rec in records:
            if not isinstance(rec, dict):
                continue
            if rec.get("session_key") not in (None, self.session_key):
                continue  # topics aren't session-scoped — filter locally
            self._write(msg.topic, rec)
            if msg.topic == "v1/laps":
                self._track_lap_progress(rec)

    def _track_lap_progress(self, rec: dict):
        n, ln = rec.get("driver_number"), rec.get("lap_number")
        if n is None or ln is None:
            return
        self._last_lap[n] = max(self._last_lap.get(n, 0), ln)
        max_lap = max(self._last_lap.values(), default=0)
        if max_lap != self._last_logged_max_lap:
            active = sum(1 for v in self._last_lap.values() if v > 0)
            self.log(f"lap {max_lap}, {active}/{len(self._last_lap)} active (mqtt)")
            self._last_logged_max_lap = max_lap

    def _get_fresh_token(self) -> str:
        token, ttl = _fetch_oauth_token()
        self._token_expires_at = time.time() + ttl
        return token

    def _refresh_loop(self):
        while not self._stop.is_set():
            wait_s = max(5.0, self._token_expires_at - time.time() - TOKEN_REFRESH_MARGIN_S)
            if self._stop.wait(wait_s):
                return
            try:
                token = self._get_fresh_token()
                self._client.username_pw_set(OPENF1_USERNAME or "monitor", token)
                self._client.reconnect()
                self.log("MQTT token refreshed, reconnected")
            except Exception as e:
                self.log(f"⚠️  MQTT token refresh failed: {str(e)[:80]}")

    def run_until(self, end: datetime, poll_s: float = 2.0):
        os.makedirs(self.rec_dir, exist_ok=True)
        token = self._get_fresh_token()
        if not token:
            self.log("⚠️  MQTT: no OAuth token available (check OPENF1_USERNAME/PASSWORD) — skipping")
            return

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
        client.username_pw_set(OPENF1_USERNAME or "monitor", token)
        client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        self._client = client

        client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        client.loop_start()

        refresher = threading.Thread(target=self._refresh_loop, daemon=True)
        refresher.start()

        try:
            while datetime.now(timezone.utc) < end and not self._stop.is_set():
                time.sleep(poll_s)
        finally:
            self._stop.set()
            client.loop_stop()
            client.disconnect()
            with self._file_lock:
                for fh in self._files.values():
                    fh.close()
                self._files.clear()
