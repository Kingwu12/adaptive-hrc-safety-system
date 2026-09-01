# Dual-Ethernet lab network

The Windows lab PC has two physically separate USB Ethernet adapters. They must
use different IPv4 subnets; putting both adapters in `192.168.1.0/24` makes
Windows route robot packets onto the OptiTrack camera link.

| Link | Windows adapter | Windows IP | Device IPs |
|---|---|---:|---:|
| OptiTrack | Ethernet / Realtek USB GbE / `00-E0-6C-39-5A-98` | `192.168.1.102/24` | cameras `192.168.1.4`–`.12` |
| UR10e | Ethernet 6 / Realtek USB FE / `00-E0-4C-36-C7-44` | `192.168.2.102/24` | robot `192.168.2.101` |

Neither lab adapter needs a gateway or DNS server. Wi-Fi owns internet access.

Run PowerShell as Administrator once:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/configure_robot_network.ps1
```

On the UR pendant, set static IPv4 `192.168.2.101`, mask `255.255.255.0`, no
gateway, then select Remote Control. A healthy link answers Dashboard port
`29999` and RTDE port `30004`.
