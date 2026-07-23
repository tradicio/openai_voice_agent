# Audio streaming tuning knobs.
AUDIO_CHUNK_SIZE = 4096
MONITOR_POLL_INTERVAL_S = 0.3
STREAM_IDLE_SLEEP_S = 0.01
MONITOR_TASK_TIMEOUT_S = 2
API_TASK_TIMEOUT_S = 5
STREAM_TASK_TIMEOUT_S = 2

# Reject oversized messages and cap the audio frame rate so a single
# client can't exhaust memory/CPU.
MAX_MESSAGE_BYTES = 128 * 1024
MAX_AUDIO_MESSAGES_PER_SECOND = 50
