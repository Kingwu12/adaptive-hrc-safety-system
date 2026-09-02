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
  optitrack_connected: boolean;
  optitrack_age_s: number | null;
  feature: Feature | null;
  posterior: Record<string, number>;
  hmm_state: string | null;
  model_source: string;
  recording: boolean;
  session_id: string | null;
  participant_id: string | null;
  trial_id: string | null;
  label: string;
  guided_step: number | null;
  guided_steps_total: number;
  recording_path: string | null;
  samples_written: number;
  calibration_elapsed_s: number | null;
  error?: string;
};

type ParticipantSummary = {
  id: string;
  name: string;
  created_at: string | null;
  run_count: number;
  good_run_count: number;
  next_trial: string;
};

type RunSummary = {
  session_id: string;
  participant_id: string;
  participant_name: string;
  trial_id: string;
  started_at: string;
  file_name: string;
  samples: number;
  duration_s: number;
  rate_hz: number;
  stale_percent: number;
  labels: Record<string, number>;
  sequence: string[];
  quality: { grade: "good" | "review" | "repeat"; label: string; score: number; reasons: string[] };
};

type Catalog = { participants: ParticipantSummary[]; runs: RunSummary[] };

const EMPTY: Status = {
  connected: false, packets: 0, packet_rate_hz: 0, stale: true, age_s: null,
  position: null, optitrack_connected: false, optitrack_age_s: null,
  feature: null, posterior: {}, hmm_state: null,
  model_source: "synthetic baseline", recording: false, session_id: null,
  participant_id: null, trial_id: null, label: "unlabelled",
  guided_step: null, guided_steps_total: 10,
  recording_path: null, samples_written: 0, calibration_elapsed_s: null,
};

const STATES = ["approaching", "working", "retreating", "hazard"];

const GUIDED_PROTOCOL = [
  {
    label: "unlabelled", title: "GET READY",
    cue: "EXPERIMENTER: confirm the arm is low and suction is off. PARTICIPANT: pick up the panel, stand on the marked start position, and wait.",
    next: "READY — START APPROACH",
  },
  {
    label: "approaching", title: "APPROACH WITH THE PANEL",
    cue: "PARTICIPANT: walk normally from the start marker to the low gripper while carrying the panel. EXPERIMENTER: press only when the panel reaches the gripper.",
    next: "PANEL AT GRIPPER — START ALIGNING",
  },
  {
    label: "working", title: "PLACE AND ALIGN ON THE GRIPPER",
    cue: "PARTICIPANT: hold the panel flat against both suction cups. EXPERIMENTER: when aligned, press once to arm suction, then press again to grip and verify both cups.",
    next: "PANEL ALIGNED — SUCTION ON & VERIFY",
  },
  {
    label: "retreating", title: "RETREAT TO THE START MARKER",
    cue: "PARTICIPANT: let go, walk away, and return fully to the start marker. EXPERIMENTER: after the cell is clear, press once to arm and again to lift. Suction stays ON.",
    next: "CELL CLEAR — LIFT ROBOT",
  },
  {
    label: "unlabelled", title: "SIMULATED INSTALLED PANEL — PREPARE",
    cue: "The robot is holding the panel at the top because this setup has no top retaining fixture. Suction intentionally stays ON. PARTICIPANT: wait at the start marker.",
    next: "ROBOT UP — BEGIN APPROACH",
  },
  {
    label: "approaching", title: "APPROACH THE RAISED PANEL",
    cue: "Approach the raised panel normally from the marked start position.",
    next: "AT RAISED PANEL — START WORK",
  },
  {
    label: "working", title: "WORK AND WAIT FOR THE CUE",
    cue: "PARTICIPANT: perform the panel task normally on the panel held at the top. EXPERIMENTER: press the button at the exact instant you say the approved hazard cue.",
    next: "PRESS & SAY ‘HAZARD’ TOGETHER",
  },
  {
    label: "hazard", title: "PERFORM THE APPROVED CUED HAZARD",
    cue: "Participant performs only the brief, pre-briefed simulated slip or near-approach. Keep the E-stop in reach.",
    next: "PRESS THE INSTANT THE HAZARD MOTION ENDS",
  },
  {
    label: "retreating", title: "CONTROLLED RECOVERY AND RETREAT",
    cue: "PARTICIPANT: recover, turn away, and return fully to the start marker. EXPERIMENTER: when clear, press once to arm and again to lower. Suction stays ON during lowering.",
    next: "CELL CLEAR — LOWER ROBOT",
  },
  {
    label: "unlabelled", title: "ROBOT LOW — READY TO RELEASE",
    cue: "The robot is stationary at the verified low pose. PARTICIPANT: approach and firmly support the panel. EXPERIMENTER: press once to arm, then again to release suction and save the run.",
    next: "PANEL SUPPORTED — RELEASE & SAVE",
  },
] as const;

const PHYSICAL_STEPS = new Set([2, 3, 8, 9]);

function apiBase() {
  // Keep browser requests same-origin. Next proxies /api/* to the local
  // hardware service, avoiding browser private-network/CORS restrictions.
  return "";
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
      if (i) ctx.lineTo(x, y);
      else ctx.moveTo(x, y);
    });
    ctx.stroke();
  }, [values, color]);
  return <canvas className="spark" ref={canvas} aria-label="Recent signal history" />;
}

type Rig = {
  gripper?: { vacuum_A_permille?: number; vacuum_B_permille?: number; pump_rpm?: number; current_mA?: number; error?: string };
  robot?: { reachable?: boolean; robotmode?: string; safety?: string; program_state?: string; error?: string };
  pose?: { available?: boolean; tcp?: number[]; q?: number[]; error?: string };
};

/** The arm reports an all-zero joint vector when the encoders are unpowered,
 *  which forward-kinematics turns into a confident-looking but FALSE TCP.
 *  Treat that signature as "no pose", never as a reading. */
function poseTrust(rig: Rig): { ok: boolean; label: string; detail: string } {
  const p = rig.pose;
  if (!p?.available) return { ok: false, label: "TCP UNREADABLE", detail: p?.error ?? "no receive interface" };
  const q = p.q ?? [];
  if (q.length && q.every((v) => Math.abs(v) < 1e-9)) {
    return { ok: false, label: "TCP NOT TRUSTWORTHY", detail: "all joints zero — encoders unpowered" };
  }
  const mode = rig.robot?.robotmode ?? "";
  if (mode && !/RUNNING/i.test(mode)) {
    return { ok: false, label: "TCP NOT TRUSTWORTHY", detail: `robot is ${mode.replace("Robotmode: ", "")}, brakes not released` };
  }
  return { ok: true, label: "TCP LIVE", detail: "separation is measured to the real arm" };
}

function controlKey() {
  if (typeof window === "undefined") return "";
  return new URLSearchParams(window.location.search).get("k") || "";
}

/** A rig button that reports its own state. A control that silently does
 *  nothing is a hazard: the operator assumes the command landed. */
function RigButton(props: {
  tag: string; label: string; kind?: string;
  busy: string | null;
  result: { tag: string; ok: boolean; text: string; at: number } | null;
  onPress: () => void;
}) {
  const { tag, label, kind, busy, result, onPress } = props;
  const isBusy = busy === tag;
  const mine = result && result.tag === tag ? result : null;
  const cls = ["rigBtn", kind ?? "", isBusy ? "isBusy" : "", mine ? (mine.ok ? "isOk" : "isErr") : ""]
    .filter(Boolean).join(" ");
  return (
    <button className={cls} onClick={onPress} disabled={!!busy}>
      <span className="rigBtnLabel">{label}</span>
      <span className="rigBtnState">
        {isBusy ? "sending…" : mine ? (mine.ok ? `✓ ${mine.text}` : `✕ ${mine.text}`) : ""}
      </span>
    </button>
  );
}

export default function Home() {
  const [status, setStatus] = useState<Status>(EMPTY);
  const [reachable, setReachable] = useState(false);
  const [history, setHistory] = useState<Record<string, number[]>>({ distance: [], speed: [], acceleration: [] });
  const [participant, setParticipant] = useState("P01");
  const [catalog, setCatalog] = useState<Catalog>({ participants: [], runs: [] });
  const [catalogRefresh, setCatalogRefresh] = useState(0);
  const [participantEditor, setParticipantEditor] = useState<"new" | "rename" | null>(null);
  const [participantName, setParticipantName] = useState("");
  const [message, setMessage] = useState("Start the local sensor service, then enable MVN Network Streamer.");
  const [rig, setRig] = useState<Rig>({});
  const [rigBusy, setRigBusy] = useState<string | null>(null);
  const [rigResult, setRigResult] = useState<{ tag: string; ok: boolean; text: string; at: number } | null>(null);
  const [vacuum, setVacuum] = useState(60);
  const [rigMsg, setRigMsg] = useState("");
  const [tab, setTab] = useState<"operate" | "monitor">("operate");
  const [protocolWorking, setProtocolWorking] = useState(false);
  const [armedStep, setArmedStep] = useState<number | null>(null);
  const protocolBusy = useRef(false);
  const armedStepRef = useRef<number | null>(null);
  const armedAtRef = useRef(0);
  const armedUntilRef = useRef(0);
  const armedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  useEffect(() => {
    let live = true;
    const pollRig = async () => {
      try {
        const res = await fetch(`${apiBase()}/api/rig`, { cache: "no-store" });
        if (!res.ok) return;
        const next = await res.json() as Rig;
        if (live) setRig(next);
      } catch { /* rig offline is non-fatal */ }
    };
    pollRig(); const timer = setInterval(pollRig, 1500);
    return () => { live = false; clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (status.recording) return;
    let live = true;
    const pollCatalog = async () => {
      try {
        const res = await fetch(`${apiBase()}/api/catalog`, { cache: "no-store" });
        if (!res.ok) return;
        const next = await res.json() as Catalog;
        if (live) setCatalog(next);
      } catch { /* run history is non-critical to live safety control */ }
    };
    void pollCatalog();
    const timer = setInterval(pollCatalog, 10000);
    return () => { live = false; clearInterval(timer); };
  }, [status.recording, catalogRefresh]);

  const rigPost = async (path: string, body: object, id?: string) => {
    const tag = id ?? path;
    setRigBusy(tag);
    setRigResult(null);
    setRigMsg(`sending ${JSON.stringify(body)} ...`);
    const started = Date.now();
    try {
      const res = await fetch(`${apiBase()}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Control-Key": controlKey() },
        body: JSON.stringify(body),
      });
      const result = await res.json();
      if (!res.ok) {
        throw new Error(res.status === 403
          ? "REJECTED 403 — no valid control key. Add ?k=<key> to this page's URL."
          : (result.error || `Request failed (${res.status})`));
      }
      const ms = Date.now() - started;
      setRigResult({ tag, ok: true, text: `done in ${ms} ms`, at: Date.now() });
      setRigMsg(JSON.stringify(result).slice(0, 220));
    } catch (err) {
      const text = err instanceof Error ? err.message : "Request failed";
      setRigResult({ tag, ok: false, text, at: Date.now() });
      setRigMsg(text);
    } finally {
      setRigBusy(null);
    }
  };

  const post = async (path: string, body: object = {}) => {
    try {
      const res = await fetch(`${apiBase()}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Control-Key": controlKey() },
        body: JSON.stringify(body),
      });
      const result = await res.json();
      if (!res.ok) throw new Error(result.error || "Request failed");
      setMessage(result.message || "Updated");
      return result as {
        message?: string;
        completed?: boolean;
        trial_id?: string;
        participant?: ParticipantSummary;
      };
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Request failed");
      return null;
    }
  };

  const startRecording = async () => {
    await post("/api/protocol/start", { participant_id: participant });
  };

  const abortRecording = async () => {
    const result = await post("/api/session/stop");
    if (result) setCatalogRefresh(value => value + 1);
  };

  const saveParticipant = async () => {
    const result = await post("/api/participants", {
      name: participantName,
      participant_id: participantEditor === "rename" ? participant : undefined,
    });
    if (!result?.participant) return;
    const saved = result.participant;
    setCatalog(old => ({
      ...old,
      participants: [...old.participants.filter(row => row.id !== saved.id), saved]
        .sort((a, b) => a.id.localeCompare(b.id)),
    }));
    setParticipant(saved.id);
    setParticipantEditor(null);
    setParticipantName("");
    setCatalogRefresh(value => value + 1);
  };

  const advanceProtocol = async () => {
    if (!status.recording || status.guided_step == null || protocolBusy.current) return;
    protocolBusy.current = true;
    setProtocolWorking(true);
    try {
      const result = await post("/api/protocol/complete", { vacuum });
      if (result?.completed) {
        setMessage(`${result.message || "Run saved."} Checking quality and preparing the next trial…`);
        setCatalogRefresh(value => value + 1);
      }
    } finally {
      protocolBusy.current = false;
      setProtocolWorking(false);
    }
  };

  const clearArmedAction = () => {
    armedStepRef.current = null;
    armedAtRef.current = 0;
    armedUntilRef.current = 0;
    setArmedStep(null);
    if (armedTimerRef.current) clearTimeout(armedTimerRef.current);
    armedTimerRef.current = null;
  };

  const armGuidedAction = async (step: number) => {
    protocolBusy.current = true;
    setProtocolWorking(true);
    try {
      if (!await post("/api/protocol/arm")) return;
      const now = Date.now();
      armedStepRef.current = step;
      armedAtRef.current = now;
      armedUntilRef.current = now + 5000;
      setArmedStep(step);
      armedTimerRef.current = setTimeout(clearArmedAction, 5000);
    } finally {
      protocolBusy.current = false;
      setProtocolWorking(false);
    }
  };

  const confirmGuidedAction = () => {
    if (!status.recording || status.guided_step == null || protocolBusy.current) return;
    const step = status.guided_step;
    if (!PHYSICAL_STEPS.has(step)) {
      clearArmedAction();
      void advanceProtocol();
      return;
    }
    const now = Date.now();
    if (
      armedStepRef.current === step
      && now - armedAtRef.current >= 750
      && now < armedUntilRef.current
    ) {
      clearArmedAction();
      void advanceProtocol();
      return;
    }
    if (armedStepRef.current === step && now < armedUntilRef.current) return;
    clearArmedAction();
    void armGuidedAction(step);
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (event.repeat || ["INPUT", "TEXTAREA", "SELECT"].includes(target?.tagName ?? "")) return;
      // Enter on a focused button already produces its native click. Presenter
      // keys such as ArrowRight/PageDown do not, so allow those to bubble into
      // the guided-run handler even while the last action button has focus.
      if (target?.tagName === "BUTTON" && event.key === "Enter") return;
      if (!status.recording) return;
      const direct: Record<string, string> = {
        "0": "unlabelled", "1": "approaching", "2": "working",
        "3": "retreating", "4": "hazard",
      };
      if (["Enter", "ArrowRight", "PageDown"].includes(event.key)) {
        event.preventDefault();
        confirmGuidedAction();
      } else if (direct[event.key]) {
        event.preventDefault();
        void post("/api/label", { label: direct[event.key] });
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  const calibration = status.calibration_elapsed_s;
  const calibrationClass = calibration != null && calibration >= 270 ? "warning" : "ok";
  const dominant = useMemo(() => status.hmm_state || "waiting", [status.hmm_state]);
  const guidedIndex = Math.min(status.guided_step ?? 0, GUIDED_PROTOCOL.length - 1);
  const guided = GUIDED_PROTOCOL[guidedIndex];
  const selectedParticipant = catalog.participants.find(row => row.id === participant);
  const participantRuns = catalog.runs.filter(run => run.participant_id === participant);
  const nextTrial = selectedParticipant?.next_trial ?? "T01";

  return (
    <main>
      <header className="topbar">
        <div className="brand"><span className="brandMark">HRC</span><div><strong>Operator Motion Console</strong><small>Adaptive safety · Xsens MVN</small></div></div>
        <div className="statusCluster">
          <span className={`pill ${reachable ? "ok" : "offline"}`}><i />Service {reachable ? "online" : "offline"}</span>
          <span className={`pill ${status.connected ? "ok" : "offline"}`}><i />Xsens {status.connected ? "streaming" : "waiting"}</span>
          <span className={`pill ${status.optitrack_connected ? "ok" : "offline"}`}><i />OptiTrack {status.optitrack_connected ? "tracking" : "waiting"}</span>
          <span className="clock">{status.packet_rate_hz.toFixed(1)} Hz</span>
        </div>
      </header>

      <section className="hero">
        <div><p className="eyebrow">LIVE EXPERIMENT</p><h1>See what the safety system sees.</h1><p className="sub">Capture motion, attach ground-truth labels and inspect the exact signals entering the layered HMM.</p></div>
        <div className={`stateReadout state-${dominant}`}><span>INFERRED STATE</span><strong>{dominant}</strong><small>{status.model_source}</small></div>
      </section>

      <nav className="tabs" role="tablist" aria-label="Console view">
        <button role="tab" aria-selected={tab === "operate"} className={tab === "operate" ? "tabBtn on" : "tabBtn"}
          onClick={() => setTab("operate")}>
          <span className="tabName">Operate</span>
          <span className="tabHint">run the rig and the session</span>
        </button>
        <button role="tab" aria-selected={tab === "monitor"} className={tab === "monitor" ? "tabBtn on" : "tabBtn"}
          onClick={() => setTab("monitor")}>
          <span className="tabName">Monitor</span>
          <span className="tabHint">signals and model belief</span>
        </button>
      </nav>

      {tab === "operate" && status.recording && (
        <section className={`runDirector label-${guided.label}`} aria-live="polite">
          <div className="runDirectorHead">
            <span>LIVE RUN DIRECTOR · STEP {guidedIndex + 1}/{GUIDED_PROTOCOL.length}</span>
            <strong>RECORDING LABEL: {status.label.toUpperCase()}</strong>
          </div>
          <h2>{guided.title}</h2>
          <p>{guided.cue}</p>
          {guidedIndex >= 3 && guidedIndex <= 8 && <div className="simPanelNote">SIMULATION RULE: no top fixture means suction stays ON while the panel is at the top. Never release an unsupported panel overhead.</div>}
          <button onClick={confirmGuidedAction} disabled={protocolWorking}>{protocolWorking ? "CHECKING / WORKING…" : armedStep === guidedIndex ? `PRESS AGAIN NOW — ${guided.next}` : guided.next}</button>
          <small>The dashboard operator advances each real phase. Suction and robot motion require two separate presses within five seconds.</small>
        </section>
      )}

      <section className={`grid tab-${tab}`}>
        <article className="panel capture">
          <div className="panelHead"><div><p className="kicker">01 · CAPTURE</p><h2>Session control</h2></div><span className={`recordLamp ${status.recording ? "active" : ""}`}>{status.recording ? "REC" : "IDLE"}</span></div>
          <div className="fields">
            <label>Participant
              <select value={participant} disabled={status.recording} onChange={e => { setParticipant(e.target.value); setParticipantEditor(null); }}>
                {catalog.participants.length ? catalog.participants.map(row => <option key={row.id} value={row.id}>{row.id} — {row.name || "unnamed"}</option>) : <option value="P01">P01 — loading…</option>}
              </select>
            </label>
            <label>{status.recording ? "Current trial" : "Next trial"}
              <input value={status.recording ? status.trial_id || nextTrial : nextTrial} readOnly />
            </label>
          </div>
          <div className="participantActions">
            <button disabled={status.recording} onClick={() => { setParticipantEditor("new"); setParticipantName(""); }}>+ New participant</button>
            <button disabled={status.recording || !selectedParticipant} onClick={() => { setParticipantEditor("rename"); setParticipantName(selectedParticipant?.name || ""); }}>Name / rename selected</button>
          </div>
          {participantEditor && <div className="participantEditor">
            <input autoFocus value={participantName} maxLength={80} placeholder={participantEditor === "new" ? "New participant name" : `Name for ${participant}`} onChange={e => setParticipantName(e.target.value)} onKeyDown={e => { if (e.key === "Enter") void saveParticipant(); }} />
            <button className="primary" disabled={!participantName.trim()} onClick={() => void saveParticipant()}>{participantEditor === "new" ? "Create participant" : "Save name"}</button>
            <button onClick={() => { setParticipantEditor(null); setParticipantName(""); }}>Cancel</button>
          </div>}
          <div className="actions">
            {!status.recording ? <button className="primary" disabled={!status.connected || !status.optitrack_connected || !participant} onClick={startRecording}>Start {nextTrial} guided run</button> : <button className="stop" onClick={() => void abortRecording()}>Abort / stop & save</button>}
          </div>
          {!status.recording && <p className="startHint">The next trial number comes from the files already saved for this participant. Every attempt is preserved and counted automatically.</p>}
          <p className="feedback">{message}</p>
          <dl className="sessionFacts"><div><dt>Samples</dt><dd>{status.samples_written.toLocaleString()}</dd></div><div><dt>Packet age</dt><dd>{n(status.age_s, 3)} s</dd></div><div><dt>Calibration</dt><dd className={calibrationClass}>{calibration == null ? "Not marked" : `${Math.floor(calibration / 60)}:${String(Math.floor(calibration % 60)).padStart(2, "0")}`}</dd></div></dl>
          <button className="calibrate" disabled={!status.connected || status.recording} onClick={() => post("/api/calibration/mark")}>Mark Xsens calibration complete</button>
        </article>

        <article className="panel runHistory">
          <div className="panelHead">
            <div><p className="kicker">02 · SAVED RUNS</p><h2>{participant} {selectedParticipant?.name ? `— ${selectedParticipant.name}` : "— unnamed"}</h2></div>
            <span className="quiet">{selectedParticipant?.good_run_count ?? 0}/{selectedParticipant?.run_count ?? 0} good</span>
          </div>
          <p className="qualityNote">Capture-quality checks confirm phase coverage, order, duration, tracking freshness, and sample rate. They do not measure model accuracy.</p>
          <div className="runList">
            {participantRuns.length === 0 && <p className="emptyRuns">No saved runs yet. The first completed or aborted attempt will appear here.</p>}
            {participantRuns.map(run => <div className="runCard" key={run.session_id}>
              <div className="runCardHead">
                <div><strong>{run.trial_id}</strong><span>{run.started_at.replace("T", " ")}</span></div>
                <span className={`qualityBadge quality-${run.quality.grade}`}>{run.quality.label} · {run.quality.score}</span>
              </div>
              <div className="runMetrics">
                <span>{run.samples.toLocaleString()} samples</span><span>{run.duration_s.toFixed(1)} s</span><span>{run.rate_hz.toFixed(1)} Hz</span><span>{run.stale_percent.toFixed(2)}% stale</span>
              </div>
              <div className="labelCoverage">{STATES.map(label => <span key={label}>{label} {run.labels[label] == null ? "—" : `${n(run.labels[label], 1)}s`}</span>)}</div>
              <p>{run.quality.reasons.join(" · ")}</p>
            </div>)}
          </div>
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
          <p className="help">The experimenter advances the protocol at each real phase onset. The active label then persists on every frame until the next cue; the participant never touches this console.</p>
          <div className="guidedRun">
            <span>GUIDED RUN · STEP {guidedIndex + 1}/{GUIDED_PROTOCOL.length} · {status.label.toUpperCase()}</span>
            <strong>{guided.title}</strong>
            <p>{guided.cue}</p>
            <small>Hold each labelled state for at least 2 seconds. Press Enter or use the button.</small>
            <button className="protocolNext" disabled={!status.recording || status.guided_step == null || protocolWorking} onClick={confirmGuidedAction}>
              {protocolWorking ? "CHECKING / WORKING…" : armedStep === guidedIndex ? `PRESS AGAIN NOW — ${guided.next}` : guided.next}
            </button>
          </div>
          <p className="manualLabelTitle">Manual label override — recovery/debugging only</p>
          <div className="labelButtons">{STATES.map(s => <button key={s} className={status.label === s ? "selected" : ""} disabled={!status.recording} onClick={() => post("/api/label", { label: s })}>{s}</button>)}</div>
          <button className="unlabel" disabled={!status.recording} onClick={() => post("/api/label", { label: "unlabelled" })}>Mark transition / unlabelled</button>
          <p className="shortcutHelp"><kbd>Enter</kbd> next guided phase · <kbd>1</kbd> approach · <kbd>2</kbd> work · <kbd>3</kbd> retreat · <kbd>4</kbd> hazard · <kbd>0</kbd> unlabelled</p>
        </article>

        <article className="panel probabilities">
          <div className="panelHead"><div><p className="kicker">04 · MODEL</p><h2>HMM belief</h2></div><span className="quiet">not ground truth</span></div>
          <div className="bars">{["approaching", "working", "retreating", "hazard"].map(s => { const value = status.posterior[s] || 0; return <div className="barRow" key={s}><span>{s}</span><div><i style={{ width: `${value * 100}%` }} /></div><strong>{Math.round(value * 100)}%</strong></div>; })}</div>
          <p className="modelNote"><b>Model source:</b> {status.model_source}. Model inference is experimental and may add caution; the independent separation envelope remains the safety floor.</p>
        </article>

        <article className="panel rig">
          <div className="panelHead">
            <div><p className="kicker">05 · RIG</p><h2>Robot &amp; gripper</h2></div>
            <span className={rig.robot?.reachable ? "quiet" : "warnText"}>
              {rig.robot?.reachable ? `${rig.robot?.robotmode ?? ""} · ${rig.robot?.safety ?? ""}` : "robot offline"}
            </span>
          </div>
          <div className={poseTrust(rig).ok ? "poseBox poseOk" : "poseBox poseBad"}>
            <div className="poseHead">
              <strong>{poseTrust(rig).label}</strong>
              <span>{poseTrust(rig).detail}</span>
            </div>
            {poseTrust(rig).ok && rig.pose?.tcp ? (
              <dl className="readouts poseXyz">
                <div><dt>x</dt><dd>{rig.pose.tcp[0].toFixed(3)} m</dd></div>
                <div><dt>y</dt><dd>{rig.pose.tcp[1].toFixed(3)} m</dd></div>
                <div><dt>z</dt><dd>{rig.pose.tcp[2].toFixed(3)} m</dd></div>
              </dl>
            ) : (
              <p className="poseWarn">Separation would be measured to a stationary phantom. Do not trust any safety number logged in this state.</p>
            )}
          </div>
          <p className="stepIntro">Normal trial actions are controlled by the guided run above. The controls below are for stopping, setup, or recovery.</p>

          <RigButton tag="stop_motion" label="STOP ARM MOTION — suction stays on" kind="stop" busy={rigBusy} result={rigResult}
            onPress={() => rigPost("/api/robot", { action: "stop" }, "stop_motion")} />

          <details className="autoBlock">
            <summary>Manual rig recovery controls</summary>
            <p className="autoWarn">Use these only for setup or recovery. During a recording, follow the live run director so hardware actions and labels stay synchronized.</p>
            <ol className="stepList">
              <li>
                <span className="stepNum">1</span>
                <RigButton tag="grip" label="Suction on" busy={rigBusy} result={rigResult}
                  onPress={() => rigPost("/api/gripper", { action: "grip", channel: "BOTH", vacuum }, "grip")} />
                <span className="stepNote">Grips the panel. The arm does not move.</span>
              </li>
              <li>
                <span className="stepNum">2</span>
                <RigButton tag="go_up" label="Go up" kind="primary" busy={rigBusy} result={rigResult}
                  onPress={() => rigPost("/api/robot", { action: "go_up" }, "go_up")} />
                <span className="stepNote">Lifts to the taught top pose, then holds.</span>
              </li>
              <li>
                <span className="stepNum">3</span>
                <RigButton tag="go_down" label="Go down" kind="primary" busy={rigBusy} result={rigResult}
                  onPress={() => rigPost("/api/robot", { action: "go_down" }, "go_down")} />
                <span className="stepNote">Lowers to the taught loading pose.</span>
              </li>
              <li>
                <span className="stepNum">4</span>
                <RigButton tag="release" label="Suction off" busy={rigBusy} result={rigResult}
                  onPress={() => rigPost("/api/gripper", { action: "release", channel: "BOTH" }, "release")} />
                <span className="stepNote">Releases the panel. Confirm it is supported first.</span>
              </li>
            </ol>
          </details>

          <details className="autoBlock">
            <summary>Automatic loop (bring-up only, not for trials)</summary>
            <p className="autoWarn">This grips and then runs the panel cycle on a continuous loop. The arm keeps moving on its own until you press STOP. Do not use it with a participant in the cell.</p>
            <RigButton tag="demo_start" label="Grip and run continuous cycle" busy={rigBusy} result={rigResult}
              onPress={() => rigPost("/api/demo", { action: "start", vacuum }, "demo_start")} />
          </details>

          <details className="autoBlock">
            <summary>Advanced maintenance controls</summary>
          <div className="actions">
            <RigButton tag="fd_on" label="Freedrive on" busy={rigBusy} result={rigResult}
              onPress={() => rigPost("/api/robot", { action: "freedrive_on" }, "fd_on")} />
            <RigButton tag="fd_off" label="Freedrive off" busy={rigBusy} result={rigResult}
              onPress={() => rigPost("/api/robot", { action: "freedrive_off" }, "fd_off")} />
            <button className="calibrate" onClick={() => rigPost("/api/cycle", { action: "fastening_complete" })}>FASTENING COMPLETE</button>
          </div>
          <div className="fields">
            <label>Vacuum {vacuum}%
              <input type="range" min={10} max={80} value={vacuum} onChange={e => setVacuum(parseInt(e.target.value))} />
            </label>
          </div>
          <div className="labelButtons">
            <button onClick={() => rigPost("/api/gripper", { action: "grip", channel: "BOTH", vacuum })}>Grip</button>
            <button onClick={() => rigPost("/api/gripper", { action: "release", channel: "BOTH" })}>Release</button>
            <button onClick={() => rigPost("/api/robot", { action: "power_on" })}>Power on</button>
            <button onClick={() => rigPost("/api/robot", { action: "brake_release" })}>Brake release</button>
            <button onClick={() => rigPost("/api/robot", { action: "run_cycle" })}>Run cycle (no grip)</button>
            <button onClick={() => rigPost("/api/robot", { action: "unlock" })}>Unlock protective stop</button>
            <button onClick={() => rigPost("/api/robot", { action: "play" })}>Play</button>
            <button onClick={() => rigPost("/api/robot", { action: "pause" })}>Pause</button>
          </div>
          <button className="unlabel" onClick={() => rigPost("/api/robot", { action: "stop" })}>STOP PROGRAM</button>
          </details>
          <dl className="sessionFacts">
            <div><dt>Vacuum A</dt><dd>{rig.gripper?.vacuum_A_permille ?? "—"}‰</dd></div>
            <div><dt>Vacuum B</dt><dd>{rig.gripper?.vacuum_B_permille ?? "—"}‰</dd></div>
            <div><dt>Pump</dt><dd>{rig.gripper?.pump_rpm ?? "—"} rpm</dd></div>
          </dl>
          <p className="feedback">{rigMsg || (rig.robot?.program_state ?? "")}</p>
        </article>
      </section>
      <footer><span>Data remains on this lab PC</span><span>{status.recording_path || "No active recording"}</span></footer>
    </main>
  );
}
