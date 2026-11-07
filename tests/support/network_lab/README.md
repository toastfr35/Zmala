# Isolated network lab

This fixture runs the actual server and shared terminal Engine in disposable Docker
containers. Two home routers and a server router separate three LANs and a simulated
Internet. No port is published to the PC or real LAN. Disposable credentials and
certificates live in a Docker volume; real server data is excluded from image builds.
Use only the dedicated WSL Docker daemon, and keep WSL active until each run finishes.

Create a combined application archive using the [image builder instructions](../../../zmala_images/README.md#offline-applications-and-development-media).
Run from the Zmala checkout in WSL as root. Use the archive digest from its
`READY.json` and record it with the test results.

```sh
python3 -m tests.support.network_lab.lab build --applications APPLICATIONS_TAR --expected-applications-sha256 SHA256
python3 -m tests.support.network_lab.tls_scenarios
ZMALA_LAB_TLS=1 python3 -m tests.support.network_lab.lab down
python3 -m tests.support.network_lab.scenarios
python3 -m tests.support.network_lab.lab down
```

The secure server and terminal HLT entry points share the same matrix; do not run
them concurrently. An exclusive lock prevents overlapping scenario runs. Reports
are written below `tests/coverage/network-lab/`. Cleanup removes containers, networks,
credentials and the narrow host bridge forwarding rules; it retains the image.

The TLS overlay uses three simulated public IPs: HTTPS .15, SIP .13 and TURN .14,
all on TCP 443 in 10.231.100.0/24. It uses actual production `secure-calls.js` and
`secure_calls.py`, with no transport monkeypatch. Coturn validates temporary HMAC
credentials issued by the application server. A disposable CA authenticates endpoints;
mandatory SRTP protects media. The server preserves ICE SDP and signed call proofs.

The matrix blocks UDP before established-flow acceptance at A, B and both homes,
and runs unrestricted regressions. Each policy calls both ways, requires native
SRTP/relay ICE state, actual decoded opposite audio tones and fresh H.264 frames,
then hangs up and verifies resource release. It checks HTTPS configuration and
firewall counters. Separate probes reject untrusted endpoint certificates; native
SIP probes reject an unrelated CA and a wrong certificate name. Each recording
starts with a new file, preventing stale audio from satisfying a later assertion.

`build_tools/linux/build-turn.py` builds the same pinned SDK correction used by the
Pi installer. `tests/terminal/LLT/turn_parser.cpp` tests fragmented headers, padded
ChannelData and coalesced STUN at every chunk size. The original parser must reproduce
the padded-length assertion; the corrected parser must pass. Build evidence and
upstream source stay under `zmala_terminal/linux/turn-runtime/`, outside Git.

The synthetic camera is a static 640x480 image, normally about one frame per second.
Generated audio and Xvfb replace physical devices. Software OpenH264 replaces Pi
V4L2 encoding; the actual production FFmpeg decoder is used. This does not qualify
moving-image quality, ARM call throughput, long calls or institution-specific
firewalls. Numeric addresses avoid DNS; HTTPS-only proxies and TLS inspection can
still reject these protocols. Public deployment and certificate renewal are described
in the [Server technical guide](https://github.com/toastfr35/ZmalaServer/blob/main/docs/server.md);
the lab does not configure an Internet service.
