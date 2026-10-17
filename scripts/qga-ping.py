#!/usr/bin/env python3
"""Ping the QEMU guest agent over the virtio-serial socket the boot test attaches.

WHAT THIS IS
    The host half of the guest-agent exercise. scripts/smoke-boot.sh gives the guest a
    virtio serial port named org.qemu.guest_agent.0 and connects the host end to a unix
    socket; inside the guest, the qemu-guest-agent package's udev rule starts
    qemu-guest-agent.service against that port when it appears. This script then talks
    to it.

    It is the difference between "the package is installed" and "a hypervisor and its
    guest are actually speaking". The guest's own self-test can only see the process;
    this side performs the protocol:

      1. guest-sync-delimited, with a random id - flushes whatever the channel holds,
         skips non-JSON noise, and proves the peer echoes our id (for qemu-ga, a channel
         that is not the agent answers nothing);
      2. guest-ping - the agent must answer;
      3. guest-info - the version, recorded as evidence in the log.

    The dialogue and its framing are the ones QEMU documents in docs/interop/qemu-ga.rst:
    one JSON object per line, and guest-sync-delimited additionally prefixes each message
    with a 0xFF byte.

Exit codes:
    0  the agent answered guest-ping
    1  it did not; the reason is on stderr and, when a log path was given, in the log
    2  the arguments were wrong
"""

from __future__ import annotations

import argparse
import json
import secrets
import socket
import sys
import time

DEFAULT_TIMEOUT = 15.0
SYNC_MARKER = b"\xff"


class AgentError(Exception):
    pass


class AgentChannel:
    """One connection to the agent, with line-framed JSON in and out."""

    def __init__(self, path: str, timeout: float, log) -> None:
        self.timeout = timeout
        self.log = log
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(path)
        self.buffer = b""

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def send(self, request: dict) -> None:
        self.sock.sendall((json.dumps(request) + "\n").encode("utf-8"))

    def next_message(self) -> dict:
        """The next complete JSON message from the agent, noise skipped."""
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                # guest-sync-delimited prefixes every message with 0xFF; anything
                # before a message is channel filler, not part of it.
                line = line.lstrip(SYNC_MARKER).strip()
                if not line:
                    continue
                try:
                    message = json.loads(line.decode("utf-8", "replace"))
                except ValueError:
                    self.log(f"non-JSON traffic ignored: {line[:120]!r}")
                    continue
                if not isinstance(message, dict):
                    self.log(f"non-object message ignored: {line[:120]!r}")
                    continue
                if "error" in message:
                    raise AgentError(f"the agent answered an error: {message['error']}")
                if "return" in message:
                    return message
                # An event (unsolicited) is not a reply; keep reading.
                self.log(f"event ignored: {line[:120]!r}")
            try:
                chunk = self.sock.recv(65536)
            except TimeoutError:
                break
            if not chunk:
                raise AgentError("the agent closed the connection")
            self.buffer += chunk
        raise AgentError("no reply within the timeout")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                        help=f"seconds to wait for each reply (default: {DEFAULT_TIMEOUT:g})")
    parser.add_argument("socket_path", help="the unix socket QEMU connected the port to")
    parser.add_argument("log_path", nargs="?", help="append the transcript here")
    args = parser.parse_args()

    transcript: list[str] = []

    def log(line: str) -> None:
        transcript.append(line)
        print(f"qga-ping: {line}", flush=True)

    def finish(code: int) -> int:
        if args.log_path:
            try:
                with open(args.log_path, "a", encoding="utf-8") as handle:
                    for line in transcript:
                        handle.write(line + "\n")
            except OSError as exc:
                print(f"qga-ping: cannot write {args.log_path}: {exc}", file=sys.stderr)
        return code

    try:
        channel = AgentChannel(args.socket_path, args.timeout, log)
    except AttributeError as exc:
        log(f"this Python has no unix sockets: {exc}")
        return finish(1)
    except OSError as exc:
        log(f"cannot connect to {args.socket_path}: {exc}")
        return finish(1)

    try:
        try:
            sync_id = secrets.randbits(31) + 1
            channel.send({"execute": "guest-sync-delimited", "arguments": {"id": sync_id}})
            reply = channel.next_message()
            if reply.get("return") != sync_id:
                log(f"the guest-sync echo carried the wrong id: {reply!r}")
                return finish(1)
            log(f"guest-sync echoed (id={sync_id}): a guest agent is on the channel")

            channel.send({"execute": "guest-ping"})
            reply = channel.next_message()
            if reply.get("return") != {}:
                log(f"guest-ping answered something unexpected: {reply!r}")
                return finish(1)
            log("guest-ping answered")

            channel.send({"execute": "guest-info"})
            reply = channel.next_message()
            info = reply.get("return")
            version = info.get("version", "unknown") if isinstance(info, dict) else "unknown"
            log(f"agent version: {version}")
        except AgentError as exc:
            log(str(exc))
            return finish(1)
        except (OSError, TimeoutError) as exc:
            log(f"the channel failed: {exc}")
            return finish(1)
    finally:
        channel.close()

    return finish(0)


if __name__ == "__main__":
    raise SystemExit(main())
