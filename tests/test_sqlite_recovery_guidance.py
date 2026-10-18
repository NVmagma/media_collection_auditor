"""Recovery guidance never grants clearance or reflects untrusted text."""

from app.sqlite_recovery_guidance import explain_recovery_status


def test_known_blocker_explains_manual_review():
    result = explain_recovery_status({
        "status": "blocked", "blocker": "jellyfin_scope_incomplete",
        "operation_phase": "intent_recorded",
    })
    assert "Jellyfin" in result["summary"]
    assert "all configured Jellyfin users" in result["next_step"]
    assert "not confirmed" in result["phase_explanation"]


def test_applied_phase_does_not_imply_authorization():
    result = explain_recovery_status({
        "status": "blocked", "blocker": "independent_verification_required",
        "operation_phase": "applied_pending_reconciliation",
    })
    assert "independent reconciliation" in result["phase_explanation"]
    assert "Do not replay or clear" in result["next_step"]


def test_unknown_untrusted_values_are_never_reflected():
    secret = "<script>secret-token</script>"
    result = explain_recovery_status({
        "status": "blocked", "blocker": secret, "operation_phase": secret,
    })
    assert secret not in str(result)
    assert "clear" in result["next_step"]


def test_no_pending_operation_does_not_suggest_recovery():
    result = explain_recovery_status({"status": "no_pending_operation"})
    assert "No pending" in result["summary"]
    assert "No recovery action" in result["next_step"]


def test_invalid_status_fails_closed():
    result = explain_recovery_status({"status": "unexpected"})
    assert "unchanged" in result["next_step"]


def test_every_service_blocker_has_specific_operator_guidance():
    from app.sqlite_recovery_report import BLOCKERS
    from app.sqlite_recovery_guidance import GUIDANCE
    assert set(BLOCKERS.values()) <= set(GUIDANCE)
    for blocker in set(BLOCKERS.values()):
        result = explain_recovery_status({
            "status": "blocked", "blocker": blocker,
            "operation_phase": "intent_recorded",
        })
        assert result["summary"] == GUIDANCE[blocker][0]
        assert result["next_step"] == GUIDANCE[blocker][1]
        assert "phase_explanation" in result
