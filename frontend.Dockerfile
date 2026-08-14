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

# Expose port 8501 for Streamlit service
EXPOSE 8501

# Start Streamlit application bound to 0.0.0.0
CMD ["streamlit", "run", "app/ui.py", "--server.port=8501", "--server.address=0.0.0.0"]