"""Phase 7: hardening. The hourly cap, the token window and the store leak.

Each check corresponds to a setting that existed but was never enforced, or a
collection that was never cleaned. Without these tests the phase is just
declarations in settings.py.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.files.converters import jobs, settings


def fresh_store():
    return jobs.JobStore()


def case_hourly_cap():
    """The cap must start refusing once the allowance is spent."""
    store = fresh_store()
    user = "u-cap"
    original = settings.CONVERTER_USER_HOURLY_CAP
    settings.CONVERTER_USER_HOURLY_CAP = 3
    try:
        assert not store.over_hourly_cap(user), "fresh user was already capped"
        for _ in range(3):
            store.record_submission(user)
        assert store.hourly_count(user) == 3, store.hourly_count(user)
        assert store.over_hourly_cap(user), "cap not enforced after 3 submissions"
        print("cap: 3 submissions -> over_hourly_cap True")
    finally:
        settings.CONVERTER_USER_HOURLY_CAP = original


def case_cap_rolls_over():
    """Submissions older than an hour must stop counting."""
    store = fresh_store()
    user = "u-roll"
    original = settings.CONVERTER_USER_HOURLY_CAP
    settings.CONVERTER_USER_HOURLY_CAP = 2
    try:
        old = time.time() - 3700
        store._user_submissions[user] = [old, old]
        assert store.hourly_count(user) == 0, "stale submissions still counted"
        assert not store.over_hourly_cap(user)
        print("cap: submissions older than 1h no longer count")
    finally:
        settings.CONVERTER_USER_HOURLY_CAP = original


def case_cap_disabled():
    """A cap of 0 means unlimited, not 'block everyone'."""
    store = fresh_store()
    user = "u-off"
    original = settings.CONVERTER_USER_HOURLY_CAP
    settings.CONVERTER_USER_HOURLY_CAP = 0
    try:
        for _ in range(50):
            store.record_submission(user)
        assert not store.over_hourly_cap(user), "cap=0 blocked the user"
        print("cap: 0 means unlimited")
    finally:
        settings.CONVERTER_USER_HOURLY_CAP = original


def case_token_window():
    """A result token must stop working once its own TTL passes."""
    store = fresh_store()
    job = store.create("u-token", "png", "jpg")

    job.state = jobs.DONE
    job.result_token_expires_at = time.time() + 60
    assert job.result_token_valid, "fresh token rejected"

    job.result_token_expires_at = time.time() - 1
    assert not job.result_token_valid, "expired token still accepted"

    job.result_token = ""
    assert not job.result_token_valid, "empty token accepted"
    print("token: valid inside TTL, rejected after, empty always rejected")


def case_token_shorter_than_job():
    """The token window must be shorter than the job record's lifetime.

    That is the whole point of the separate TTL: a leaked status payload must
    not buy a download window as long as the job TTL.
    """
    token_ttl = settings.CONVERTER_RESULT_TOKEN_TTL_SECONDS
    job_ttl = settings.CONVERTER_JOB_TTL_SECONDS
    assert token_ttl < job_ttl, (
        "token TTL (%s) is not shorter than job TTL (%s)" % (token_ttl, job_ttl)
    )
    print("token: TTL %ds < job TTL %ds" % (token_ttl, job_ttl))


def case_user_jobs_no_leak():
    """purge() must drop the id from _user_jobs, not just _jobs.

    Previously _user_jobs kept dead ids forever, so a long-lived process grew
    without bound and every running_count() call scanned dead entries.
    """
    store = fresh_store()
    user = "u-leak"
    ids = [store.create(user, "png", "jpg").job_id for _ in range(5)]

    for job_id in ids:
        store.purge(job_id)

    assert not store._jobs, "job records not purged"
    assert user not in store._user_jobs, "user_jobs still holds dead ids"
    print("leak: purge cleared both _jobs and _user_jobs")


def case_sweep_uses_purge():
    """sweep() must clean _user_jobs too, via purge."""
    store = fresh_store()
    user = "u-sweep"
    job = store.create(user, "png", "jpg")
    job.state = jobs.DONE
    job.expires_at = time.time() - 1

    removed = store.sweep()
    assert removed == 1, removed
    assert user not in store._user_jobs, "sweep left dead ids behind"
    print("leak: sweep cleared both collections")


def case_growing_user_jobs_capped():
    """MAX_PER_USER still bounds total records after the purge fix."""
    store = fresh_store()
    user = "u-many"
    for _ in range(store.MAX_PER_USER + 20):
        job = store.create(user, "png", "jpg")
        job.state = jobs.DONE
    total = len(store._user_jobs.get(user, []))
    assert total <= store.MAX_PER_USER, total
    print("cap: per-user record list bounded at %d" % total)


def main():
    case_hourly_cap()
    case_cap_rolls_over()
    case_cap_disabled()
    case_token_window()
    case_token_shorter_than_job()
    case_user_jobs_no_leak()
    case_sweep_uses_purge()
    case_growing_user_jobs_capped()
    print("PHASE 7 HARDENING OK")


main()
