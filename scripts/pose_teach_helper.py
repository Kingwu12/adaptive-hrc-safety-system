"""pose_teach_helper.py - live pose teaching/synthesis on the real UR10.

Used interactively from a REPL during lab sessions. Provides:
  snap()            - joints + TCP pose right now (via RTDE)
  ask_robot(prog)   - inject def-only URScript over 30001, keep socket open,
                      collect one readback string on 192.168.1.100:30999
  ik(pose, qnear)   - get_inverse_kin computed ON the robot, nothing moves
  goto_j(q, v)      - slow movej to joint target (payload set first)

Injection protocol (learned on the real arm 2026-08-12):
  - def-only over port 30001 (def auto-starts; trailing call = parse error)
  - the sender socket must STAY OPEN or the program dies
  - first statement must be set_payload(1.7,[0,0,0.06]) or the shoulder
    trips a C157A1 collision protective stop
"""
import socket
import time

import rtde_receive

ROBOT = "192.168.1.101"
MAC = "192.168.1.100"
READBACK_PORT = 30999
PAYLOAD = "set_payload(1.7,[0,0,0.06])"

_r = None
_open_sockets = []  # keep injection sockets alive (protocol: socket stays open)


def rtde():
    global _r
    if _r is None or not _r.isConnected():
        _r = rtde_receive.RTDEReceiveInterface(ROBOT)
    return _r


def snap():
    r = rtde()
    return {"q": [round(v, 5) for v in r.getActualQ()],
            "tcp": [round(v, 5) for v in r.getActualTCPPose()]}


def ask_robot(body_lines, timeout=8.0):
    """Inject a def-only program; return one readback string sent by the
    robot to MAC:READBACK_PORT (empty string if none arrives)."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((MAC, READBACK_PORT))
    srv.listen(1)
    srv.settimeout(timeout)

    prog = "def teach_prog():\n"
    prog += "  " + PAYLOAD + "\n"
    for ln in body_lines:
        prog += "  " + ln + "\n"
    prog += "end\n"

    inj = socket.create_connection((ROBOT, 30001), timeout=5)
    inj.sendall(prog.encode())
    _open_sockets.append(inj)  # keep open: program dies if sender closes

    out = ""
    try:
        conn, _ = srv.accept()
        conn.settimeout(timeout)
        chunks = []
        try:
            while True:
                c = conn.recv(4096)
                if not c:
                    break
                chunks.append(c)
        except socket.timeout:
            pass
        conn.close()
        out = b"".join(chunks).decode(errors="replace")
    except socket.timeout:
        pass
    srv.close()
    return out


def ik(pose, qnear):
    """get_inverse_kin on the robot; returns joint list or None. No motion."""
    p = "p[" + ",".join(f"{v:.6f}" for v in pose) + "]"
    qn = "[" + ",".join(f"{v:.6f}" for v in qnear) + "]"
    body = [
        f"q = get_inverse_kin({p}, qnear={qn})",
        f'socket_open("{MAC}", {READBACK_PORT}, "rb")',
        'socket_send_string(to_str(q), "rb")',
        'socket_close("rb")',
    ]
    out = ask_robot(body)
    if not out or "[" not in out:
        return None
    nums = out[out.index("[") + 1: out.index("]")].split(",")
    try:
        return [float(x) for x in nums]
    except ValueError:
        return None


def goto_j(q, v=0.15, a=0.4):
    """Slow movej to a joint target. Motion happens: only call with the
    cell confirmed clear and pendant in Remote."""
    qs = "[" + ",".join(f"{v_:.6f}" for v_ in q) + "]"
    body = [
        f"movej({qs}, a={a}, v={v})",
        f'socket_open("{MAC}", {READBACK_PORT}, "rb")',
        'socket_send_string("MOVE_DONE", "rb")',
        'socket_close("rb")',
    ]
    return ask_robot(body, timeout=60.0)
