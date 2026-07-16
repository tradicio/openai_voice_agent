# Restructure project modules

## Problem

The working app is currently split across `main.py` (539 lines) and a couple of
loosely-named helper files. `main.py` mixes four unrelated concerns: Realtime
API configuration constants, the `OpenAIRealtimeAPIWrapper` class (WebSocket
connection + audio streaming engine), the Streamlit page (`main()`), and
process-level logging setup. `utils.py` mixes three unrelated helpers: audio
frame conversion, YAML prompt loading, and a Streamlit hot-reload hashing
utility. This makes the codebase hard to navigate and hard to change safely —
e.g. touching audio resampling risks touching UI code in the same file.

## Goals

- Reorganize existing code into modules with single, clear responsibilities.
- No behavior changes. No new abstractions, features, or refactors beyond
  moving code and updating imports.

## Non-goals

- No package directory (e.g. `app/`) — flat top-level modules only, matching
  the project's small size.
- No test suite additions as part of this change.
- No changes to `tools.py` (already well-scoped) or `prompts.yaml`.

## Design

### File layout

| File | Contents | Source |
|---|---|---|
| `config.py` | `REALTIME_API_URL`, `REALTIME_API_HEADERS`, `REALTIME_API_CONFIG`, `DEFAULT_INSTRUCTIONS`, audio format constants (`API_SAMPLE_RATE`, `API_SAMPLE_WIDTH`, `API_CHANNELS`, `CLIENT_SAMPLE_RATE`, `CLIENT_SAMPLE_WIDTH`, `CLIENT_CHANNELS`, `FORMAT_MAPPING`, `LAYOUT_MAPPING`) | extracted from `main.py` |
| `audio_utils.py` | `audio_frame_to_pcm_audio`, `pcm_audio_to_audio_frame`, `get_blank_audio_frame` | moved from `utils.py` |
| `prompts.py` | `load_prompts` | moved from `utils.py` |
| `st_utils.py` | `get_logger`, `get_event_loop` (existing) + `hash_by_code` (moved from `utils.py`) | existing file, extended |
| `tools.py` | unchanged | as-is |
| `realtime_client.py` | `TerminateTaskGroup` exception, `OpenAIRealtimeAPIWrapper` class | extracted from `main.py` |
| `ui.py` | the Streamlit page logic (current `main()` function body, renders sliders/buttons/webrtc/chat) | extracted from `main.py` |
| `main.py` | thin entry point: `logging.basicConfig` setup, third-party logger level tweaks, calls `ui.main()` under `if __name__ == '__main__':` | trimmed from current `main.py` |

`utils.py` is deleted once its three responsibilities are redistributed.

### Dependency graph

```
main.py -> ui.py -> realtime_client.py -> config.py -> tools.py
                  |                    -> audio_utils.py
                  |                    -> tools.py
                  |                    -> st_utils.py
                  -> prompts.py
                  -> st_utils.py
```

No circular imports: `config.py` depends only on `tools.py` (for
`TOOL_DEFINITIONS`); `audio_utils.py`, `prompts.py`, `st_utils.py`, `tools.py`
are leaves with no internal dependencies.

### Import changes

- `realtime_client.py` imports from `config.py` (constants), `audio_utils.py`
  (frame conversion), `tools.py` (`TOOL_HANDLERS`, `TOOL_INSTRUCTIONS`), and
  `st_utils.py` (`get_logger`).
- `ui.py` imports `OpenAIRealtimeAPIWrapper` from `realtime_client.py`,
  `load_prompts` from `prompts.py`, `hash_by_code`/`get_logger`/
  `get_event_loop` from `st_utils.py`.
- `main.py` imports `ui` and calls `ui.main()`.

## Testing / verification

No automated tests exist for this project. Verification is manual: after the
split, run `uv run streamlit run main.py`, start a conversation, confirm audio
streaming, transcripts, tool-calling (end-of-conversation), and the prompt
selector all behave exactly as before the restructure.
