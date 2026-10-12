from celery import Celery
from app.config import settings

celery_app = Celery(
    "airyield",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.workers.deal_tasks",
        "app.workers.bsp_tasks",
        "app.workers.bsp_commission_tasks",
        "app.workers.commission_tasks",
        "app.workers.lcc_tasks",
        "app.workers.report_tasks",
        "app.workers.mail_tasks",
    ],
)

celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.timezone = "UTC"

# BSP statements can take several minutes to parse (1000-2000 pages). Raise the
# Redis visibility timeout above the worst-case parse time so the broker does not
# redeliver an in-flight job and spawn a second concurrent copy. Give tasks a
# generous soft/hard time limit as a backstop.
celery_app.conf.broker_transport_options = {"visibility_timeout": 3 * 60 * 60}  # 3h
celery_app.conf.task_soft_time_limit = 2 * 60 * 60   # 2h — raises SoftTimeLimitExceeded
celery_app.conf.task_time_limit = 2 * 60 * 60 + 300  # hard kill 5 min later
# Recycle worker children periodically so PyMuPDF C-level memory can't accumulate.
celery_app.conf.worker_max_tasks_per_child = 20

# ── Scheduled jobs (celery beat) ────────────────────────────────────────────
# The first periodic job in the stack: run ONE `celery beat` process beside the workers.
# Email intake checks connected mailboxes for mail from onboarded senders; a worker must
# consume the `mail` queue (architecture/02 §2.4).
celery_app.conf.beat_schedule = {
    "mail-sync-all": {
        "task": "mail.sync_all",
        "schedule": max(1, settings.MAIL_POLL_MINUTES) * 60.0,
        "options": {"queue": "mail", "expires": max(1, settings.MAIL_POLL_MINUTES) * 60.0},
    },
}
