"""Persistent report scheduling with atomic job claims and bounded catch-up."""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


class SchedulerError(ValueError):
    pass


def _validate_time(value):
    if not isinstance(value, str):
        raise SchedulerError("local_time must be a string HH:MM.")
    parts = value.split(":")
    if len(parts) != 2:
        raise SchedulerError("local_time must be HH:MM.")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        raise SchedulerError("local_time must be HH:MM with integers.")
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise SchedulerError("local_time hours/minutes out of range.")
    return hour, minute


def _next_daily_run(tz_name, local_time, now):
    tz = ZoneInfo(tz_name)
    now_local = datetime.fromtimestamp(now, tz)
    hour, minute = _validate_time(local_time)
    target_today = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now_local < target_today:
        return target_today.timestamp()
    return (target_today + timedelta(days=1)).timestamp()


def _next_monthly_run(tz_name, local_time, now):
    tz = ZoneInfo(tz_name)
    now_local = datetime.fromtimestamp(now, tz)
    hour, minute = _validate_time(local_time)
    target_this = now_local.replace(day=1, hour=hour, minute=minute, second=0, microsecond=0)
    if now_local < target_this:
        return target_this.timestamp()
    # Move to first of next month
    if now_local.month == 12:
        next_month = now_local.replace(year=now_local.year + 1, month=1, day=1, hour=hour, minute=minute, second=0, microsecond=0)
    else:
        next_month = now_local.replace(month=now_local.month + 1, day=1, hour=hour, minute=minute, second=0, microsecond=0)
    return next_month.timestamp()


def compute_next_run(report_type, tz_name, local_time, now):
    if report_type == "daily":
        return _next_daily_run(tz_name, local_time, now)
    if report_type == "monthly":
        return _next_monthly_run(tz_name, local_time, now)
    raise SchedulerError("Unsupported report type.")


class Scheduler:
    def __init__(self, connection_factory, clock=None):
        self.connection_factory = connection_factory
        self.clock = clock or (lambda: datetime.now(timezone.utc).timestamp())
        self._ensure_schema()

    @contextmanager
    def connection(self):
        conn = self.connection_factory()
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _ensure_schema(self):
        with self.connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS report_schedules (
                    id TEXT PRIMARY KEY,
                    portfolio_id TEXT NOT NULL,
                    report_type TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    local_time TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    next_run REAL NOT NULL,
                    last_run REAL,
                    last_outcome TEXT,
                    data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_schedules_next ON report_schedules(enabled, next_run);
                CREATE TABLE IF NOT EXISTS report_jobs (
                    id TEXT PRIMARY KEY,
                    schedule_id TEXT NOT NULL,
                    job_key TEXT UNIQUE NOT NULL,
                    report_type TEXT NOT NULL,
                    period_label TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    leased_until REAL,
                    next_retry REAL,
                    error TEXT,
                    created_at REAL NOT NULL,
                    completed_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_key ON report_jobs(job_key);
            """)

    def upsert(self, payload):
        portfolio_id = payload.get("portfolio_id")
        report_type = payload.get("report_type")
        tz_name = payload.get("timezone", "Africa/Kampala")
        local_time = payload.get("local_time", "08:00")
        destination = payload.get("destination", {})
        if destination not in ({}, {"type": "private"}):
            raise SchedulerError("Only private dashboard publication is configured.")
        enabled = 1 if payload.get("enabled", True) else 0
        if report_type not in {"daily", "monthly"}:
            raise SchedulerError("report_type must be daily or monthly.")
        try:
            ZoneInfo(tz_name)
        except Exception as exc:
            raise SchedulerError(f"Invalid timezone: {tz_name}") from exc
        _validate_time(local_time)
        now = self.clock()
        next_run = compute_next_run(report_type, tz_name, local_time, now)
        schedule_id = payload.get("id") or "sch-" + str(uuid.uuid4())[:12]
        data = json.dumps({"created_at": now})
        with self.connection() as conn:
            existing = conn.execute("SELECT id FROM report_schedules WHERE id=?", (schedule_id,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE report_schedules SET portfolio_id=?, report_type=?, timezone=?, local_time=?, "
                    "destination=?, enabled=?, next_run=?, data=? WHERE id=?",
                    (portfolio_id, report_type, tz_name, local_time, json.dumps(destination), enabled, next_run, data, schedule_id),
                )
            else:
                conn.execute(
                    "INSERT INTO report_schedules VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (schedule_id, portfolio_id, report_type, tz_name, local_time, json.dumps(destination),
                     enabled, next_run, None, None, data),
                )
        return {"id": schedule_id, "portfolio_id": portfolio_id, "report_type": report_type,
                "timezone": tz_name, "local_time": local_time, "enabled": bool(enabled),
                "next_run": next_run, "destination": destination}

    def list(self, portfolio_id=None):
        with self.connection() as conn:
            sql = "SELECT * FROM report_schedules"
            params = ()
            if portfolio_id:
                sql += " WHERE portfolio_id=?"
                params = (portfolio_id,)
            sql += " ORDER BY next_run"
            rows = conn.execute(sql, params).fetchall()
            return [{
                "id": r["id"], "portfolio_id": r["portfolio_id"], "report_type": r["report_type"],
                "timezone": r["timezone"], "local_time": r["local_time"], "enabled": bool(r["enabled"]),
                "next_run": r["next_run"], "last_run": r["last_run"], "last_outcome": r["last_outcome"],
                "destination": json.loads(r["destination"]),
            } for r in rows]

    def pause(self, schedule_id):
        with self.connection() as conn:
            conn.execute("UPDATE report_schedules SET enabled=0 WHERE id=?", (schedule_id,))

    def enable(self, schedule_id):
        with self.connection() as conn:
            row = conn.execute("SELECT report_type, timezone, local_time FROM report_schedules WHERE id=?", (schedule_id,)).fetchone()
            if not row:
                raise SchedulerError("Schedule not found.")
            next_run = compute_next_run(row["report_type"], row["timezone"], row["local_time"], self.clock())
            conn.execute("UPDATE report_schedules SET enabled=1, next_run=? WHERE id=?", (next_run, schedule_id))

    def tick(self, runner):
        """Run due schedules. `runner(schedule_row, period_label)` returns outcome dict."""
        now = self.clock()
        jobs = []
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            due = conn.execute(
                "SELECT * FROM report_schedules WHERE enabled=1 AND next_run <= ? ORDER BY next_run",
                (now,),
            ).fetchall()
            for row in due:
                # Determine period label for completed period
                from backend.reports import period_bounds
                try:
                    period = period_bounds(row["report_type"], row["timezone"], row["next_run"])
                except Exception:
                    continue
                job_key = f"{row['id']}:{row['report_type']}:{period.label}"
                existing = conn.execute("SELECT * FROM report_jobs WHERE job_key=?", (job_key,)).fetchone()
                if existing and (existing["state"] == "complete" or existing["attempts"] >= 3):
                    # Already processed; advance next_run anyway to avoid stuck schedules
                    next_run = compute_next_run(row["report_type"], row["timezone"], row["local_time"], now + 60)
                    conn.execute("UPDATE report_schedules SET next_run=? WHERE id=?", (next_run, row["id"]))
                    continue
                if existing and ((existing["state"] == "running" and existing["leased_until"] > now)
                                 or (existing["state"] == "failed" and existing["next_retry"] > now)):
                    continue
                job_id = "job-" + str(uuid.uuid4())[:12]
                leased = now + 300
                try:
                    if existing:
                        job_id = existing["id"]
                        conn.execute("DELETE FROM report_jobs WHERE id=?", (job_id,))
                    conn.execute(
                        "INSERT INTO report_jobs (id, schedule_id, job_key, report_type, period_label, state, attempts, leased_until, next_retry, created_at) "
                        "VALUES (?, ?, ?, ?, ?, 'running', 1, ?, ?, ?)",
                        (job_id, row["id"], job_key, row["report_type"], period.label, leased, leased, now),
                    )
                    if existing:
                        conn.execute("UPDATE report_jobs SET attempts=? WHERE id=?", (existing["attempts"] + 1, job_id))
                except sqlite3.IntegrityError:
                    continue
                next_run = compute_next_run(row["report_type"], row["timezone"], row["local_time"], now + 60)
                jobs.append({"job_id": job_id, "schedule": dict(row), "period_label": period.label, "period": period})
        outcomes = []
        for job in jobs:
            try:
                outcome = runner(job["schedule"], job["period"])
                status = "complete"
                error = None
            except Exception as exc:
                outcome = {"error": str(exc)}
                status = "failed"
                error = str(exc)
            with self.connection() as conn:
                if status == "complete":
                    schedule = job["schedule"]
                    conn.execute("UPDATE report_schedules SET next_run=? WHERE id=?",
                                 (compute_next_run(schedule["report_type"], schedule["timezone"], schedule["local_time"], now + 60), schedule["id"]))
                conn.execute(
                    "UPDATE report_jobs SET state=?, completed_at=?, error=? WHERE id=?",
                    (status, self.clock(), error, job["job_id"]),
                )
                conn.execute(
                    "UPDATE report_schedules SET last_run=?, last_outcome=? WHERE id=?",
                    (self.clock(), json.dumps(outcome), job["schedule"]["id"]),
                )
            outcomes.append(outcome)
        return outcomes
