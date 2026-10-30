"""
Run this DURING a live FP/Qualifying/Race session to capture F1's real
declared tyre New/used flag (see data/live_timing_feed.py for why this
exists and what it fixes). Does nothing useful between sessions -- there
is no historical replay through this channel, only whatever is live right
now.

Usage:
    python capture_live_tyres.py <openf1_session_key> [--duration SECONDS]

    <openf1_session_key> is the OpenF1 session_key for the session you're
    about to capture (check /api/next_meeting or OpenF1's /sessions
    endpoint) -- it's only used as the output filename, so
    engine.tyre_inventory's loader can find it again once the session
    ends and the pre-race briefing gets (re)built.

Stop it with Ctrl-C once the session you're watching ends; it also exits
on its own once F1's own SessionStatus feed reports the session finished,
or after --duration seconds (default 3 hours) as a backstop.
"""
import argparse
import asyncio
import sys

from data.live_timing_feed import capture_session


async def _main(session_key: int, duration: float):
    print(f"Connecting to F1 live timing, capturing for session_key={session_key}...")
    print("Checkpointing to cache/live_tyre_flags/ every 30s. Ctrl-C to stop early.")
    try:
        flags = await capture_session(session_key, max_duration_s=duration)
    except KeyboardInterrupt:
        print("\nStopped early by user; last checkpoint is still on disk.")
        return
    n_drivers = len(flags)
    n_stints = sum(len(v) for v in flags.values())
    print(f"Done: captured {n_stints} stints across {n_drivers} drivers.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("session_key", type=int)
    parser.add_argument("--duration", type=float, default=3 * 3600,
                        help="max seconds to run before giving up (default 3h)")
    args = parser.parse_args()
    try:
        asyncio.run(_main(args.session_key, args.duration))
    except KeyboardInterrupt:
        sys.exit(0)
