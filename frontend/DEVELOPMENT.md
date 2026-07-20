# Frontend Development Guide

## Project Structure

- `app/` — Next.js app directory
  - `page.tsx` — Main page component
  - `layout.tsx` — Root layout
  - `globals.css` — Global styles
- `components/` — Reusable React components
  - `PromptSelector.tsx` — Prompt dropdown
  - `TimeoutSlider.tsx` — Timeout control
  - `ConversationButton.tsx` — Start/Stop button
  - `TranscriptDisplay.tsx` — Chat transcript
- `lib/` — Utility functions
  - `api.ts` — API client helpers
  - `audioCapture.ts` — Web Audio API wrapper
- `hooks/` — React hooks
  - `useAudioStream.ts` — Main integration hook

## Key Components

### useAudioStream Hook

Main hook managing audio capture, WebSocket connection, and transcript updates.

```typescript
const { messages, status } = useAudioStream(
  isRecording,      // boolean — when true, connects to backend
  promptKey,        // string — selected prompt key
  timeout,          // number — session timeout in seconds
);
```

Returns:
- `messages` — Array of `{role: 'user' | 'assistant', text: string}`
- `status` — Current status message (e.g., "Connected", "Disconnected")

### AudioCaptureManager

Wraps Web Audio API for microphone capture.

```typescript
const manager = new AudioCaptureManager();
await manager.initialize((audioFrame) => {
  // Handle Float32Array audio frame
});
manager.stop();
```

### API Client

Helper functions for backend communication.

```typescript
fetchPrompts()                     // GET /api/prompts
sendControlMessage(ws, action)     // Send start/stop
sendConfigMessage(ws, config)      // Send config updates
createWebSocketURL()               // Get WebSocket URL
```

## Environment Variables

- `NEXT_PUBLIC_API_URL` (default: http://localhost:8000) — Backend URL
  Must be prefixed with `NEXT_PUBLIC_` to be available in browser

## Running Locally

```bash
npm install
npm run dev
```

App runs on `http://localhost:3000`

## Build & Production

```bash
npm run build
npm start
```

## Browser Compatibility

Requires Web Audio API support (Chrome 32+, Firefox 25+, Safari 14+).

## Debugging

Enable React DevTools in browser extension.

Common issues:
- **"Failed to fetch prompts"** — Backend not running or CORS misconfigured
- **"Permission denied" for microphone** — Check browser permissions
- **WebSocket connection refused** — Backend URL incorrect or not listening

## Component Props

### PromptSelector
- `onSelect: (key: string) => void` — Called when prompt changes
- `disabled: boolean` — Disable during conversation

### TimeoutSlider
- `onchange: (timeout: number) => void` — Called when slider changes
- `disabled: boolean` — Disable during conversation

### ConversationButton
- `isRecording: boolean` — Current recording state
- `onStart: () => void` — Called when starting
- `onStop: () => void` — Called when stopping

### TranscriptDisplay
- `messages: Message[]` — Array of messages to display
