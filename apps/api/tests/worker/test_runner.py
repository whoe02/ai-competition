"""The worker uses one durable, KL-local schedule rather than an in-process timer."""

from kira.worker.runner import JOB_ID, build_scheduler


def test_the_nightly_job_is_registered_for_kuala_lumpur_time():
    scheduler = build_scheduler()
    job = scheduler.get_job(JOB_ID)

    assert job is not None
    assert str(scheduler.timezone) == "Asia/Kuala_Lumpur"
    assert "hour='5'" in str(job.trigger)
