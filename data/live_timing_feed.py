"""
Live F1 timing feed client — captures the genuine "New"/used tyre flag that
OpenF1 does not expose.

Why this exists: `engine.tyre_inventory` approximates "this stint opened a
brand-new physical tyre" from `tyre_age_at_start == 0`, because that is all
OpenF1's `/stints` endpoint carries. That approximation breaks for a driver
who refits an already-scrubbed set for an extra Qualifying banker lap (more
common for front-runners making deep Q3 runs) -- OpenF1 has no way to tell
that apart from a genuinely fresh set, and it isn't a bug in our code, it's
missing from OpenF1's data (confirmed directly: its `/stints` response has
exactly 8 fields, none of them a "new" flag). Found while investigating a
real Austin 2026 tyre-availability mismatch against F1.com's own chart for
ANT/HAM/RUS/PIA -- all deep Q3 runners, all over-counted by 2-3 sets.

F1's own live timing feed carries the real thing: `TimingAppData.Lines.
{driver_number}.Stints[i].New`, a genuine "true"/"false" string set by the
official timing system at the moment a stint starts, not derived from tyre
age. Confirmed by reading the darshjoshi/pitwall project (MIT licensed)
directly, which reads this exact field both from F1's post-session static
archive and from this same live feed. The static archive is currently
returning 401 for anonymous requests (confirmed directly, along with
FastF1 and pitwall's own "no auth needed" code path both failing the same
way) -- but the LIVE SignalR feed used here is a different endpoint and
is NOT behind that wall: `POST .../signalrcore/negotiate` returned a real
200 with a connection token when checked directly. Only car telemetry
(CarData.z) and car position (Position.z) need an F1TV token (per F1's own
policy since Aug 2025) -- TimingAppData is free.

The catch: this only exists while a session is live. There is no historical
replay through this channel, so it can only improve sessions captured going
forward, starting with whichever FP/Qualifying session is next -- it can't
retroactively fix Austin. A capture run writes its result to
`cache/live_tyre_flags/{session_key}.json`; `engine.tyre_inventory` reads
that file (if present) and uses the real flag in place of the age-based
guess for exactly the stints it covers, falling back to the existing
heuristic everywhere else. Absent any captured file, behaviour is pixel-for-
pixel what it was before this module existed.

Protocol (reverse-engineered, same understanding pitwall/FastF1 built on):
  1. OPTIONS /signalrcore/negotiate -> AWSALBCORS cookie (load-balancer
     affinity, not a credential)
  2. WebSocket connect to wss://.../signalrcore with that cookie attached
  3. Send {"protocol":"json","version":1}\x1e, expect an empty-object ack
  4. Send a Subscribe invocation with our topic list
  5. Receive the initial state as a Completion message (type 3), then live
     deltas as Invocation messages (type 1, target "feed") -- deep-merged
     onto the running state, since F1 only ever sends what changed
  6. Reply to Ping messages (type 6) to stay connected
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import time
from typing import Any

import ssl

import certifi
import httpx
import websockets

# System Python on macOS ships without a usable CA bundle for the SSL module,
# which makes the default context reject F1's (perfectly valid) certificate
# with CERTIFICATE_VERIFY_FAILED. certifi's bundle is the standard fix.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

NEGOTIATE_URL = "https://livetiming.formula1.com/signalrcore/negotiate"
WEBSOCKET_URL = "wss://livetiming.formula1.com/signalrcore"
RECORD_SEPARATOR = "\x1e"

MSG_INVOCATION = 1
MSG_COMPLETION = 3
MSG_PING = 6
MSG_CLOSE = 7

# The only topics this capture needs -- TimingAppData for the real stint
# data, the other three just to know what session this is and map driver
# numbers to something the caller can key on. Deliberately NOT CarData.z/
# Position.z (telemetry/GPS): those need an F1TV token we don't have, and
# nothing here needs them.
TOPICS = ["TimingAppData", "SessionInfo", "SessionStatus", "DriverList"]

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                         "cache", "live_tyre_flags")


def _deep_merge(base: Any, update: Any) -> Any:
    """Recursively merge `update` onto `base`. F1's delta format: matching
    dict keys recurse, a leaf value in `update` overwrites `base`, keys only
    in `base` are kept untouched."""
    if not isinstance(base, dict) or not isinstance(update, dict):
        return update
    merged = copy.copy(base)
    for key, value in update.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _session_finished(state: dict) -> bool:
    status = (state.get("SessionStatus") or {}).get("Status", "")
    return status in ("Finalised", "Finished", "Ends")


def extract_tyre_flags(state: dict) -> dict[int, list[dict]]:
    """{driver_number: [{"compound": str, "new": bool, "total_laps": int}, ...]}
    in chronological stint order, straight from the real declared flag --
    no age-based guessing."""
    lines = (state.get("TimingAppData") or {}).get("Lines") or {}
    out: dict[int, list[dict]] = {}
    for num_str, line in lines.items():
        if not isinstance(line, dict):
            continue
        stints = line.get("Stints")
        if not stints:
            continue
        # F1 sends this as either a list (keyframe) or a dict keyed by
        # stint index as a string (some deltas) -- normalise both.
        if isinstance(stints, dict):
            ordered = [stints[k] for k in sorted(stints, key=lambda x: int(x))]
        else:
            ordered = stints
        try:
            num = int(num_str)
        except ValueError:
            continue
        out[num] = [
            {
                "compound": s.get("Compound"),
                "new": str(s.get("New", "")).lower() == "true",
                "total_laps": s.get("TotalLaps"),
            }
            for s in ordered if isinstance(s, dict) and s.get("Compound")
        ]
    return out


async def _negotiate_cookie() -> dict[str, str]:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.options(NEGOTIATE_URL)
        cookie = resp.cookies.get("AWSALBCORS")
        return {"AWSALBCORS": cookie} if cookie else {}


async def capture_session(
    session_key: int,
    max_duration_s: float = 3 * 3600,
    checkpoint_every_s: float = 30,
    out_dir: str = CACHE_DIR,
) -> dict[int, list[dict]]:
    """Connect to F1's live timing feed and capture real tyre New/Used flags
    until the session ends or `max_duration_s` elapses, whichever comes
    first. Checkpoints to disk every `checkpoint_every_s` so a crash loses
    at most that much, in `{out_dir}/{session_key}.json`. Returns the final
    captured flags on a clean exit.

    `session_key` is purely a filename -- this module makes no OpenF1 calls
    and does no correlation itself; it's the caller's job to pass the
    OpenF1 session_key this live session corresponds to, so
    engine.tyre_inventory can find the right file later.
    """
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{session_key}.json")

    cookies = await _negotiate_cookie()
    headers = [("Cookie", f"{k}={v}") for k, v in cookies.items()]

    state: dict[str, Any] = {}
    started = time.monotonic()
    last_checkpoint = 0.0

    async with websockets.connect(
        WEBSOCKET_URL, additional_headers=headers,
        ping_interval=None, max_size=2**22, ssl=_SSL_CONTEXT,
    ) as ws:
        await ws.send(json.dumps({"protocol": "json", "version": 1}) + RECORD_SEPARATOR)
        await ws.recv()   # handshake ack

        await ws.send(json.dumps({
            "type": MSG_INVOCATION, "invocationId": "1",
            "target": "Subscribe", "arguments": [TOPICS],
        }) + RECORD_SEPARATOR)

        while True:
            elapsed = time.monotonic() - started
            if elapsed >= max_duration_s:
                break
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                continue

            for part in raw.split(RECORD_SEPARATOR):
                if not part.strip():
                    continue
                try:
                    msg = json.loads(part)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type")
                if msg_type == MSG_PING:
                    await ws.send(json.dumps({"type": MSG_PING}) + RECORD_SEPARATOR)
                elif msg_type == MSG_COMPLETION:
                    result = msg.get("result") or {}
                    for topic, data in result.items():
                        state[topic] = _deep_merge(state.get(topic), data)
                elif msg_type == MSG_INVOCATION and msg.get("target") == "feed":
                    args = msg.get("arguments") or []
                    if len(args) >= 2:
                        topic, data = args[0], args[1]
                        state[topic] = _deep_merge(state.get(topic), data)
                elif msg_type == MSG_CLOSE:
                    raise ConnectionError(msg.get("error", "server closed connection"))

            if elapsed - last_checkpoint >= checkpoint_every_s:
                last_checkpoint = elapsed
                with open(out_path, "w") as f:
                    json.dump(extract_tyre_flags(state), f)

            if _session_finished(state):
                break

    flags = extract_tyre_flags(state)
    with open(out_path, "w") as f:
        json.dump(flags, f)
    return flags


def load_captured_flags(session_key: int, cache_dir: str = CACHE_DIR) -> dict[int, list[dict]] | None:
    """{driver_number: [{"compound","new","total_laps"}, ...]} for a
    previously-captured session, or None if nothing was captured for it
    (the normal case for every session before this module existed, and for
    any session nobody ran a capture against) -- callers must treat None as
    "fall back to the existing heuristic", not an error."""
    path = os.path.join(cache_dir, f"{session_key}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        raw = json.load(f)
    return {int(k): v for k, v in raw.items()}


async def check_connectivity() -> dict:
    """One-shot sanity check, safe to run between sessions: completes the
    negotiate + handshake + subscribe steps and reports whether a keyframe
    came back, without needing a live car on track. Does not write a cache
    file. Used to verify the plumbing independent of race-weekend timing."""
    cookies = await _negotiate_cookie()
    headers = [("Cookie", f"{k}={v}") for k, v in cookies.items()]
    async with websockets.connect(
        WEBSOCKET_URL, additional_headers=headers,
        ping_interval=None, max_size=2**22, ssl=_SSL_CONTEXT,
    ) as ws:
        await ws.send(json.dumps({"protocol": "json", "version": 1}) + RECORD_SEPARATOR)
        handshake_resp = await ws.recv()

        await ws.send(json.dumps({
            "type": MSG_INVOCATION, "invocationId": "1",
            "target": "Subscribe", "arguments": [TOPICS],
        }) + RECORD_SEPARATOR)

        raw = await asyncio.wait_for(ws.recv(), timeout=10)
        got_completion = any(
            json.loads(p).get("type") == MSG_COMPLETION
            for p in raw.split(RECORD_SEPARATOR) if p.strip()
        )
        return {
            "negotiated_cookie": bool(cookies),
            "handshake_ok": handshake_resp.strip(RECORD_SEPARATOR) in ("{}", ""),
            "got_completion_message": got_completion,
        }
