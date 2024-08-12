# Use the official Python image
FROM python:3.10-slim

# Set the working directory in the container
WORKDIR /app

ENV PYTHONPATH=/app

# Copy only the necessary files
COPY src/agents/requirements.txt /app/requirements.txt
COPY src/agents/app.py /app/app.py
COPY src/agents/crews /app/crews
COPY src/cloud_logging_helper.py /app/cloud_logging_helper.py

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make port 8080 available to the world outside this container
EXPOSE 8080

# Define environment variables
ENV PORT 8080
ENV PROJECT_ID research-assistant-424819
ENV SERVICE_ACCOUNT_SECRET_ID email_updates_secret
ENV OPENAI_API_KEY_SECRET_ID OPENAI_API_KEY
ENV ANTHROPIC_API_KEY_SECRET_ID ANTHROPIC_API_KEY

CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 app:app