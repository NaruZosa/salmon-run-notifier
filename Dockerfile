# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_IN_PROJECT=true

# Install Poetry
RUN pip install "poetry==$POETRY_VERSION"

# Set the working directory
WORKDIR /app

# Copy the application
COPY pyproject.toml poetry.lock main.py salmon_config_template.toml ./

# Install dependencies
RUN poetry install --without dev

# Create config directory and change permissions
RUN mkdir -p /app/config
RUN chmod 0777 -R /app/config # Fix directory permissions issues, notably affecting Unraid

# Run the application
CMD ["poetry", "run", "python", "-m", "main"]
