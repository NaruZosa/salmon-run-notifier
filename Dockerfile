# Use an official Python runtime as a parent image
FROM python:3.13-alpine

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
	POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

# Set the working directory
WORKDIR /app

# Copy the application
COPY pyproject.toml poetry.lock main.py salmon_config_template.toml requirements.txt ./

# Install dependencies
RUN pip install -r requirements.txt

# Create config directory and change permissions
RUN mkdir -p /app/config
RUN chmod 0777 -R /app/config # Fix directory permissions issues, notably affecting Unraid

# Run the application
CMD ["python", "-m", "main"]
