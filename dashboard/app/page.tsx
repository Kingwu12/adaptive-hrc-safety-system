"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { QRCodeSVG } from "qrcode.react";

type Feature = {
  d: number; d_dot: number; speed: number; v_proj: number;
  v_lat_frac: number; a_proj: number; torso_facing: number;
};

type Status = {
  automation?: {
    enabled: boolean; active: boolean; qualification_only: boolean;
    availability?: string; participant_blocker?: string;
    version: string; phase: string; reason: string; fault: boolean;
    task_sha256?: string | null;
    work_locations?: { configured: boolean; visited_count?: number; total_locations?: number };
    simulated_drilling?: { completed_count: number; simulated_task_complete: boolean; reason: string; dwell_s: number };
    presentation?: {
      stage: number | null; stages_total: number; title: string;
      instruction: string; action_label: string | null;
      sync_required: boolean; automatic_wait: boolean;
    };
  };
  connected: boolean;
  packets: number;
  packet_rate_hz: number;
  stale: boolean;
  age_s: number | null;
  position: number[] | null;
  xsens_segment_count: number;
  optitrack_connected: boolean;
  optitrack_age_s: number | null;
  feature: Feature | null;
  posterior: Record<string, number>;
  hmm_state: string | null;
  model_source: string;
  model_sha256: string;
  model_health?: { warnings: string[] };
  event_exposure?: {motion_samples: number; rapid_closing_samples: number; review_reason: string | null};
  controller_comparison?: Record<string, {speed_fraction: number; rule: string; shadow_only: boolean}> | null;
  controller_profile?: {red_radius_m: number; predictive_role: string};
  controller_output_enabled: boolean;
  controller_decision?: {condition?: string; speed_fraction: number; rule: string} | null;
  recording: boolean;
  session_id: string | null;
  participant_id: string | null;
  trial_id: string | null;
  block_label: string | null;
  within_block_trial: number | null;
  controller_condition: string | null;
  planned_event: string | null;
  collection_mode: CollectionMode;
  label: string;
  event_label: string;
  guided_step: number | null;
  guided_steps_total: number;
  recording_path: string | null;
  samples_written: number;
  calibration_elapsed_s: number | null;
  mvn_native_recording_reference: string | null;
  motive_recording_reference: string | null;
  video_recording_reference: string | null;
  manifest_path: string | null;
  sync_marker_count: number;
  error?: string;
};

type ParticipantSummary = {
  id: string;
  name: string;
  created_at: string | null;
  collection_mode: CollectionMode;
  run_count: number;
  good_run_count: number;
  next_trial: string;
};

type RunSummary = {
  session_id: string;
  participant_id: string;
  participant_name: string;
  trial_id: string;
  block_label?: string | null;
  within_block_trial?: number | null;
  controller_condition?: string | null;
  planned_event?: string | null;
  collection_mode: CollectionMode;
  started_at: string;
  file_name: string;
  samples: number;
  duration_s: number;
  rate_hz: number;
  stale_percent: number;
  labels: Record<string, number>;
  events: Record<string, number>;
  sequence: string[];
  quality: { grade: "good" | "review" | "repeat"; label: string; score: number; reasons: string[] };
};

type Catalog = { participants: ParticipantSummary[]; runs: RunSummary[] };

type CollectionMode = "participant_study" | "qualification" | "model_development";
type StudySlot = {
  block: "A" | "B" | "C";
  withinBlockTrial: 1 | 2 | 3;
  controller: "fixed zone" | "reactive SSM" | "predictive SSM";
  event: "clean" | "distractor" | "rapid intrusion";
};

const EMPTY: Status = {
  connected: false, packets: 0, packet_rate_hz: 0, stale: true, age_s: null,
  position: null, xsens_segment_count: 0,
  optitrack_connected: false, optitrack_age_s: null,
  feature: null, posterior: {}, hmm_state: null,
  model_source: "synthetic baseline", recording: false, session_id: null,
  model_sha256: "synthetic-baseline",
  controller_output_enabled: false,
  participant_id: null, trial_id: null, label: "unlabelled", event_label: "none",
  block_label: null, within_block_trial: null, controller_condition: null, planned_event: null,
  collection_mode: "model_development",
  guided_step: null, guided_steps_total: 10,
  recording_path: null, samples_written: 0, calibration_elapsed_s: null,
  mvn_native_recording_reference: null,
  motive_recording_reference: null, video_recording_reference: null,
  manifest_path: null,
  sync_marker_count: 0,
};

const STATES = ["approaching", "working", "retreating"];
const CONTROLLER_ORDERS = [
  ["fixed zone", "reactive SSM", "predictive SSM"],
  ["fixed zone", "predictive SSM", "reactive SSM"],
  ["reactive SSM", "fixed zone", "predictive SSM"],
  ["reactive SSM", "predictive SSM", "fixed zone"],
  ["predictive SSM", "fixed zone", "reactive SSM"],
  ["predictive SSM", "reactive SSM", "fixed zone"],
] as const;
const CONTROLLER_NAMES: Record<string, StudySlot["controller"]> = {
  static: "fixed zone", fixed_zone: "fixed zone",
  dynamic_ssm: "reactive SSM", adaptive: "predictive SSM",
};
const EVENT_ORDERS = [
  ["clean", "distractor", "rapid intrusion"],
  ["clean", "rapid intrusion", "distractor"],
  ["distractor", "clean", "rapid intrusion"],
  ["distractor", "rapid intrusion", "clean"],
  ["rapid intrusion", "clean", "distractor"],
  ["rapid intrusion", "distractor", "clean"],
] as const;

function participantNumber(id: string) {
  const match = id.match(/(\d+)/);
  return Math.max(1, Number(match?.[1] || 1));
}

function studySchedule(participantId: string): StudySlot[] {
  const seed = participantNumber(participantId) - 1;
  const controllerOrder = CONTROLLER_ORDERS[seed % CONTROLLER_ORDERS.length];
  return (["A", "B", "C"] as const).flatMap((block, blockIndex) => {
    const events = EVENT_ORDERS[(seed + blockIndex) % EVENT_ORDERS.length];
    return events.map((event, trialIndex) => ({
      block,
      withinBlockTrial: (trialIndex + 1) as 1 | 2 | 3,
      controller: controllerOrder[blockIndex],
      event,
    }));
  });
}

const GUIDED_PROTOCOL = [
  {
    label: "unlabelled", title: "GET READY",
    cue: "Suction is already on. PARTICIPANT: pick up the panel, stand on the marked start position, and wait.",
    next: "READY — START APPROACH",
  },
  {
    label: "approaching", title: "APPROACH WITH THE PANEL",
    cue: "PARTICIPANT: walk normally from the start marker to the low gripper while carrying the panel. EXPERIMENTER: press only when the panel reaches the gripper.",
    next: "PANEL AT GRIPPER — START ALIGNING",
  },
  {
    label: "working", title: "PLACE AND ALIGN ON THE GRIPPER",
    cue: "PARTICIPANT: seat the panel flat against both running suction cups. Press once when both cups have sealed; a weak seal stays on so the panel can be reseated.",
    next: "PANEL SEALED — VERIFY GRIP",
  },
  {
    label: "retreating", title: "RETREAT TO THE START MARKER",
    cue: "Press once to request the lift. The selected experiment controller will hold, slow, stop, or resume the robot continuously from the live participant-zone signal.",
    next: "REQUEST LIFT — CONTROLLER GATES MOTION",
  },
  {
    label: "unlabelled", title: "SIMULATED INSTALLED PANEL — PREPARE",
    cue: "The robot reached the top and suction remains on. The participant may begin the second approach immediately.",
    next: "AUTOMATICALLY CONTINUING",
  },
  {
    label: "approaching", title: "APPROACH THE RAISED PANEL",
    cue: "Approach the raised panel normally from the marked start position.",
    next: "AT RAISED PANEL — START WORK",
  },
  {
    label: "working", title: "COMPLETE ONE LAP",
    cue: "PARTICIPANT: complete the lap and simulated drilling gestures. EXPERIMENTER: press Lap complete once when finished, then have the participant retreat.",
    next: "LAP COMPLETE — RETREAT",
  },
  {
    label: "working", title: "COMPLETE THE PANEL TASK",
    cue: "Continue the same task normally. Do not insert another hazard or distractor event.",
    next: "TASK COMPLETE — RETREAT",
  },
  {
    label: "retreating", title: "CONTROLLED RECOVERY AND RETREAT",
    cue: "Press once to request lowering. The selected controller gates the motion continuously. Suction stays on while moving and releases automatically 1.5 seconds after the verified low pose.",
    next: "REQUEST LOWER — CONTROLLER GATES MOTION",
  },
  {
    label: "unlabelled", title: "ROBOT LOW — READY TO RELEASE",
    cue: "The robot is at the verified low support. Suction is releasing and the run is saving automatically.",
    next: "RELEASING & SAVING",
  },
] as const;

type ParticipantFormStage = "intake" | "block" | "end";
type FormAccess = Record<ParticipantFormStage, {
  accessible_without_login: boolean;
  responder_route_available: boolean;
  requires_monash_login: boolean;
  http_status: number | null;
  error?: string;
}>;
type FormCompletion = {
  tracking_configured: boolean;
  tracking_available: boolean;
  submitted: boolean;
  participant_id: string;
  stage: ParticipantFormStage;
  block?: string | null;
  checked_utc?: string;
  error?: string;
};

const PARTICIPANT_FORMS: Record<ParticipantFormStage, {
  label: string;
  baseUrl: string;
  participantEntry: string;
}> = {
  intake: {
    label: "Intake",
    baseUrl: "https://docs.google.com/forms/d/e/1FAIpQLSce3ywyZ9OFginm-8-Kk2GqH5rSl4UxfDqiieAg5iomivF3xA/viewform",
    participantEntry: "entry.266356234",
  },
  block: {
    label: "Block feedback",
    baseUrl: "https://docs.google.com/forms/d/e/1FAIpQLSeKgkIe5wdqEuFGnOuGxPpqD8ssQdSAR09oxrnwEQyzCPJviA/viewform",
    participantEntry: "entry.528851826",
  },
  end: {
    label: "End survey",
    baseUrl: "https://docs.google.com/forms/d/e/1FAIpQLSd4gfX2ljOfRFxyeYq2B-haGNhENzA6dCjnmhYTIXGpVxc87g/viewform",
    participantEntry: "entry.377617610",
  },
};

function participantFormUrl(stage: ParticipantFormStage, participantId: string) {
  const form = PARTICIPANT_FORMS[stage];
  const params = new URLSearchParams({
    usp: "pp_url",
    [form.participantEntry]: participantId,
  });
  return `${form.baseUrl}?${params.toString()}`;
}

function studyFormKey(participantId: string, stage: ParticipantFormStage, block?: string) {
  return `${participantId}:${stage === "block" ? `block-${block || "A"}` : stage}`;
}

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
  if (rig.robot?.reachable === false) {
    return { ok: false, label: "ROBOT OFFLINE", detail: rig.robot.error ?? "robot Dashboard status unavailable" };
  }
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
  const [workspaceMode, setWorkspaceMode] = useState<CollectionMode>("participant_study");
  const [participant, setParticipant] = useState("");
  const [catalog, setCatalog] = useState<Catalog>({ participants: [], runs: [] });
  const [catalogRefresh, setCatalogRefresh] = useState(0);
  const [participantEditor, setParticipantEditor] = useState<"new" | "rename" | null>(null);
  const [participantName, setParticipantName] = useState("");
  const [participantSaving, setParticipantSaving] = useState(false);
  const participantSaveBusy = useRef(false);
  const participantRevision = useRef(0);
  const [mvnRecordingConfirmed, setMvnRecordingConfirmed] = useState(false);
  const [mvnRecordingReference, setMvnRecordingReference] = useState("");
  const [motiveRecordingReference, setMotiveRecordingReference] = useState("");
  const [videoRecordingReference, setVideoRecordingReference] = useState("");
  const blockLabel = "A";
  const [plannedEvent] = useState("clean");
  const [message, setMessage] = useState("");
  const [rig, setRig] = useState<Rig>({});
  const [rigBusy, setRigBusy] = useState<string | null>(null);
  const [rigResult, setRigResult] = useState<{ tag: string; ok: boolean; text: string; at: number } | null>(null);
  const [vacuum, setVacuum] = useState(60);
  const [rigMsg, setRigMsg] = useState("");
  const [tab, setTab] = useState<"operate" | "monitor">("operate");
  const [phoneStage, setPhoneStage] = useState<ParticipantFormStage>("intake");
  const [phoneFullscreen, setPhoneFullscreen] = useState(false);
  const [verifiedForms, setVerifiedForms] = useState<Record<ParticipantFormStage, boolean>>({
    intake: false, block: false, end: false,
  });
  const [formAccess, setFormAccess] = useState<FormAccess | null>(null);
  const [formCompletion, setFormCompletion] = useState<FormCompletion | null>(null);
  const [completedStudyForms, setCompletedStudyForms] = useState<Record<string, boolean>>({});
  const [protocolWorking, setProtocolWorking] = useState(false);
  const protocolBusy = useRef(false);

  useEffect(() => {
    let live = true;
    const poll = async () => {
      try {
        const res = await fetch(`${apiBase()}/api/status`, { cache: "no-store" });
        if (!res.ok) throw new Error("service unavailable");
        const next = await res.json() as Status;
        if (!live) return;
        setStatus(next); setReachable(true);
        if (!next.connected || next.xsens_segment_count < 23 || !next.optitrack_connected
          || next.calibration_elapsed_s == null || next.calibration_elapsed_s > 300) {
          setMvnRecordingConfirmed(false);
        }
        if (next.feature) {
          setHistory(old => ({
            distance: [...old.distance, next.feature!.d].slice(-90),
            speed: [...old.speed, next.feature!.speed].slice(-90),
            acceleration: [...old.acceleration, next.feature!.a_proj].slice(-90),
          }));
        }
      } catch {
        if (live) {
          setReachable(false);
          setMvnRecordingConfirmed(false);
        }
      }
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
        if (live) {
          setRig(next);
          if (!poseTrust(next).ok) setMvnRecordingConfirmed(false);
        }
      } catch { /* rig offline is non-fatal */ }
    };
    pollRig(); const timer = setInterval(pollRig, 1500);
    return () => { live = false; clearInterval(timer); };
  }, []);

  useEffect(() => {
    if (status.recording) return;
    let live = true;
    const pollCatalog = async () => {
      const revision = participantRevision.current;
      try {
        const res = await fetch(`${apiBase()}/api/catalog`, { cache: "no-store" });
        if (!res.ok) return;
        const next = await res.json() as Catalog;
        if (live && revision === participantRevision.current && !participantSaveBusy.current) {
          setCatalog(next);
          setParticipant(current => {
            const available = next.participants.filter(row => row.collection_mode === workspaceMode);
            return available.some(row => row.id === current) ? current : available[0]?.id ?? "";
          });
        }
      } catch { /* run history is non-critical to live safety control */ }
    };
    void pollCatalog();
    const timer = setInterval(pollCatalog, 10000);
    return () => { live = false; clearInterval(timer); };
  }, [status.recording, catalogRefresh, workspaceMode]);

  useEffect(() => {
    let live = true;
    const checkForms = async () => {
      try {
        const response = await fetch(`${apiBase()}/api/forms/status`, { cache: "no-store" });
        if (!response.ok) return;
        const payload = await response.json() as { forms: FormAccess };
        if (live) setFormAccess(payload.forms);
      } catch { /* Manual participant-device verification is still required. */ }
    };
    void checkForms();
    const timer = setInterval(checkForms, 60000);
    return () => { live = false; clearInterval(timer); };
  }, []);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPhoneFullscreen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      try {
        const saved = window.localStorage.getItem("hrc-study-form-handoffs-v1");
        if (saved) setCompletedStudyForms(JSON.parse(saved));
      } catch { /* A form handoff can still be marked in this browser session. */ }
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const setStudyFormComplete = (stage: ParticipantFormStage, block: string | undefined, complete: boolean) => {
    if (!participant) return;
    setCompletedStudyForms(old => {
      const next = { ...old, [studyFormKey(participant, stage, block)]: complete };
      try { window.localStorage.setItem("hrc-study-form-handoffs-v1", JSON.stringify(next)); } catch { /* non-fatal */ }
      return next;
    });
  };

  const chooseWorkspaceMode = (mode: CollectionMode) => {
    setWorkspaceMode(mode);
    const available = catalog.participants.filter(row => row.collection_mode === mode);
    setParticipant(current => available.some(row => row.id === current) ? current : available[0]?.id ?? "");
  };

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

  const startInFlight = useRef(false);
  const [startBusy, setStartBusy] = useState(false);
  const startRecording = async (slot?: StudySlot, references?: {
    mvn: string;
    motive: string;
    video: string;
  }, recordingsConfirmed = mvnRecordingConfirmed) => {
    if (startInFlight.current) return;
    startInFlight.current = true;
    setStartBusy(true);
    try {
    const isStructuredRun = workspaceMode !== "model_development";
    if (isStructuredRun && !slot) {
      setMessage("No assigned study slot is selected. Refresh the session before starting.");
      return;
    }
    const result = await post("/api/protocol/start", {
      participant_id: participant,
      mvn_recording_confirmed: recordingsConfirmed,
      mvn_recording_reference: references?.mvn ?? mvnRecordingReference.trim(),
      block_label: isStructuredRun ? slot?.block : undefined,
      within_block_trial: isStructuredRun ? slot?.withinBlockTrial : undefined,
      controller_condition: isStructuredRun ? slot?.controller : undefined,
      planned_event: isStructuredRun ? slot?.event : undefined,
      collection_mode: workspaceMode,
      automatic: workspaceMode === "qualification" && status.automation?.enabled === true,
      vacuum,
      motive_recording_reference: isStructuredRun ? (references?.motive ?? motiveRecordingReference.trim()) : undefined,
      video_recording_reference: isStructuredRun ? (references?.video ?? videoRecordingReference.trim()) : undefined,
    });
    if (result) {
      setMvnRecordingConfirmed(false);
      setMvnRecordingReference("");
      setMotiveRecordingReference("");
      setVideoRecordingReference("");
    }
    } finally {
      startInFlight.current = false;
      setStartBusy(false);
    }
  };

  const abortRecording = async () => {
    const result = await post("/api/session/stop");
    if (result) setCatalogRefresh(value => value + 1);
  };

  const saveParticipant = async () => {
    if (participantSaveBusy.current) return;
    participantSaveBusy.current = true;
    participantRevision.current += 1;
    setParticipantSaving(true);
    try {
      const result = await post("/api/participants", {
        name: participantName,
        participant_id: participantEditor === "rename" ? participant : undefined,
        collection_mode: workspaceMode,
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
    } finally {
      participantRevision.current += 1;
      participantSaveBusy.current = false;
      setParticipantSaving(false);
    }
  };

  const createStructuredParticipant = async () => {
    if (participantSaveBusy.current || status.recording) return;
    participantSaveBusy.current = true;
    participantRevision.current += 1;
    setParticipantSaving(true);
    try {
      const result = await post("/api/participants", {
        name: "",
        collection_mode: workspaceMode,
      });
      if (!result?.participant) return;
      const saved = result.participant;
      setCatalog(old => ({
        ...old,
        participants: [...old.participants.filter(row => row.id !== saved.id), saved]
          .sort((a, b) => a.id.localeCompare(b.id)),
      }));
      setParticipant(saved.id);
      setCatalogRefresh(value => value + 1);
    } finally {
      participantRevision.current += 1;
      participantSaveBusy.current = false;
      setParticipantSaving(false);
    }
  };

  const advanceProtocol = async () => {
    if (!status.recording || status.guided_step == null || protocolBusy.current) return;
    protocolBusy.current = true;
    setProtocolWorking(true);
    try {
      const combineWorkConfirmations = !status.automation?.active && status.guided_step === 6;
      let result = await post("/api/protocol/complete", { vacuum });
      // Steps 6 and 7 label the same work interval and issue no hardware command.
      // Only combine the expected adjacent annotation; never skip a motion step.
      if (combineWorkConfirmations && result?.guided_step === 7) {
        result = await post("/api/protocol/complete", { vacuum });
      }
      if (result?.completed) {
        setMessage(`${result.message || "Run saved."} Checking quality and preparing the next trial…`);
        setCatalogRefresh(value => value + 1);
      }
    } finally {
      protocolBusy.current = false;
      setProtocolWorking(false);
    }
  };

  const confirmGuidedAction = () => {
    if (!status.recording || status.guided_step == null || protocolBusy.current) return;
    const step = status.guided_step;
    if (status.automation?.active && (status.automation.fault || ![7, 9].includes(step))) return;
    void advanceProtocol();
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
        if (event.key !== "4" || (status.planned_event || plannedEvent) === "rapid intrusion") {
          void post("/api/label", { label: direct[event.key] });
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  const calibration = status.calibration_elapsed_s;
  const xsensComplete = status.connected && status.xsens_segment_count >= 23;
  const calibrationClass = calibration != null && calibration >= 270 ? "warning" : "ok";
  const dominant = useMemo(() => status.hmm_state || "waiting", [status.hmm_state]);
  const guidedIndex = Math.min(status.guided_step ?? 0, GUIDED_PROTOCOL.length - 1);
  const guided = GUIDED_PROTOCOL[guidedIndex];
  const manualStepNumber = [1, 2, 3, 4, 4, 5, 6, 6, 7, 8][guidedIndex] ?? 1;
  const protocolBusyLabel = [3, 8].includes(guidedIndex)
    ? "MOTION REQUEST ACTIVE — CONTROLLER GATING…"
    : "CHECKING / WORKING…";
  const modeParticipants = catalog.participants.filter(row => row.collection_mode === workspaceMode);
  const selectedParticipant = modeParticipants.find(row => row.id === participant);
  const participantRuns = catalog.runs.filter(run =>
    run.participant_id === participant && run.collection_mode === workspaceMode);
  const nextTrial = selectedParticipant?.next_trial ?? "T01";
  const schedule = studySchedule(participant || "P01");
  const acceptedStudyKeys = new Set(participantRuns
    .filter(run => run.quality.grade === "good")
    .map(run => `${run.block_label}-${run.within_block_trial}`));
  const nextStudySlot = schedule.find(slot =>
    !acceptedStudyKeys.has(`${slot.block}-${slot.withinBlockTrial}`));
  const acceptedStudyRuns = acceptedStudyKeys.size;
  const intakeComplete = !!completedStudyForms[studyFormKey(participant, "intake")];
  const blockAFormComplete = !!completedStudyForms[studyFormKey(participant, "block", "A")];
  const blockBFormComplete = !!completedStudyForms[studyFormKey(participant, "block", "B")];
  const blockCFormComplete = !!completedStudyForms[studyFormKey(participant, "block", "C")];
  const finalFormComplete = !!completedStudyForms[studyFormKey(participant, "end")];
  const robotPose = poseTrust(rig);
  const calibrationReady = calibration != null && calibration <= 300;
  const initialRigReady = reachable
    && xsensComplete
    && status.optitrack_connected
    && robotPose.ok
    && calibrationReady;
  const dueStudyForm: { stage: ParticipantFormStage; block?: "A" | "B" | "C"; title: string } | null = !participant ? null
    : !intakeComplete ? { stage: "intake", title: "Complete intake" }
      : acceptedStudyRuns >= 3 && !blockAFormComplete ? { stage: "block", block: "A", title: "Complete Block A feedback" }
        : acceptedStudyRuns >= 6 && !blockBFormComplete ? { stage: "block", block: "B", title: "Complete Block B feedback" }
          : acceptedStudyRuns >= 9 && !blockCFormComplete ? { stage: "block", block: "C", title: "Complete Block C feedback" }
            : acceptedStudyRuns >= 9 && !finalFormComplete ? { stage: "end", title: "Complete final survey and debrief" }
              : null;
  const flowSteps = [
    { label: "1 · Intake", complete: intakeComplete, current: dueStudyForm?.stage === "intake" },
    { label: "2 · Suit & calibrate", complete: acceptedStudyRuns > 0 || initialRigReady, current: intakeComplete && acceptedStudyRuns === 0 && !dueStudyForm && !initialRigReady },
    { label: "3 · Block A", complete: acceptedStudyRuns >= 3, current: acceptedStudyRuns < 3 && intakeComplete && !dueStudyForm && (acceptedStudyRuns > 0 || initialRigReady) },
    { label: "4 · Block A form", complete: blockAFormComplete, current: dueStudyForm?.stage === "block" && dueStudyForm.block === "A" },
    { label: "5 · Block B", complete: acceptedStudyRuns >= 6, current: acceptedStudyRuns >= 3 && acceptedStudyRuns < 6 && !dueStudyForm },
    { label: "6 · Block B form", complete: blockBFormComplete, current: dueStudyForm?.stage === "block" && dueStudyForm.block === "B" },
    { label: "7 · Block C", complete: acceptedStudyRuns >= 9, current: acceptedStudyRuns >= 6 && acceptedStudyRuns < 9 && !dueStudyForm },
    { label: "8 · Block C form", complete: blockCFormComplete, current: dueStudyForm?.stage === "block" && dueStudyForm.block === "C" },
    { label: "9 · Final form & debrief", complete: finalFormComplete, current: dueStudyForm?.stage === "end" },
  ];
  const currentFlowIndex = Math.max(0, flowSteps.findIndex(step => step.current));
  const currentFlowStep = flowSteps[currentFlowIndex];
  const currentFlowLabel = currentFlowStep.label.replace(/^\d+\s*·\s*/, "");
  const activePlannedEvent = status.recording ? (status.planned_event || plannedEvent) : plannedEvent;
  const automaticActive = status.automation?.active === true;
  const automaticPresentation = status.automation?.presentation;
  const automaticWaiting = automaticActive && (status.automation?.fault === true || !automaticPresentation?.action_label);
  const guidedProgress = automaticActive
    ? automaticPresentation?.stage != null ? `STAGE ${automaticPresentation.stage}/${automaticPresentation.stages_total}` : "AUTOMATIC TRIAL"
    : `STEP ${manualStepNumber}/8`;
  const guidedTitle = automaticActive ? automaticPresentation?.title || "Automatic trial — waiting for instruction"
    : guidedIndex === 3
    ? activePlannedEvent === "rapid intrusion" ? "PERFORM THE APPROVED RAPID INTRUSION"
      : activePlannedEvent === "distractor" ? "PERFORM THE APPROVED DISTRACTOR"
        : "CLEAN CONTROL WINDOW — CONTINUE NORMALLY"
    : guided.title;
  const guidedCue = automaticActive ? automaticPresentation?.instruction || status.automation?.reason || "Waiting for trial state"
    : guidedIndex === 3
    ? activePlannedEvent === "rapid intrusion"
      ? "Request the lift once, then give the synchronized cue when motion begins. The selected controller governs the robot continuously while the pre-briefed operator performs the approved rapid movement and retreats."
      : activePlannedEvent === "distractor"
        ? "Request the lift once, then give the synchronized cue for the pre-briefed distractor when motion begins. The selected controller governs the robot continuously."
        : "Request the lift once and give no event cue. The selected controller governs the same motion continuously."
    : guided.cue;
  const guidedNext = automaticActive
    ? automaticWaiting ? "AUTOMATIC — FOLLOW THE INSTRUCTION ABOVE"
      : automaticPresentation?.action_label || "Waiting for instruction"
    : guided.next;
  const activePhoneStage = dueStudyForm?.stage ?? phoneStage;
  const activePhoneBlock = dueStudyForm?.block ?? blockLabel;
  const phoneUrl = participantFormUrl(activePhoneStage, participant);
  const phoneTitle = activePhoneStage === "intake" ? "Before the suit goes on"
    : activePhoneStage === "block" ? `After all three trials in Block ${activePhoneBlock}`
      : "After Blocks A, B and C are complete";
  const phoneInstruction = activePhoneStage === "intake"
    ? "Scan once, confirm the prefilled participant ID, then complete the intake questions."
    : activePhoneStage === "block"
      ? `Scan once after Block ${activePhoneBlock}. Confirm the prefilled ID and select Block ${activePhoneBlock} in the first question.`
      : "Scan once at the very end and complete the final comparison questions.";
  const isQualification = workspaceMode === "qualification";
  const activeFormAccess = formAccess?.[activePhoneStage];
  const formRouteBlocked = activeFormAccess?.accessible_without_login === false;
  const currentFormReady = activeFormAccess?.accessible_without_login === true;
  const formStatusText = formRouteBlocked
    ? `PUBLIC ACCESS BLOCKED (${activeFormAccess?.http_status ?? "network"})`
    : currentFormReady
      ? "PUBLIC LINK ONLINE"
      : "CHECKING PUBLIC LINK";
  const dueFormStage = dueStudyForm?.stage;
  const dueFormBlock = dueStudyForm?.block;

  useEffect(() => {
    if (!participant || !dueFormStage || !currentFormReady) return;
    let live = true;
    const checkCompletion = async () => {
      const params = new URLSearchParams({
        participant_id: participant,
        stage: dueFormStage,
      });
      if (dueFormBlock) params.set("block", dueFormBlock);
      try {
        const response = await fetch(`${apiBase()}/api/forms/completion?${params}`, { cache: "no-store" });
        if (!response.ok) return;
        const payload = await response.json() as FormCompletion;
        if (!live) return;
        setFormCompletion(payload);
        if (payload.tracking_available && payload.submitted) {
          const key = studyFormKey(participant, dueFormStage, dueFormBlock);
          setCompletedStudyForms(old => {
            const next = { ...old, [key]: true };
            try { window.localStorage.setItem("hrc-study-form-handoffs-v1", JSON.stringify(next)); } catch { /* non-fatal */ }
            return next;
          });
        }
      } catch { /* The manual confirmation remains available if the bridge is offline. */ }
    };
    void checkCompletion();
    const timer = setInterval(checkCompletion, 3000);
    return () => { live = false; clearInterval(timer); };
  }, [participant, dueFormStage, dueFormBlock, currentFormReady]);
  const activeFormCompletion = formCompletion
    && formCompletion.participant_id === participant
    && formCompletion.stage === dueFormStage
    && (dueFormStage !== "block" || formCompletion.block === dueFormBlock)
    ? formCompletion
    : null;
  const defaultMvnReference = `${participant}-${nextTrial}.mvn`;
  const defaultMotiveReference = `${participant}-${nextTrial}.tak`;
  const defaultVideoReference = `${participant}-${nextTrial}.mp4`;
  const effectiveRecordingReferences = {
    mvn: mvnRecordingReference.trim() || defaultMvnReference,
    motive: motiveRecordingReference.trim() || defaultMotiveReference,
    video: videoRecordingReference.trim() || defaultVideoReference,
  };
  const preflightChecks = [
    { key: "service", label: "Trial control", value: !reachable ? "Offline" : status.controller_output_enabled ? "Enabled" : "Robot control switched off", ready: reachable && status.controller_output_enabled },
    { key: "xsens", label: "Xsens body", value: xsensComplete ? "23/23 segments" : `${status.xsens_segment_count}/23 segments`, ready: xsensComplete },
    { key: "optitrack", label: "OptiTrack", value: status.optitrack_connected ? "Fresh stream" : "Waiting", ready: status.optitrack_connected },
    { key: "robot", label: "Robot pose", value: robotPose.ok ? "Live pose" : robotPose.label, ready: robotPose.ok },
    { key: "calibration", label: "Calibration", value: calibrationReady ? "Current" : calibration == null ? "Required" : "Expired", ready: calibrationReady },
  ];
  const readyPreflightCount = preflightChecks.filter(check => check.ready).length;
  const currentPreflight = !reachable ? {
    key: "service", owner: "SYSTEM SETUP", title: "Start the sensor service",
    detail: "Run the local sensor service on this lab PC. This page will continue automatically when it is online.",
  } : !status.controller_output_enabled ? {
    key: "control", owner: "SYSTEM SETUP", title: "Robot control is switched off",
    detail: "The dashboard can monitor tracking, but this server cannot send trial speed or stop commands. This is a lab-PC setup issue; moving the participant farther away will not resolve it.",
  } : !xsensComplete ? {
    key: "xsens", owner: "YOUR ACTION", title: "Connect the Xsens suit",
    detail: "In MVN Analyze, start Network Streamer and wait for a complete 23-segment body stream.",
  } : !status.optitrack_connected ? {
    key: "optitrack", owner: "YOUR ACTION", title: "Start OptiTrack streaming",
    detail: "Open Motive and start the configured stream. This page will continue when fresh tracking arrives.",
  } : !robotPose.ok ? {
    key: "robot", owner: "YOUR ACTION", title: "Make the robot pose trustworthy",
    detail: robotPose.detail,
  } : !calibrationReady ? {
    key: "calibration", owner: "YOUR ACTION", title: "Calibrate the Xsens suit",
    detail: "Complete the MVN calibration, then confirm it here. Calibration expires after five minutes.",
  } : !mvnRecordingConfirmed ? {
    key: "recordings", owner: "YOUR ACTION", title: "Start the three recordings",
    detail: "Start MVN, Motive and video with the matching filenames below, then confirm that all three timers are moving.",
  } : {
    key: "ready", owner: "READY", title: `Start ${nextTrial}`,
    detail: "Tracking, robot control and recording confirmations are ready. Start checks the low pose and clearance, then switches loading suction on.",
  };

  return (
    <main className={workspaceMode === "model_development" ? "developmentShell" : "studyShell"}>
      <header className="topbar">
        <div className="brand"><span className="brandMark">HRC</span><div><strong>Operator Motion Console</strong><small>Adaptive safety · Xsens MVN</small></div></div>
        <div className="statusCluster">
          <span title={`Service ${reachable ? "online" : "offline"}`} className={`pill ${reachable ? "ok" : "offline"}`}><i />{reachable ? "Online" : "Offline"}</span>
          <span title={`Xsens ${status.connected ? `${status.xsens_segment_count}/23 segments` : "waiting"}`} className={`pill ${xsensComplete ? "ok" : "offline"}`}><i />Xsens {status.connected ? `${status.xsens_segment_count}/23 segments` : "waiting"}</span>
          <span title={`OptiTrack ${status.optitrack_connected ? "tracking" : "waiting"}`} className={`pill ${status.optitrack_connected ? "ok" : "offline"}`}><i />Opti {status.optitrack_connected ? "tracking" : "waiting"}</span>
          {workspaceMode !== "model_development" && <button className="headerStop" disabled={rigBusy != null} onClick={() => rigPost("/api/robot", { action: "stop" }, "header_stop")}>STOP ARM</button>}
          <span className="clock">{status.packet_rate_hz.toFixed(1)} Hz</span>
        </div>
      </header>

      <section className="modeChooser" aria-label="Collection workflow">
        <button className={workspaceMode === "participant_study" ? "modeCard selected" : "modeCard"}
          disabled={status.recording} onClick={() => chooseWorkspaceMode("participant_study")}>
          <span>LIVE STUDY</span>
          <strong>Participant study</strong>
          <small>9 trials · reported data</small>
        </button>
        <button className={workspaceMode === "qualification" ? "modeCard selected development" : "modeCard development"}
          disabled={status.recording} onClick={() => chooseWorkspaceMode("qualification")}>
          <span>REHEARSAL</span>
          <strong>Qualification</strong>
          <small>Q-runs · not results</small>
        </button>
        <button className={workspaceMode === "model_development" ? "modeCard selected development" : "modeCard development"}
          disabled={status.recording} onClick={() => chooseWorkspaceMode("model_development")}>
          <span>TRAINING ONLY</span>
          <strong>Model development</strong>
          <small>Labelled pilot data</small>
        </button>
      </section>

      {workspaceMode !== "model_development" ? (
        <>
          <section className="studyContextBar" aria-label="Current participant session step">
            <div className="studyContextIdentity">
              <span>{isQualification ? "QUALIFICATION" : "PARTICIPANT STUDY"}</span>
              <div className="contextParticipantControl">
                {modeParticipants.length > 0 && <select aria-label="Participant code" disabled={status.recording || startBusy} value={participant} onChange={event => setParticipant(event.target.value)}>
                  {modeParticipants.map(row => <option key={row.id} value={row.id}>{row.id}</option>)}
                </select>}
                <button disabled={participantSaving || status.recording} onClick={() => void createStructuredParticipant()}>{participantSaving ? "Creating…" : `+ New ${isQualification ? "Q code" : "participant"}`}</button>
              </div>
            </div>
            <div className="currentStepChip">
              <span>STEP {currentFlowIndex + 1} OF {flowSteps.length}</span>
              <strong>{participant ? currentFlowLabel : isQualification ? "Create Q code" : "Create participant"}</strong>
            </div>
            <div className="studyCounter"><strong>{acceptedStudyRuns}/9</strong><span>trials accepted</span></div>
          </section>

          {status.recording && (
            <section className={`runDirector label-${status.event_label === "hazard" ? "hazard" : guided.label}`} aria-live="polite">
              <div className="runDirectorHead">
                <span>LIVE {isQualification ? "QUALIFICATION" : "PARTICIPANT"} RUN · BLOCK {status.block_label} · TRIAL {status.within_block_trial} · {guidedProgress}</span>
                <strong>PHASE: {status.label.toUpperCase()} · EVENT: {status.event_label.toUpperCase()}</strong>
              </div>
              <h2>{guidedTitle}</h2>
              <p>{guidedCue}</p>
              {status.controller_decision && <div className="controllerWitness" role="status">
                <strong>{status.controller_decision.speed_fraction === 0 ? "Controller requests stop" : `Controller requests ${Math.round(status.controller_decision.speed_fraction * 100)}% speed`}</strong>
                <span>{status.controller_decision.rule}</span>
                <small>Measured separation {n(status.feature?.d)} m · closing speed {n(status.feature?.v_proj)} m/s</small>
              </div>}
              {guidedIndex === 0 && <button className="syncMarker" onClick={() => void post("/api/sync")}>
                {status.sync_marker_count > 0 ? `✓ Sync marker ${status.sync_marker_count} recorded` : "Record visible shared sync marker"}
              </button>}
              {guidedIndex >= 3 && guidedIndex <= 8 && <div className="simPanelNote">No top fixture: suction stays ON while the panel is overhead. Never release an unsupported panel.</div>}
              {!automaticWaiting && <button onClick={confirmGuidedAction} disabled={protocolWorking}>{protocolWorking ? protocolBusyLabel : guidedNext}</button>}
              <button className="runAbort" onClick={() => void abortRecording()}>Abort safely &amp; preserve attempt</button>
              <small>{automaticActive ? "Automatic qualification: follow the current instruction above. Task completion requires confirmation. Faults require abort and inspection." : "One press records each real phase boundary. Lift and lower requests stay active while the selected controller gates robot speed from the live participant signal."}</small>
              <details className="controllerComparison">
                <summary>Operator: controller identity and event evidence</summary>
                <p>Recording {status.participant_id} · block {status.block_label}. Assigned controller: <strong>{status.controller_condition || "unavailable"}</strong>.</p>
                <p>Controller producing the latest decision: <strong>{CONTROLLER_NAMES[status.controller_decision?.condition || ""] || "unavailable — no identified controller decision"}</strong> ({status.controller_decision?.condition || "no identifier"}).</p>
                {status.controller_decision?.condition && CONTROLLER_NAMES[status.controller_decision.condition] !== status.controller_condition && <p className="warnText">CONTROLLER MISMATCH: abort this attempt and inspect the recorded controller identity.</p>}
                <p>Only the assigned controller commands the robot. Other values are calculated from the same input for diagnosis.</p>
                {status.controller_comparison && <table><thead><tr><th>Controller</th><th>Requested speed</th></tr></thead><tbody>
                  {Object.entries(status.controller_comparison).map(([name, value]) => <tr key={name}><td>{name}</td><td>{Math.round(value.speed_fraction * 100)}%</td></tr>)}
                </tbody></table>}
                <p>Moving event samples: {status.event_exposure?.motion_samples ?? 0} · rapid-closing samples: {status.event_exposure?.rapid_closing_samples ?? 0}</p>
                {status.event_exposure?.review_reason && <p className="warnText">{status.event_exposure.review_reason}</p>}
              </details>
            </section>
          )}

          <section className="studyLayout">
            {!status.recording && <aside className="automationReadiness" role="status">
              <strong>{isQualification
                ? status.automation?.enabled ? "Automatic rehearsal enabled" : "Automatic rehearsal is off"
                : "Participant trials: operator-confirmed"}</strong>
              <p>{isQualification
                ? status.automation?.enabled
                  ? "Start once. Grip verification, retreat, lift, lowering and supported release advance automatically. Shared sync and task completion still need your observation."
                  : "Start the lab with Start-Lab.ps1 to enable automatic rehearsals. Sensor and robot checks remain required."
                : status.automation?.participant_blocker || "Automatic participant release remains unqualified. Use Qualification to verify the full cycle before release."}</p>
              {status.model_health?.warnings.map(warning => <p key={warning} className="warnText">{warning}</p>)}
            </aside>}
            {!status.recording && <article className="panel oneStepCard">
              {!participant ? (
                <div className="oneStepAction emptyAction">
                  <span>STEP 1</span>
                  <h2>{isQualification ? "Create a rehearsal code" : "Create an anonymous participant code"}</h2>
                  <p>{isQualification
                    ? "Use a Q-code for this rehearsal. Qualification runs stay separate from participant results."
                    : "This anonymous code links every trial file and questionnaire. No participant name is required."}</p>
                  <button className="stepPrimary" disabled={participantSaving} onClick={() => void createStructuredParticipant()}>{participantSaving ? "Creating…" : `Create next ${isQualification ? "Q code" : "participant"}`}</button>
                </div>
              ) : dueStudyForm ? (
                <div className="oneStepAction formStep">
                  <div className="stepStatus"><span>PARTICIPANT HANDOFF</span><b className={currentFormReady ? "readyText" : "warnText"}>{formStatusText}</b></div>
                  <div className="inlineFormHandoff">
                    <div className={currentFormReady ? "inlineQr" : "inlineQr qrUnavailable"}>
                      {currentFormReady ? <QRCodeSVG value={phoneUrl} size={244} marginSize={2} level="M" /> : <strong>FORM UNAVAILABLE</strong>}
                    </div>
                    <div className="inlineFormCopy">
                      <span>{participant} · {dueStudyForm.stage === "block" ? `BLOCK ${dueStudyForm.block}` : dueStudyForm.stage.toUpperCase()}</span>
                      <h2>{dueStudyForm.stage === "intake" ? "Scan to begin" : dueStudyForm.title}</h2>
                      <p>{phoneInstruction}</p>
                      {activeFormCompletion?.tracking_available ? (
                        <div className="submissionWaiting" role="status"><i /><strong>Waiting for submission</strong><small>This advances automatically when the response reaches the Sheet.</small></div>
                      ) : currentFormReady ? (
                        <button className="manualSubmission" onClick={() => setStudyFormComplete(dueStudyForm.stage, dueStudyForm.block, true)}>Continue after the confirmation screen appears</button>
                      ) : null}
                      <details className="formFallback">
                        <summary>QR not scanning?</summary>
                        <a href={currentFormReady ? phoneUrl : undefined} target="_blank" rel="noreferrer">Open form on this computer</a>
                      </details>
                    </div>
                  </div>
                  {isQualification && <small className="qualificationNote">For the rehearsal, submit a clearly marked dummy response and verify its Sheet row.</small>}
                </div>
              ) : nextStudySlot ? (
                <div className={`oneStepAction trialStep action-${currentPreflight.key}`}>
                  <div className="stepStatus"><span>{currentPreflight.owner}</span><b>NEXT · {nextTrial}</b></div>
                  <h2>{currentPreflight.title}</h2>
                  <p>{currentPreflight.detail}</p>
                  <div className="trialIdentity" aria-label="Next trial assignment">
                    <strong>Block {nextStudySlot.block} · Trial {nextStudySlot.withinBlockTrial}</strong>
                    <span>{nextStudySlot.controller}</span>
                    <span>{nextStudySlot.event}</span>
                  </div>
                  <small>{isQualification && status.automation?.enabled
                    ? "Automatic qualification: load → seal → retreat → lift → task → retreat → lower. Supported release is confirmed."
                    : "Single-press sequence. The selected controller gates lift/lower continuously, and suction releases only at the verified low support."}</small>

                  {currentPreflight.key === "calibration" && (
                    <button className="stepPrimary" onClick={() => post("/api/calibration/mark")}>Calibration complete</button>
                  )}

                  {currentPreflight.key === "recordings" && (
                    <>
                      <div className="recordingFiles" aria-label="Required recording filenames">
                        <label><span>MVN</span><input value={mvnRecordingReference || defaultMvnReference} maxLength={500} onChange={event => setMvnRecordingReference(event.target.value)} /></label>
                        <label><span>Motive</span><input value={motiveRecordingReference || defaultMotiveReference} maxLength={500} onChange={event => setMotiveRecordingReference(event.target.value)} /></label>
                        <label><span>Video</span><input value={videoRecordingReference || defaultVideoReference} maxLength={500} onChange={event => setVideoRecordingReference(event.target.value)} /></label>
                      </div>
                      <button className="stepPrimary" disabled={startBusy} onClick={() => void startRecording(nextStudySlot, effectiveRecordingReferences, true)}>{startBusy ? "Starting trial…" : "All three recordings are running — start trial"}</button>
                    </>
                  )}

                  {currentPreflight.key === "ready" && (
                    <button className="stepPrimary" disabled={startBusy} onClick={() => void startRecording(nextStudySlot, effectiveRecordingReferences)}>Start Block {nextStudySlot.block} · Trial {nextStudySlot.withinBlockTrial} — suction turns on</button>
                  )}

                  <details className="preflightDetails">
                    <summary>{readyPreflightCount}/5 systems ready <span>View all checks</span></summary>
                    <div className="preflightList" aria-label="Run preflight">
                      {preflightChecks.map(check => (
                        <div key={check.key} className={check.ready ? "ready" : "blocked"}>
                          <i /><span>{check.label}</span><b>{check.value}</b>
                        </div>
                      ))}
                    </div>
                  </details>
                </div>
              ) : (
                <div className="oneStepAction completeAction"><span>SESSION COMPLETE</span><h2>All required trials and forms are complete</h2><p>Debrief the participant and preserve the session manifest.</p></div>
              )}
              {message && (!dueStudyForm || status.recording) && <p className="feedback compactFeedback">{message}</p>}
            </article>}

            <details className="panel studyDetails">
              <summary><span>Session map</span><b>{acceptedStudyRuns}/9 captures passed</b></summary>
              <p>Capture checks cover labels and tracking. Final analysis eligibility requires a separate trial audit.</p>
              <details>
                <summary>Operator: controller order for {participant || "no participant selected"}</summary>
                <p>Block names always progress A → B → C. The assigned controllers change with participant code. Keep this operator information out of the participant briefing.</p>
                {participant && <ol>{schedule.filter(slot => slot.withinBlockTrial === 1).map(slot => <li key={slot.block}>Block {slot.block}: <strong>{slot.controller}</strong></li>)}</ol>}
              </details>
              <div className="trialMatrix">
                {schedule.map(slot => {
                  const matches = participantRuns.filter(run => run.block_label === slot.block && run.within_block_trial === slot.withinBlockTrial);
                  const accepted = matches.some(run => run.quality.grade === "good");
                  const attempted = matches.length > 0;
                  return <div key={`${slot.block}-${slot.withinBlockTrial}`} className={accepted ? "trialSlot accepted" : attempted ? "trialSlot repeat" : "trialSlot"}>
                    <span>{slot.block}{slot.withinBlockTrial}</span><strong>{slot.event}</strong><small>{accepted ? "✓ accepted" : attempted ? "repeat" : "waiting"}</small>
                  </div>;
                })}
              </div>
            </details>

            <details className="panel studyDetails">
              <summary><span>Rig status &amp; recovery</span><b className={robotPose.ok ? "readyText" : "warnText"}>{robotPose.label}</b></summary>
              <p className={robotPose.ok ? "studyRigOk" : "poseWarn"}>{robotPose.detail}</p>
              <RigButton tag="stop_motion_study" label="STOP ARM MOTION — suction stays on" kind="stop" busy={rigBusy} result={rigResult} onPress={() => rigPost("/api/robot", { action: "stop" }, "stop_motion_study")} />
              <div className="studyRecovery"><RigButton tag="grip_study" label="Suction on" busy={rigBusy} result={rigResult} onPress={() => rigPost("/api/gripper", { action: "grip", channel: "BOTH", vacuum }, "grip_study")} /><RigButton tag="down_study" label="Return to low pose" busy={rigBusy} result={rigResult} onPress={() => rigPost("/api/robot", { action: "go_down" }, "down_study")} /><RigButton tag="release_study" label="Release supported panel" busy={rigBusy} result={rigResult} onPress={() => rigPost("/api/gripper", { action: "release", channel: "BOTH" }, "release_study")} /></div>
            </details>
          </section>
        </>
      ) : (<>

      <section className="hero">
        <div><p className="eyebrow">TRAINING ONLY — NEVER PARTICIPANT RESULTS</p><h1>Model development</h1><p className="sub">Label pilot motion, inspect signals, and retrain. Study and qualification runs stay separate.</p></div>
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
        <section className={`runDirector label-${status.event_label === "hazard" ? "hazard" : guided.label}`} aria-live="polite">
          <div className="runDirectorHead">
            <span>LIVE RUN DIRECTOR · {status.block_label} / {status.controller_condition} / TRIAL {status.within_block_trial} · STEP {manualStepNumber}/8</span>
            <strong>PHASE: {status.label.toUpperCase()} · EVENT: {status.event_label.toUpperCase()}</strong>
          </div>
          <h2>{guidedTitle}</h2>
          <p>{guidedCue}</p>
          {guidedIndex === 0 && <button className="syncMarker" onClick={() => void post("/api/sync")}>
            {status.sync_marker_count > 0 ? `✓ Sync marker ${status.sync_marker_count} recorded` : "Record visible shared sync marker"}
          </button>}
          {guidedIndex >= 3 && guidedIndex <= 8 && <div className="simPanelNote">SIMULATION RULE: no top fixture means suction stays ON while the panel is at the top. Never release an unsupported panel overhead.</div>}
          <button onClick={confirmGuidedAction} disabled={protocolWorking}>{protocolWorking ? protocolBusyLabel : guidedNext}</button>
          <small>One press records each phase boundary. Lift and lower requests remain active while the assigned controller gates motion.</small>
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
            <button className="primary" disabled={participantSaving || !participantName.trim()} onClick={() => void saveParticipant()}>{participantSaving ? "Saving…" : participantEditor === "new" ? "Create participant" : "Save name"}</button>
            <button onClick={() => { setParticipantEditor(null); setParticipantName(""); }}>Cancel</button>
          </div>}
          <div className="actions">
            {!status.recording ? <button className="primary" disabled={!xsensComplete || !status.optitrack_connected || !participant || !mvnRecordingConfirmed || !mvnRecordingReference.trim() || calibration == null || calibration > 300} onClick={() => void startRecording()}>Start {nextTrial} development run</button> : <button className="stop" onClick={() => void abortRecording()}>Abort / stop & save</button>}
          </div>
          {!status.recording && <label className="nativeReference"><span>Visible native MVN file name/path for this run</span><input value={mvnRecordingReference} maxLength={500} placeholder="e.g. C:\\MVN\\P06-T01.mvn" onChange={event => setMvnRecordingReference(event.target.value)} /></label>}
          {!status.recording && <label className="preflightCheck"><input type="checkbox" checked={mvnRecordingConfirmed} onChange={event => setMvnRecordingConfirmed(event.target.checked)} /><span>Native recording is active in MVN Analyze and its file path is visible.</span></label>}
          {!status.recording && <p className="startHint">The next trial number comes from the files already saved for this participant. Every attempt is preserved and counted automatically.</p>}
          <p className="feedback">{message}</p>
          <dl className="sessionFacts"><div><dt>Samples</dt><dd>{status.samples_written.toLocaleString()}</dd></div><div><dt>Packet age</dt><dd>{n(status.age_s, 3)} s</dd></div><div><dt>Calibration</dt><dd className={calibrationClass}>{calibration == null ? "Not marked" : `${Math.floor(calibration / 60)}:${String(Math.floor(calibration % 60)).padStart(2, "0")}`}</dd></div><div><dt>Model</dt><dd title={status.model_sha256}>{status.model_sha256 === "synthetic-baseline" ? "SYNTHETIC" : status.model_sha256.slice(0, 12)}</dd></div></dl>
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
              <div className="labelCoverage">{STATES.map(label => <span key={label}>{label} {run.labels[label] == null ? "—" : `${n(run.labels[label], 1)}s`}</span>)}<span>{run.planned_event || "legacy event"}: {(run.events?.hazard ?? 0) + (run.events?.distractor ?? 0)} frames</span></div>
              <p>{run.quality.reasons.join(" · ")}</p>
            </div>)}
          </div>
        </article>

        <article className="panel participantPhone">
          <div className="panelHead">
            <div><p className="kicker">03 · PARTICIPANT PHONE</p><h2>One QR, only when due</h2></div>
            <span className={currentFormReady ? "phoneReady" : "warnText"}>{formStatusText}</span>
          </div>
          <p className="phoneRule">Questionnaires happen five times: intake once, after each three-trial block, and at the end. Never interrupt an individual trial for a form.</p>
          <div className="phoneStages" role="group" aria-label="Participant questionnaire stage">
            {(["intake", "block", "end"] as ParticipantFormStage[]).map(stage => (
              <button key={stage} className={phoneStage === stage ? "selected" : ""}
                disabled={status.recording} onClick={() => setPhoneStage(stage)}>
                {stage === "block" ? `Block ${blockLabel}` : PARTICIPANT_FORMS[stage].label}
                <small>{verifiedForms[stage] ? "✓ tested" : "not tested"}</small>
              </button>
            ))}
          </div>
          <div className={`phoneHandoff ${status.recording ? "locked" : ""}`}>
            <div className="phoneCopy">
              <span>{status.recording ? "NOT DURING A RUN" : `${participant} · ${PARTICIPANT_FORMS[phoneStage].label.toUpperCase()}`}</span>
              <strong>{status.recording ? "Participant continues the physical task" : phoneTitle}</strong>
              <p>{status.recording ? "The questionnaire stays hidden until the run is safely saved." : phoneInstruction}</p>
              {!status.recording && phoneStage === "block" && <em>Controller identity is never shown to the participant.</em>}
            </div>
            {!status.recording && currentFormReady && (
              <button className="qrButton" onClick={() => setPhoneFullscreen(true)} aria-label={`Show ${PARTICIPANT_FORMS[phoneStage].label} QR full screen`}>
                <QRCodeSVG value={phoneUrl} size={154} marginSize={2} level="M" />
                <span>Tap to enlarge</span>
              </button>
            )}
            {!status.recording && !currentFormReady && (
              <div className="qrLocked"><strong>QR LOCKED</strong><span>Test responder access first</span></div>
            )}
          </div>
          {!status.recording && <div className="formPreflight">
            <a href={phoneUrl} target="_blank" rel="noreferrer">Open {PARTICIPANT_FORMS[phoneStage].label} test link ↗</a>
            <label><input type="checkbox" disabled={formRouteBlocked} checked={verifiedForms[phoneStage]} onChange={event => setVerifiedForms(old => ({ ...old, [phoneStage]: event.target.checked }))} />
              <span>{formRouteBlocked ? "Set responder access to Anyone with the link." : "I opened this on a participant phone without a Monash login and a response can be submitted."}</span>
            </label>
          </div>}
          <p className="phoneDataNote">The phone writes directly to the existing Google Form response tabs. The Sheet remains the background research record, not another screen the participant has to navigate.</p>
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
          <div className="panelHead"><div><p className="kicker">03 · GROUND TRUTH</p><h2>Phase + independent event</h2></div><span className="currentLabel">{status.label} · {status.event_label}</span></div>
          <p className="help">The experimenter advances the protocol at each real phase onset. The active label then persists on every frame until the next cue; the participant never touches this console.</p>
          <div className="guidedRun">
            <span>GUIDED RUN · STEP {manualStepNumber}/8 · {status.label.toUpperCase()}</span>
            <strong>{guidedTitle}</strong>
            <p>{guidedCue}</p>
            <small>Hold each labelled state for at least 2 seconds. Press Enter or use the button.</small>
            <button className="protocolNext" disabled={!status.recording || status.guided_step == null || protocolWorking} onClick={confirmGuidedAction}>
              {protocolWorking ? protocolBusyLabel : guidedNext}
            </button>
          </div>
          <p className="manualLabelTitle">Manual label override — recovery/debugging only</p>
          <div className="labelButtons">{STATES.map(s => <button key={s} className={status.label === s ? "selected" : ""} disabled={!status.recording} onClick={() => post("/api/label", { label: s })}>{s}</button>)}</div>
          <button className="unlabel" disabled={!status.recording || activePlannedEvent !== "rapid intrusion"} onClick={() => post("/api/label", { label: "hazard" })}>Mark rapid-intrusion event (phase stays unchanged)</button>
          <button className="unlabel" disabled={!status.recording} onClick={() => post("/api/label", { label: "unlabelled" })}>Mark transition / unlabelled</button>
          <p className="shortcutHelp"><kbd>Enter</kbd> next guided phase · <kbd>1</kbd> approach · <kbd>2</kbd> work · <kbd>3</kbd> retreat · <kbd>4</kbd> rapid intrusion (planned trials only) · <kbd>0</kbd> unlabelled</p>
        </article>

        <article className="panel probabilities">
          <div className="panelHead"><div><p className="kicker">04 · MODEL</p><h2>HMM belief</h2></div><span className="quiet">not ground truth</span></div>
          <div className="bars">{STATES.map(s => { const value = status.posterior[s] || 0; return <div className="barRow" key={s}><span>{s}</span><div><i style={{ width: `${value * 100}%` }} /></div><strong>{Math.round(value * 100)}%</strong></div>; })}</div>
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
      </>)}
      {phoneFullscreen && !status.recording && currentFormReady && (
        <div className="participantOverlay" role="dialog" aria-modal="true" aria-label="Participant questionnaire QR">
          <button className="overlayClose" onClick={() => setPhoneFullscreen(false)} aria-label="Close participant view">Close ×</button>
          <div className="participantCard">
            <span>PARTICIPANT {participant}</span>
            <h2>{phoneTitle}</h2>
            <p>{phoneInstruction}</p>
            <div className="participantQr"><QRCodeSVG value={phoneUrl} size={340} marginSize={3} level="M" /></div>
            <strong>Scan with your phone camera</strong>
            <small>Your participant ID is already filled in. Ask the experimenter if the form does not open.</small>
          </div>
        </div>
      )}
      <footer><span>Data remains on this lab PC</span><span>{status.recording_path || "No active recording"}</span></footer>
    </main>
  );
}
