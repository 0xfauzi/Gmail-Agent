FROM python:3.9-slim

WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .
COPY cloud_logging_helper.py .

# Install the Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the watcher.py file into the container
COPY watcher.py .

ENV PYTHONPATH=/app

# Set the command to run the watcher.py script
CMD ["python", "watcher.py"]