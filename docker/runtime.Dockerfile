# JSON runtime. Build and verify before selecting a published image.
ARG BASE_IMAGE=python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
FROM ${BASE_IMAGE}
# Debian DSA-6607-1. Use HTTPS to fetch the fix for the APT HTTP transport.
RUN sed -i 's|http://|https://|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=0 update \
    && apt-get -o Acquire::Retries=0 install -y --no-install-recommends --only-upgrade apt libapt-pkg7.0 \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' apt)" ge 3.0.4 \
    && dpkg --compare-versions "$(dpkg-query -W -f='${Version}' libapt-pkg7.0)" ge 3.0.4 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV PYTHONPATH=/app/app:/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    AUDITOR_WORKER_MODE=json_serialized AUDITOR_STATE_BACKEND=json \
    DRY_RUN=true MAX_ACTIONS_PER_RUN=10 ALLOW_PERMANENT_DELETE=false \
    ALLOW_FILESYSTEM_DELETE=false ALLOW_CROSS_FILESYSTEM_MOVES=false ENABLE_SEASON_PRUNING=false
COPY requirements.txt /app/requirements.txt
COPY docker/runtime-constraints.txt /app/runtime-constraints.txt
RUN pip install --no-cache-dir -r /app/requirements.txt -c /app/runtime-constraints.txt
COPY app/ /app/app/
COPY unraid/assets/Media_Collection_Auditor_Badge.png /app/app/static/auditor-badge.png
COPY unraid/assets/media-collection-auditor-icon.png /app/app/static/auditor-icon.png
RUN WEB_SESSION_SECRET=synthetic-build-import-check python -B -c "import app.main, app.json_worker_cycle, app.json_worker_service, app.json_operation_recovery, app.json_arr_import_service; assert app.json_worker_service.enabled()"
ARG SOURCE_REVISION
LABEL org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.title="Media Collection Auditor JSON worker" \
      io.media-collection-auditor.worker="json-serialized"
STOPSIGNAL SIGINT
EXPOSE 8080
ENTRYPOINT ["python", "-B", "-m", "app.main"]
