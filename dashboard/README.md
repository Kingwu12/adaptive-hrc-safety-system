# HRC Operator Motion Console

Local web interface for the Monash adaptive HRC safety FYP. The UI displays
the Xsens-derived position and motion features produced by
`scripts/dashboard_server.py`, captures participant/trial metadata, applies
ground-truth labels, and shows the current layered-HMM posterior.

## Run locally

Use Node.js 22.13 or newer. From the repository root, open two terminals:

```bash
python scripts/dashboard_server.py
```

```bash
cd dashboard
npm install
npm run dev
```

Open <http://localhost:3000>. Xsens Analyze/Animate and the Awinda USB driver
run on Windows 10/11, not macOS: attach the Awinda dongle to the Windows host,
then stream `Position + Quaternion` over UDP to this Mac on port `9763`.
The header must show `Xsens 23/23 segments` before recording. Also start a
native MVN recording on Windows; the Mac JSONL stores synchronized segment
poses, while the native file preserves the broader MVN data product.

## Trusted lab-network viewing

```bash
python scripts/dashboard_server.py --share
cd dashboard && npm run dev -- --host 0.0.0.0
```

Teammates can use the Mac's LAN address to view the console. Remote browsers
are view-only unless the host deliberately adds `--allow-remote-control`.
Recorded JSONL data stays under `data/xsens/` and is ignored by Git.
