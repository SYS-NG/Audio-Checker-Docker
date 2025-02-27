import time
import requests
import os
import logging
from datetime import datetime
from flask import Flask, jsonify

# ---------------------------
# Setup Logging
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ---------------------------
# Configuration Variables
# ---------------------------
# URL to check for new audio files (this endpoint should return a JSON list of URLs)
AUDIO_LIST_URL = os.getenv("AUDIO_LIST_URL", "http://localhost:3001/queue")
logger.info(f"AUDIO_LIST_URL set to: {AUDIO_LIST_URL}")

# URL for the inference container's endpoint.
# If both containers are on the same Docker network, use the container's service name.
#INFERENCE_URL = os.getenv("INFERENCE_URL", "http://pytorch-audio-inference:5000/infer")
INFERENCE_URL = os.getenv("INFERENCE_URL", "http://localhost:5000/infer")


# Directory where downloaded audio files are stored
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/tmp/audio_files")
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# File to keep track of already processed files
PROCESSED_FILE = os.getenv("PROCESSED_FILE", "/tmp/processed_files.txt")
processed_files = set()
if os.path.exists(PROCESSED_FILE):
    with open(PROCESSED_FILE, "r") as f:
        for line in f:
            processed_files.add(line.strip())

def save_processed(file_identifier):
    """Append a processed file identifier (e.g. URL) to our tracking file."""
    with open(PROCESSED_FILE, "a") as f:
        f.write(file_identifier + "\n")

# ---------------------------
# Functions
# ---------------------------
def check_for_new_files():
    """
    Queries the hosted site for a JSON list of new .wav file URLs.
    Returns a list of URLs.
    """
    try:
        response = requests.get(AUDIO_LIST_URL)
        logger.info(f"Audio request response: {response}")
        response.raise_for_status()
        if response.text:
            try:
                audio_files = response.json()  # Attempt to parse JSON
                return audio_files
            except ValueError:
                logger.error("Response content is not valid JSON.")
                return []  # Return empty list if JSON parsing fails
        else:
            logger.info("No new audio files found.")
            return []
    except Exception as e:
        logger.error(f"Error checking for new audio files: {e}")
        return []

def download_file(url):
    """
    Downloads the audio file from the provided URL.
    Returns the local file path if successful.
    """
    try:
        local_filename = os.path.join(DOWNLOAD_DIR, url.split("/")[-1])
        logger.info(f"Downloading {url} to {local_filename}")
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(local_filename, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return local_filename
    except Exception as e:
        logger.error(f"Error downloading file {url}: {e}")
        return None

def trigger_inference(file_path):
    """
    Calls the inference container by posting the audio file to its endpoint.
    Logs and returns the response.
    """
    try:
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, "audio/wav")}
            logger.info(f"Sending {file_path} to inference container at URL: {INFERENCE_URL}")
            logger.info(f"File size: {os.path.getsize(file_path)} bytes")
            
            # Log request details before sending
            logger.info(f"Making POST request with file: {os.path.basename(file_path)}")
            
            # Send the request and time it
            start_time = time.time()
            response = requests.post(INFERENCE_URL, files=files)
            request_time = time.time() - start_time
            
            # Log response details
            logger.info(f"Inference request completed in {request_time:.2f} seconds")
            logger.info(f"Response status code: {response.status_code}")
            logger.info(f"Response headers: {response.headers}")
            
            response.raise_for_status()
            logger.info(f"Inference response for {file_path}: {response.text}")
            return response.text
    except requests.exceptions.ConnectionError as e:
        logger.error(f"Connection error when triggering inference: {e}")
        logger.error(f"Could not connect to inference server at {INFERENCE_URL}. Is it running?")
        return None
    except requests.exceptions.Timeout as e:
        logger.error(f"Timeout error when triggering inference: {e}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error when triggering inference: {e}")
        return None
    except Exception as e:
        logger.error(f"Error triggering inference for {file_path}: {e}")
        logger.exception("Full exception details:")
        return None

def send_inference_result(filename, inference_result):
    """
    Sends the inference result back to the audio-uploader endpoint.
    Returns True if successful, False otherwise.
    """
    try:
        # Parse the inference result to determine if it's human or not
        # Assuming the inference result is a JSON string containing an "isHuman" field
        import json
        result_data = json.loads(inference_result)
        is_human = result_data.get("prediction", "").lower() == "human"
        
        # Prepare the payload
        payload = {
            "filename": filename,
            "isHuman": is_human
        }
        
        # URL for the audio-uploader endpoint
        result_url = os.getenv("RESULT_URL", "http://localhost:3001/inference-result")
        
        logger.info(f"Sending inference result for {filename} to {result_url}")
        logger.info(f"Payload: {payload}")
        
        # Send the POST request
        response = requests.post(result_url, json=payload)
        response.raise_for_status()
        
        logger.info(f"Result submission response: {response.text}")
        return True
    except Exception as e:
        logger.error(f"Error sending inference result for {filename}: {e}")
        logger.exception("Full exception details:")
        return False

# Initialize Flask app
app = Flask(__name__)

@app.route('/process-audio', methods=['GET'])
def process_audio():
    """
    Endpoint that checks for new audio files, processes them,
    and returns the inference results.
    """
    logger.info("Received request to process audio files")
    results = []
    audio_files = check_for_new_files()
    
    logger.info(f"Found {len(audio_files)} audio files to process")
    
    for queued_audio_data in audio_files:
        file_url = queued_audio_data['downloadUrl']
        filename = file_url.split("/")[-1]
        logger.info(f"Processing file with URL: {file_url}")
        
        # Skip files that have already been processed
        if file_url in processed_files:
            logger.info(f"Already processed {file_url}")
            results.append({
                'url': file_url,
                'status': 'skipped',
                'message': 'Already processed'
            })
            continue

        local_file = download_file(file_url)
        if local_file:
            logger.info(f"Successfully downloaded file to {local_file}, triggering inference")
            inference_result = trigger_inference(local_file)
            
            if inference_result:
                logger.info(f"Inference successful for {file_url}")
                
                # Send the inference result back to the audio-uploader
                _ = send_inference_result(filename, inference_result)
                
                processed_files.add(file_url)
                save_processed(file_url)
                results.append({
                    'url': file_url,
                    'status': 'success',
                    'inference_result': inference_result,
                })
            else:
                logger.error(f"Inference failed for {file_url}")
                results.append({
                    'url': file_url,
                    'status': 'error',
                    'message': 'Inference failed'
                })
        else:
            logger.error(f"Failed to download file from {file_url}")
            results.append({
                'url': file_url,
                'status': 'error',
                'message': 'Failed to download file'
            })

    logger.info(f"Processed {len(results)} files, returning results")
    return jsonify({
        'processed_files': len(results),
        'results': results
    })

if __name__ == "__main__":
    # Run the Flask app
    port = os.getenv('PORT', 5009)
    logger.info(f"Environment variables:")
    logger.info(f"PORT: {os.getenv('PORT')}")
    logger.info(f"AUDIO_LIST_URL: {os.getenv('AUDIO_LIST_URL')}")
    logger.info(f"INFERENCE_URL: {os.getenv('INFERENCE_URL')}")
    logger.info(f"RESULT_URL: {os.getenv('RESULT_URL', 'http://localhost:3001/inference-result')}")
    logger.info(f"Starting Flask app on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
