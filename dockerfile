# Use a slim base image to keep the container small and efficient
FROM python:3.10-slim

# Install necessary system packages if needed (e.g., build dependencies)
RUN apt-get update && apt-get install -y --no-install-recommends build-essential

# Set the working directory inside the container
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your main application code into the container
COPY app/collection_auditor.py .

# Define the command that runs when the container starts (this will be overwritten by docker-compose)
ENTRYPOINT ["python", "collection_auditor.py"]