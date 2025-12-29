# Stage 1: Build the module
FROM python:alpine AS builder

WORKDIR /build

# Install build dependencies
RUN pip install --no-cache-dir setuptools wheel build

# Copy source code
COPY . .

# Build the distribution package (creates .tar.gz in dist/)
RUN python -m build

# Stage 2: Runtime environment
FROM python:alpine

# Set environment variables to prevent Python from writing pyc files and buffering stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DIR_APIER=/opt/ci_cd_apier
ENV APIER_VENV="$DIR_APIER/venv"

RUN apk add --no-cache age

# Create a virtual environment in /opt/ci_cd_apier
RUN python -m venv "$APIER_VENV"

# Copy the built distribution from builder stage
COPY --from=builder /build/dist/*.tar.gz /tmp/

# Install the built package
RUN "$APIER_VENV/bin/pip" install --no-cache-dir /tmp/*.tar.gz && \
    rm -rf /tmp/*.tar.gz
