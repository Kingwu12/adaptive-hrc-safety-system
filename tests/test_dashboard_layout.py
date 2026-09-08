"""Small source contracts for the lab dashboard's operator-first layout."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_wide_dashboard_keeps_navigation_compact_and_controls_above_fold():
    css = (ROOT / "dashboard/app/globals.css").read_text(encoding="utf-8")
    page = (ROOT / "dashboard/app/page.tsx").read_text(encoding="utf-8")

    assert ".modeChooser{display:flex;gap:26px" in css
    assert "border-bottom:2px solid var(--mint)" in css
    assert ".hero { min-height:0; padding:20px 0 14px" in css
    assert ".topbar { height:64px" in css
    chooser_start = page.index('<section className="modeChooser"')
    chooser_end = page.index("</section>", chooser_start)
    chooser = page[chooser_start:chooser_end]
    assert chooser.index("Participant study") < chooser.index("Qualification")
    assert chooser.index("Qualification") < chooser.index("Model development")


def test_participant_console_exposes_one_current_action_only():
    page = (ROOT / "dashboard/app/page.tsx").read_text(encoding="utf-8")

    assert '<section className="studyFlow"' not in page
    assert page.count('<details className="panel studyDetails">') == 2
    assert "PUBLIC LINK ONLINE" in page
    assert 'activeFormAccess?.accessible_without_login === true' in page
    assert 'className={currentFormReady ? "inlineQr" : "inlineQr qrUnavailable"}' in page
    assert 'size={244}' in page
    assert 'Continue after the confirmation screen appears' in page
    assert '>Open form</a>' not in page
    assert '>Show QR</button>' not in page
    assert page.count('className="contextParticipantControl"') == 1
    assert 'className="participantStrip"' not in page


def test_form_handoff_can_advance_from_the_response_sheet_bridge():
    page = (ROOT / "dashboard/app/page.tsx").read_text(encoding="utf-8")
    server = (ROOT / "scripts/dashboard_server.py").read_text(encoding="utf-8")

    assert "/api/forms/completion?" in page
    assert "payload.tracking_available && payload.submitted" in page
    assert 'HRC_FORM_COMPLETION_URL' in server
    assert 'HRC_FORM_COMPLETION_TOKEN' in server
    assert 'path == "/api/forms/completion"' in server


def test_participant_flow_waits_at_suit_and_calibration_until_rig_is_ready():
    page = (ROOT / "dashboard/app/page.tsx").read_text(encoding="utf-8")

    assert "const initialRigReady = reachable" in page
    assert "&& xsensComplete" in page
    assert 'label: "2 · Suit & calibrate"' in page
    assert "acceptedStudyRuns === 0 && !dueStudyForm && !initialRigReady" in page
    assert "(acceptedStudyRuns > 0 || initialRigReady)" in page


def test_trial_preflight_reveals_only_the_first_unmet_action():
    css = (ROOT / "dashboard/app/globals.css").read_text(encoding="utf-8")
    page = (ROOT / "dashboard/app/page.tsx").read_text(encoding="utf-8")

    assert "const currentPreflight = !reachable" in page
    assert '} : !xsensComplete ? {' in page
    assert '} : !status.optitrack_connected ? {' in page
    assert '} : !robotPose.ok ? {' in page
    assert '} : !calibrationReady ? {' in page
    assert '} : !mvnRecordingConfirmed ? {' in page
    assert '<details className="preflightDetails">' in page
    assert 'All three recordings are running' in page
    assert ".studyShell .preflightList{display:grid;grid-template-columns:1fr" in css


def test_participant_workspace_uses_high_contrast_procedural_surface():
    css = (ROOT / "dashboard/app/globals.css").read_text(encoding="utf-8")
    page = (ROOT / "dashboard/app/page.tsx").read_text(encoding="utf-8")

    assert 'className={workspaceMode === "model_development" ? "developmentShell" : "studyShell"}' in page
    assert "background:#f4f6f4" in css
    assert ".studyShell .oneStepAction{" in css
    assert "min-height:52px" in css


def test_workspace_chrome_is_flat_and_qualification_language_is_unambiguous():
    css = (ROOT / "dashboard/app/globals.css").read_text(encoding="utf-8")
    page = (ROOT / "dashboard/app/page.tsx").read_text(encoding="utf-8")

    assert "radial-gradient" not in css
    assert ".topbar{position:sticky;top:0;z-index:40;background:#09100d;backdrop-filter:none}" in css
    assert ".studyShell .oneStepAction{" in css and "box-shadow:none" in css
    assert ".studyShell .emptyAction{display:grid;grid-template-columns:minmax(0,1fr) 250px" in css
    assert 'isQualification ? "Create Q code" : "Create participant"' in page
    assert 'isQualification ? "Create a rehearsal code"' in page


def test_dashboard_does_not_describe_an_unreachable_robot_as_live_tcp():
    page = (ROOT / "dashboard/app/page.tsx").read_text(encoding="utf-8")

    assert 'rig.robot?.reachable === false' in page
    assert 'label: "ROBOT OFFLINE"' in page


def test_automatic_qualification_does_not_offer_manual_movement_advances():
    page = (ROOT / "dashboard/app/page.tsx").read_text(encoding="utf-8")
    assert 'automatic: workspaceMode === "qualification" && status.automation?.enabled === true' in page
    assert 'disabled={protocolWorking || automaticWaiting}' in page
    assert 'status.automation.fault || ![7, 9].includes(step)' in page
    assert 'START LOADING SUCTION' not in page
    assert ' — suction turns on' in page
    assert 'TASK COMPLETE — BEGIN RETREAT' in page
    assert 'Automatic participant release remains unqualified.' in page
