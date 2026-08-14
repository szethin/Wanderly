# Base image: Use lightweight official Python 3.10 slim Linux image
FROM python:3.14-slim

# Set internal working directory inside the container
WORKDIR /app

# Copy dependency requirements file first to leverage Docker build cache
COPY requirements.txt .

# Install Python dependencies without saving cache to minimize image size
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application code into the container
COPY . .

# Expose port 8000 for FastAPI service
EXPOSE 8000

# Start Uvicorn server bound to 0.0.0.0 to accept external container requests
CMD ["uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "8000"]