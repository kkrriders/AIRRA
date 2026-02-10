FROM python:3.11-slim

WORKDIR /app

# Install dependencies
RUN pip install flask prometheus-client

# Copy service
COPY payment-service.py .

# Expose port
EXPOSE 5001

# Run service
CMD ["python", "payment-service.py"]
