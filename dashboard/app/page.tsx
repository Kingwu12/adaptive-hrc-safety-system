"use client";

import { useEffect, useMemo, useRef, useState } from "react";

type Feature = {
  d: number; d_dot: number; speed: number; v_proj: number;
  v_lat_frac: number; a_proj: number; torso_facing: number;
};

type Status = {
  connected: boolean;
  packets: number;
  packet_rate_hz: number;
  stale: boolean;
  age_s: number | null;
  position: number[] | null;
  feature: Feature | null;
  posterior: Record<string, number>;
  hmm_state: string | null;
  model_source: string;
  recording: boolean;
  session_id: string | null;
  participant_id: string | null;
  trial_id: string | null;
  label: string;
  recording_path: string | null;
  samples_written: number;
  calibration_elapsed_s: number | null;
  error?: string;
};

const EMPTY: Status = {
  connected: false, packets: 0, packet_rate_hz: 0, stale: true, age_s: null,
  position: null, feature: null, posterior: {}, hmm_state: null,
  model_source: "synthetic baseline", recording: false, session_id: null,
  participant_id: null, trial_id: null, label: "unlabelled",
  recording_path: null, samples_written: 0, calibration_elapsed_s: null,
};

const STATES = ["approaching", "working", "retreating", "hazard"];

function apiBase() {
  if (typeof window === "undefined") return "http://127.0.0.1:8765";
  return `${window.location.protocol}//${window.location.hostname}:8765`;
}

function n(value: number | null | undefined, digits = 2) {
  return value == null || !Number.isFinite(value) ? "—" : value.toFixed(digits);
}

function Sparkline({ values, color }: { values: number[]; color: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const el = canvas.current;
    if (!el || values.length < 2) return;
    const dpr = window.devicePixelRatio || 1;
    const rect = el.getBoundingClientRect();
    el.width = rect.width * dpr; el.height = rect.height * dpr;
    const ctx = el.getContext("2d"); if (!ctx) return;
    ctx.scale(dpr, dpr);
    const min = Math.min(...values), max = Math.max(...values);
    const span = Math.max(max - min, 0.01);
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.lineJoin = "round";
    ctx.beginPath();
    values.forEach((v, i) => {
      const x = (i / (values.length - 1)) * rect.width;
      const y = rect.height - 5 - ((v - min) / span) * (rect.height - 10);
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    });
    ctx.stroke();
  }, [values, color]);
  return <canvas className="spark" ref={canvas} aria-label="Recent signal history" />;
}

export default function Home() {
  const [status, setStatus] = useState<Status>(EMPTY);
  const [reachable, setReachable] = useState(false);
  const [history, setHistory] = useState<Record<string, number[]>>({ distance: [], speed: [], acceleration: [] });
  const [participant, setParticipant] = useState("P01");
  const [trial, setTrial] = useState("T01");
  const [message, setMessage] = useState("Start the local sensor service, then enable MVN Network Streamer.");

  useEffect(() => {
    let live = true;
    const poll = async () => {
      try {
        const res = await fetch(`${apiBase()}/api/status`, { cache: "no-store" });
        if (!res.ok) throw new Error("service unavailable");
        const next = await res.json() as Status;
        if (!live) return;
        setStatus(next); setReachable(true);
        if (next.feature) {
          setHistory(old => ({
            distance: [...old.distance, next.feature!.d].slice(-90),
            speed: [...old.speed, next.feature!.speed].slice(-90),
            acceleration: [...old.acceleration, next.feature!.a_proj].slice(-90),
          }));
        }
      } catch { if (live) setReachable(false); }
    };
    poll(); const timer = setInterval(poll, 250);
    return () => { live = false; clearInterval(timer); };
  }, []);

  const post = async (path: string, body: object = {}) => {
    try {
      const res = await fetch(`${apiBase()}${path}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const result = await res.json();
      if (!res.ok) throw new Error(result.error || "Request failed");
      setMessage(result.message || "Updated");
    } catch (err) { setMessage(err instanceof Error ? err.message : "Request failed"); }
  };

  const calibration = status.calibration_elapsed_s;
  const calibrationClass = calibration != null && calibration >= 270 ? "warning" : "ok";
  const dominant = useMemo(() => status.hmm_state || "waiting", [status.hmm_state]);

  return (
    <main>
      <header className="topbar">
        <div className="brand"><span className="brandMark">HRC</span><div><strong>Operator Motion Console</strong><small>Adaptive safety · Xsens MVN</small></div></div>
        <div className="statusCluster">
          <span className={`pill ${reachable ? "ok" : "offline"}`}><i />Service {reachable ? "online" : "offline"}</span>
          <span className={`pill ${status.connected ? "ok" : "offline"}`}><i />Xsens {status.connected ? "streaming" : "waiting"}</span>
          <span className="clock">{status.packet_rate_hz.toFixed(1)} Hz</span>
        </div>
      </header>

      <section className="hero">
        <div><p className="eyebrow">LIVE EXPERIMENT</p><h1>See what the safety system sees.</h1><p className="sub">Capture motion, attach ground-truth labels and inspect the exact signals entering the layered HMM.</p></div>
        <div className={`stateReadout state-${dominant}`}><span>INFERRED STATE</span><strong>{dominant}</strong><small>{status.model_source}</small></div>
      </section>

      <section className="grid">
        <article className="panel capture">
          <div className="panelHead"><div><p className="kicker">01 · CAPTURE</p><h2>Session control</h2></div><span className={`recordLamp ${status.recording ? "active" : ""}`}>{status.recording ? "REC" : "IDLE"}</span></div>
          <div className="fields"><label>Participant<input value={participant} onChange={e => setParticipant(e.target.value)} disabled={status.recording} /></label><label>Trial<input value={trial} onChange={e => setTrial(e.target.value)} disabled={status.recording} /></label></div>
          <div className="actions">
            {!status.recording ? <button className="primary" disabled={!status.connected} onClick={() => post("/api/session/start", { participant_id: participant, trial_id: trial })}>Start recording</button> : <button className="stop" onClick={() => post("/api/session/stop")}>Stop & save</button>}
          </div>
          <p className="feedback">{message}</p>
          <dl className="sessionFacts"><div><dt>Samples</dt><dd>{status.samples_written.toLocaleString()}</dd></div><div><dt>Packet age</dt><dd>{n(status.age_s, 3)} s</dd></div><div><dt>Calibration</dt><dd className={calibrationClass}>{calibration == null ? "Not marked" : `${Math.floor(calibration / 60)}:${String(Math.floor(calibration % 60)).padStart(2, "0")}`}</dd></div></dl>
          <button className="calibrate" disabled={!status.connected || status.recording} onClick={() => post("/api/calibration/mark")}>Mark Xsens calibration complete</button>
        </article>

        <article className="panel signals">
          <div className="panelHead"><div><p className="kicker">02 · SIGNALS</p><h2>Motion features</h2></div><span className={status.stale ? "warnText" : "quiet"}>{status.stale ? "STALE INPUT" : "60 Hz window"}</span></div>
          <div className="signalGrid">
            <div className="signal"><span>Distance</span><strong>{n(status.feature?.d)} <em>m</em></strong><Sparkline values={history.distance} color="#5ce1a6" /></div>
            <div className="signal"><span>Speed</span><strong>{n(status.feature?.speed)} <em>m/s</em></strong><Sparkline values={history.speed} color="#8db5ff" /></div>
            <div className="signal"><span>Closing velocity</span><strong>{n(status.feature?.v_proj)} <em>m/s</em></strong><small>Positive = moving toward robot</small></div>
            <div className="signal"><span>Acceleration</span><strong>{n(status.feature?.a_proj)} <em>m/s²</em></strong><Sparkline values={history.acceleration} color="#ffb86b" /></div>
          </div>
          <div className="coords"><span>PELVIS XYZ</span>{status.position ? status.position.map((v, i) => <code key={i}>{"xyz"[i]} {n(v, 3)}</code>) : <code>waiting for first packet</code>}</div>
        </article>

        <article className="panel labels">
          <div className="panelHead"><div><p className="kicker">03 · GROUND TRUTH</p><h2>What is actually happening?</h2></div><span className="currentLabel">{status.label}</span></div>
          <p className="help">Choose the state the participant is deliberately performing. This label is saved beside every sensor frame.</p>
          <div className="labelButtons">{STATES.map(s => <button key={s} className={status.label === s ? "selected" : ""} disabled={!status.recording} onClick={() => post("/api/label", { label: s })}>{s}</button>)}</div>
          <button className="unlabel" disabled={!status.recording} onClick={() => post("/api/label", { label: "unlabelled" })}>Mark transition / unlabelled</button>
        </article>

        <article className="panel probabilities">
          <div className="panelHead"><div><p className="kicker">04 · MODEL</p><h2>HMM belief</h2></div><span className="quiet">not ground truth</span></div>
          <div className="bars">{["approaching", "working", "retreating", "hazard"].map(s => { const value = status.posterior[s] || 0; return <div className="barRow" key={s}><span>{s}</span><div><i style={{ width: `${value * 100}%` }} /></div><strong>{Math.round(value * 100)}%</strong></div>; })}</div>
          <p className="modelNote"><b>Important:</b> this baseline model is fitted on synthetic loops until the real labelled dataset pipeline is completed.</p>
        </article>
      </section>
      <footer><span>Data remains on this Mac</span><span>{status.recording_path || "No active recording"}</span></footer>
    </main>
  );
}
