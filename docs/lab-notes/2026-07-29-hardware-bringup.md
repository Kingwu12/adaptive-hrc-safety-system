# Lab notes — 2026-07-29: first hardware bring-up (UR10)

Everything below was verified live this session (not recalled).

## Robot + network runbook

- Robot: UR10 e-Series, serial 20185000750, PolyScope 5.9.3.1031212.
- Arm static IP **192.168.1.101/24**, mask 255.255.255.0, gw 192.168.1.1
  (set on pendant: Settings -> System -> Network; the DHCP radio toggle
  WIPES staged values — re-enter and press Apply).
- Laptop: USB ethernet adapter, macOS service "USB 10/100/1000 LAN" (en10):
  `networksetup -setmanual "USB 10/100/1000 LAN" 192.168.1.100 255.255.255.0`
  (no sudo needed).
- Cable goes to the **control box bottom ethernet port**. A lab cable to the
  wifi router gives a live 1000baseT link with no robot on it — first trap.
- Remote handover: header-bar icon toggle (screen locks when correct).
  Dashboard `is in remote control` can return **true while execution is
  still blocked** — the real test is whether `RTDEControlInterface`
  connects. Error text when wrong: "Command is not allowed due to safety
  reasons / Please enable remote control on the robot!".

## Build environment (macOS)

- `ur-rtde 1.6.3` has no macOS wheels; source build needs **boost@1.85**
  (Boost 1.90 removed `boost_system` CMake config -> build fails):
  `brew install boost@1.85`, then
  `BOOST_ROOT=/opt/homebrew/opt/boost@1.85 CMAKE_PREFIX_PATH=$BOOST_ROOT pip install ur-rtde`.

## What ran on hardware today

1. Dashboard identity check: model UR10, mode RUNNING, safety NORMAL.
2. Read-only RTDE receive: live joint angles, speed slider readback.
3. Zero-motion idle URScript pushed via port 30001 (kept-alive socket) as
   the running program — never send dashboard `play` while the loaded .urp
   is unknown.
4. Live slider control witnessed: 1.0 -> 0.4 -> 1.0 round-trip.
5. `demo_ursim.py --log fixed_zone --speed 4` and `--log adaptive` both
   replayed on the real arm (sim logs regenerated first). Robot left safe:
   slider 1.0, no program running.

## Sensing (corrected + built)

- Lab tracker is an **Xsens IMU suit** (NOT OptiTrack as the scoping doc
  assumed). Transport implemented: `src/hrc_safety/mocap/xsens_transport.py`
  (MVN MXTP02 UDP parser + listener, default port 9763, pelvis segment).
  Bridge/recorder/calibration unchanged. Commits c463c1d, a3e740f; 31/31.
- Xsens Analyze/Animate and the Awinda USB driver require a Windows 10/11
  host. Attach the Awinda dongle to that Windows machine; the Mac is the UDP
  receiver and does not need an Xsens USB driver.
- MVN setup on Windows: Options -> Network Streamer -> UDP, "Position +
  Quaternion", target = Mac LAN IP : 9763. Verify the FIRST real packet
  against the parser once.

## Open questions (for Yizhe)

1. ~~IMU position drift: anchoring policy?~~ **ANSWERED (Yizhe, from
   experience, 2026-07-29): strap super tight, no wiggle room; clean
   restart/recalibration every ~5 minutes.** Design consequence: loops fit
   inside 5-min windows between re-anchors; Sa measured within a window.
2. MUHREC submission must describe the Xsens wearable — CHECK the submitted
   application text mentions the suit/straps, not cameras.
