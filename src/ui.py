import streamlit as st
from streamlit_webrtc import WebRtcMode, webrtc_streamer

from src.prompts.prompts import load_prompts
from src.realtime.realtime_client import OpenAIRealtimeAPIWrapper
from src.utils.st_utils import get_logger, get_event_loop, hash_by_code


logger = get_logger(__name__)


def main():
    loop = get_event_loop(_logger = logger)

    # Regenerate when code changes to utilize Streamlit's hot reload
    api_wrapper_key = f"api_wrapper-{hash_by_code(OpenAIRealtimeAPIWrapper)}"

    if api_wrapper_key not in st.session_state:
        openai_api_key = st.secrets['OPENAI_API_KEY']
        st.session_state[api_wrapper_key] = \
                OpenAIRealtimeAPIWrapper(api_key = openai_api_key)
    api_wrapper = st.session_state[api_wrapper_key]

    session_timeout = st.slider(
        'Maximum conversation time (seconds)',
        min_value = 60,
        max_value = 300,
        value = 120
    )
    api_wrapper.set_session_timeout(session_timeout)

    prompts = load_prompts()
    prompt_key = st.selectbox(
        'Assistant prompt',
        options = list(prompts.keys()),
        format_func = lambda key: prompts[key]['label'],
        disabled = st.session_state.get('recording', False),
    )
    api_wrapper.set_instructions(prompts[prompt_key]['instructions'])

    # webrtc_streamer has its own start button,
    # but we control it externally because we don't know how to notify api_wrapper
    if 'recording' not in st.session_state:
        st.session_state.recording = False
    if st.session_state.recording:
        if st.button('End conversation', type = 'primary'):
            st.session_state.recording = False
    else:
        if st.button('Start conversation'):
            st.session_state.recording = True

    webrtc_ctx = webrtc_streamer(
        key = f"recoder",
        mode = WebRtcMode.SENDRECV,
        rtc_configuration = dict(
            iceServers = [
                dict(urls = ['stun:stun.l.google.com:19302'])
            ]
        ),
        audio_frame_callback = api_wrapper.audio_frame_callback,
        media_stream_constraints = dict(video = False, audio = True),
        desired_playing_state = st.session_state.recording,
    )

    if webrtc_ctx.state.playing and st.session_state.recording:
        if not api_wrapper.recording:
            st.write('Connecting to OpenAI.')
            logger.info('Starting running')
            loop.run_until_complete(api_wrapper.run())
            logger.info('Finished running')
            st.write('Disconnected from OpenAI.')
            st.session_state.recording = False
            st.rerun()
    else:
        if api_wrapper.recording:
            logger.info('Stopping running')
            api_wrapper.stop()
            st.session_state.recording = False
            st.rerun()
        api_wrapper.write_messages()
