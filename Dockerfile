FROM python:3.12-slim

# Keep the production image small. The application only needs Python packages
# from requirements.txt; no compiler toolchain is required at runtime.
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/collection_auditor.py .
COPY app/sqlite_lock.py .
COPY app/sqlite_backend_gate.py .
COPY app/main.py .
COPY app/web.py .
COPY app/dashboard_tracking_snapshot.py .
COPY app/integration_status.py .
COPY app/integration_api.py .
COPY app/sqlite_json.py .
COPY app/sqlite_state.py .
COPY app/lifecycle_decisions.py .
COPY app/templates ./templates
COPY app/static ./static
COPY unraid/assets/Media_Collection_Auditor_Badge.png ./static/auditor-badge.png
COPY app/config_store.py .
COPY app/connection_tests.py .
COPY app/run_control.py .
COPY app/audit_history.py .
COPY app/manual_rescue.py .
COPY app/auth.py .

# Catch missing runtime modules during image build, not on Unraid.
RUN WEB_SESSION_SECRET=build-only-import-smoke-test python -c "import sqlite_lock; import collection_auditor; import web; from dashboard_tracking_snapshot import read_json_dashboard_snapshot"

EXPOSE 8080

ENTRYPOINT ["python", "main.py"]
