# Use a lightweight Python image
FROM python:3.8-slim

# Set the working directory
WORKDIR /app

# Copy and install dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Python script
COPY audio_checker.py /app/

RUN echo "invalidate cache"

# Optionally set environment variables (you can override these at runtime)
ENV AUDIO_LIST_URL="http://audio-uploader:3001/queue"
ENV INFERENCE_URL="http://pytorch-audio-inference:5000/infer"
ENV RESULT_URL="http://audio-uploader:3001/inference-result"
ENV DOWNLOAD_DIR="/tmp/audio_files"
ENV PROCESSED_FILE="/tmp/processed_files.txt"
ENV PORT=5009

# Expose the port
EXPOSE 5009

# Command to run the Flask app
CMD ["python", "audio_checker.py"]
