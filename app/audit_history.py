"""Append audit summaries alongside the saved action logs."""
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

HISTORY_FILE = Path(os.environ.get("AUDIT_HISTORY_FILE", "/app/logs/audit_history.jsonl"))

def now():
    return datetime.now(timezone.utc).isoformat()

def read_history(limit=100):
    if not HISTORY_FILE.exists():
        return []
    records = []
    try:
        with HISTORY_FILE.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                    if isinstance(record, dict):
                        records.append(record)
                except (ValueError, TypeError):
                    continue
    except OSError:
        return []
    return list(reversed(records[-limit:]))

def append_history(record):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())

def summarize_actions(path, offset):
    """Summarize new action records. Counts reflect logged titles, not all scanned titles."""
    counts = Counter()
    titles = {"Movies": set(), "TV": set()}
    actions = []
    try:
        with open(path, encoding="utf-8") as handle:
            handle.seek(offset)
            for line in handle:
                try:
                    event = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(event, dict):
                    continue
                action = str(event.get("action", "unknown"))
                status = str(event.get("status", "unknown"))
                counts[action] += 1
                counts["status:" + status] += 1
                lib, folder = event.get("library"), event.get("folder")
                if lib in titles and isinstance(folder, str) and folder and folder != "-":
                    titles[lib].add(folder)
                # Leave free-text details out of history because they may contain private data.
                actions.append({"time": event.get("time", ""), "library": lib,
                                "folder": folder, "action": action, "status": status})
    except (OSError, UnicodeError):
        pass
    return {"movies_processed": len(titles["Movies"]), "tv_processed": len(titles["TV"]),
            "action_counts": {k: v for k, v in counts.items() if not k.startswith("status:")},
            "status_counts": {k[7:]: v for k, v in counts.items() if k.startswith("status:")},
            "actions": actions}

def new_record(trigger, dry_run):
    return {"id": uuid4().hex, "trigger": trigger, "dry_run": bool(dry_run),
            "started_at": now()}

def finish_record(record, result, summary, error=None):
    finished = datetime.now(timezone.utc)
    started = datetime.fromisoformat(record["started_at"])
    record.update(finished_at=finished.isoformat(),
                  duration_seconds=round((finished - started).total_seconds(), 2),
                  result=result, **summary)
    if error:
        record["error"] = error
    append_history(record)
    return record
