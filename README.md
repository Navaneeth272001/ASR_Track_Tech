# ASR_Track_Tech
Automatic Speech Recognition System for Track Tech

stt-pipeline/
│── requirements.txt
│── config.py
│── classifier.py
│── queue_sender.py
│── transcribe_ws.py
│── main.py

# Race Track Announcement System - Raspberry Pi Setup
This guide helps you set up the Raspberry Pi to run the race track announcement notification system using AWS Transcribe Streaming and MQTT or HTTP delivery.
1️⃣ Clone the repository
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git
cd YOUR_REPO
2️⃣ Set up Python environment
sudo apt update
sudo apt install python3-venv python3-pip -y

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install required Python packages
pip install --upgrade pip
pip install -r requirements.txt
Dependencies include:
aiohttp, boto3, sounddevice, numpy, rapidfuzz, paho-mqtt, requests
Note: sounddevice requires PortAudio:
sudo apt install libportaudio2 libportaudiocpp0 portaudio19-dev -y
3️⃣ Configure AWS
Step 3a: Install AWS CLI
sudo apt install awscli -y
aws --version
Step 3b: Create IAM user
Go to AWS IAM Console.
Create a new user with Programmatic access.
Attach the AmazonTranscribeFullAccess policy.
Download the access key CSV.
Step 3c: Configure AWS credentials
aws configure
Enter your credentials and region:
AWS Access Key ID [None]: <YOUR_ACCESS_KEY_ID>
AWS Secret Access Key [None]: <YOUR_SECRET_ACCESS_KEY>
Default region name [None]: us-east-1
Default output format [None]: json
Alternatively, you can set environment variables in ~/.bashrc:
export AWS_ACCESS_KEY_ID=<YOUR_ACCESS_KEY_ID>
export AWS_SECRET_ACCESS_KEY=<YOUR_SECRET_ACCESS_KEY>
export AWS_DEFAULT_REGION=us-east-1
Verify configuration:
aws transcribe list-transcription-jobs
4️⃣ Configure microphone
Plug in your microphone (USB or Pi Audio Hat).
List available devices:
import sounddevice as sd
print(sd.query_devices())
Update MIC_DEVICE_INDEX in transcribe_ws.py to match your mic.
Sample configuration in config.py:
MIC_SAMPLE_RATE = 44100      # input mic sample rate
STREAM_SAMPLE_RATE = 16000   # AWS Transcribe rate
FRAME_MS = 20
5️⃣ Configure MQTT / HTTP delivery
Update config.py:
DELIVERY_MODE = "MQTT"  # or "HTTP"

MQTT_BROKER = "node.kaatru.org"
MQTT_PORT = 1883
MQTT_TOPIC = "racetrack/announcements"

PUSH_ENDPOINT = "https://YOUR_BACKEND/notify"  # if using HTTP
6️⃣ Run the system
source venv/bin/activate
python main.py
You should see logs like:
[mqtt] connected to broker node.kaatru.org
[transcribe] connected
[mic] using device: USB Microphone channels: 1 rate: 44100
[transcript] Amateur to the lanes
The system will stream microphone audio to AWS Transcribe, classify transcripts, and send notifications via MQTT or HTTP.
7️⃣ Additional Notes
Debounce: The system prevents duplicate announcements within DEBOUNCE_SECONDS (default 180s).
Queueing: Messages are persisted locally in outbox.db if delivery fails.
Testing: Speak any of the configured classes and intents, e.g.:
"Super Pro to the lanes"
"Sportsman standby"
"Amateur to the lanes"
"General announcement: safety first"
Shutdown: Press Ctrl+C to gracefully stop the system.