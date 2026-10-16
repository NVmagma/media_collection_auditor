FROM python:3.12-slim

# Keep the production image small. The application only needs Python packages
# from requirements.txt; no compiler toolchain is required at runtime.
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/collection_auditor.py .
COPY app/main.py .
COPY app/web.py .
COPY app/templates ./templates
COPY app/static ./static

EXPOSE 8080

ENTRYPOINT ["python", "main.py"]
