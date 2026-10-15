FROM python:3.12-slim

# Keep the production image small. The application only needs Python packages
# from requirements.txt; no compiler toolchain is required at runtime.
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/collection_auditor.py .

ENTRYPOINT ["python", "collection_auditor.py"]
