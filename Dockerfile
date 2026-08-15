FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY client.py .
COPY client_lib.py .
COPY server.py .
COPY server_lib.py .

# Default command
CMD ["python", "server.py"]