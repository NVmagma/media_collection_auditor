# Initial SQLite release supports scheduled preview only. No environment bypass.
ARG BASE_IMAGE=python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
FROM ${BASE_IMAGE}
WORKDIR /app
# Existing modules use both legacy flat imports and the app package namespace.
ENV PYTHONPATH=/app/app:/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt /app/requirements.txt
COPY docker/sqlite-candidate-constraints.txt /app/candidate-constraints.txt
RUN pip install --no-cache-dir -r /app/requirements.txt -c /app/candidate-constraints.txt
COPY app/ /app/app/
COPY unraid/assets/Media_Collection_Auditor_Badge.png /app/app/static/auditor-badge.png
ARG SOURCE_REVISION
RUN python -c 'import os,re; from pathlib import Path; revision=os.environ["SOURCE_REVISION"]; assert re.fullmatch("[0-9a-f]{40}",revision); Path("/app/app/sqlite_release_profile.py").write_text("PROFILE = " + repr("scheduled-preview-v1") + "\nSOURCE_REVISION = " + repr(revision) + "\n")'
RUN WEB_SESSION_SECRET=build-only-candidate-import-check python -c "import app.main, app.sqlite_scheduled_service, app.sqlite_scheduled_production, app.sqlite_tracking_view, app.sqlite_scheduled_observations; from app.sqlite_release_profile import PROFILE; assert PROFILE == 'scheduled-preview-v1'; from app.sqlite_backend_gate import require_sqlite_production_activation; from unittest import TestCase; TestCase().assertRaises(RuntimeError, require_sqlite_production_activation)"
LABEL org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.title="Media Collection Auditor SQLite scheduled preview" \
      io.media-collection-auditor.sqlite-activation="preview-only" \
      net.unraid.docker.webui="http://[IP]:[PORT:8080]/"
STOPSIGNAL SIGINT
EXPOSE 8080
ENTRYPOINT ["python", "-m", "app.main"]
