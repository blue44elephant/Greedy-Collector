from greedy_collector import monitoring


def test_missing_celery_reports_apscheduler_fallback(monkeypatch):
    monkeypatch.setattr(monitoring.settings, "monitoring_backend", "celery")
    monkeypatch.setattr(monitoring.settings, "redis_url", "redis://example:6379/0")
    monkeypatch.setattr(monitoring.importlib.util, "find_spec", lambda name: None)
    status = monitoring.monitoring_status()
    assert status["requested"] == "celery"
    assert status["active"] == "apscheduler"
    assert status["fallback"] == "apscheduler"
