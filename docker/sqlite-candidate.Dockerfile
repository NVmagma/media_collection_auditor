# Build only with an explicitly pinned official Python base.
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
COPY unraid/assets/media-collection-auditor-icon.png /app/app/static/auditor-icon.png
RUN WEB_SESSION_SECRET=build-only-candidate-import-check python -c "import app.main, app.sqlite_scheduled_service, app.sqlite_scheduled_production, app.sqlite_tracking_view, app.sqlite_scheduled_observations; from app.sqlite_release_profile import PROFILE; assert PROFILE == 'sealed'; from app.sqlite_backend_gate import require_sqlite_production_activation; from unittest import TestCase; TestCase().assertRaises(RuntimeError, require_sqlite_production_activation)"
ARG SOURCE_REVISION
LABEL org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.title="Media Collection Auditor SQLite candidate" \
      io.media-collection-auditor.sqlite-activation="disabled"
STOPSIGNAL SIGINT
EXPOSE 8080
ENTRYPOINT ["python", "-m", "app.main"]
