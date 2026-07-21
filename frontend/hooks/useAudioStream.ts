'use client';

import { useEffect, useState, useRef } from 'react';
import { AudioCaptureManager } from '@/lib/audioCapture';
import { AudioPlaybackManager } from '@/lib/audioPlayback';
import { createWebSocketURL, sendControlMessage, sendConfigMessage } from '@/lib/api';

interface Message {
  role: 'user' | 'assistant';
  text: string;
  index: number;
}

interface RawMessage {
  role: 'user' | 'assistant';
  text: string;
}

// Must match backend CLIENT_CHANNELS (src/realtime/config.py)
const CLIENT_CHANNELS = 2;

function insertSorted(indices: number[], value: number): void {
  let lo = 0;
  let hi = indices.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (indices[mid] < value) lo = mid + 1;
    else hi = mid;
  }
  indices.splice(lo, 0, value);
}

function encodeAudioFrame(data: Float32Array): string {
  // Convert mono Float32 to interleaved stereo Int16 PCM
  // (backend expects CLIENT_CHANNELS channels)
  const buffer = new ArrayBuffer(data.length * 2 * CLIENT_CHANNELS);
  const view = new Int16Array(buffer);
  for (let i = 0; i < data.length; i++) {
    const sample = Math.max(-1, Math.min(1, data[i])) * 0x7fff;
    for (let ch = 0; ch < CLIENT_CHANNELS; ch++) {
      view[i * CLIENT_CHANNELS + ch] = sample;
    }
  }
  return btoa(String.fromCharCode(...new Uint8Array(buffer)));
}

export function useAudioStream(
  isActive: boolean,
  promptKey: string,
  timeout: number,
) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [status, setStatus] = useState('');
  // Refs (not state) so the audio callback always sees the live instance
  // instead of a stale closure captured before the WebSocket/state updated.
  const wsRef = useRef<WebSocket | null>(null);
  const audioCaptureRef = useRef<AudioCaptureManager | null>(null);
  const audioPlaybackRef = useRef<AudioPlaybackManager | null>(null);
  // Raw per-backend-index transcript content, keyed by the stable index the
  // backend assigned when the underlying message was created. The user's own
  // transcript (via Whisper) commonly arrives well after the assistant's
  // reply to it has already started streaming in, so messages do NOT arrive
  // over the WebSocket in index order. We keep the untouched raw content here
  // and re-derive the displayed bubbles from it, sorted by index.
  const rawMessagesRef = useRef<Map<number, RawMessage>>(new Map());
  // Indices seen so far, kept sorted incrementally (see insertSorted) so
  // re-deriving the bubble list never needs a fresh O(n log n) sort.
  const orderedIndicesRef = useRef<number[]>([]);
  // Merged, displayed bubbles from the last full rebuild, and which bubble
  // each raw index currently contributes to — lets a delta on an
  // already-known index update its bubble's text in O(1) instead of
  // re-merging every message on every incoming token.
  const mergedRef = useRef<Message[]>([]);
  const indexToBubblePosRef = useRef<Map<number, number>>(new Map());

  const rebuildMerged = (): Message[] => {
    const merged: Message[] = [];
    const indexToBubblePos = new Map<number, number>();
    for (const index of orderedIndicesRef.current) {
      const msg = rawMessagesRef.current.get(index);
      if (!msg || !msg.text) continue;
      const last = merged[merged.length - 1];
      if (last && last.role === msg.role) {
        last.text += msg.text;
      } else {
        merged.push({ role: msg.role, text: msg.text, index });
      }
      indexToBubblePos.set(index, merged.length - 1);
    }
    mergedRef.current = merged;
    indexToBubblePosRef.current = indexToBubblePos;
    return merged;
  };

  const applyTranscriptDelta = (
    index: number,
    role: 'user' | 'assistant',
    delta: string,
  ): Message[] => {
    const existing = rawMessagesRef.current.get(index);
    const isNewIndex = !existing;
    rawMessagesRef.current.set(index, {
      role,
      text: (existing?.text ?? '') + delta,
    });

    if (isNewIndex) {
      insertSorted(orderedIndicesRef.current, index);
      return rebuildMerged();
    }

    const bubblePos = indexToBubblePosRef.current.get(index);
    const bubble = bubblePos !== undefined ? mergedRef.current[bubblePos] : undefined;
    if (!bubble) {
      // Shouldn't normally happen (every known index gets a bubble on
      // insertion), but fall back to a full rebuild rather than drop data.
      return rebuildMerged();
    }
    mergedRef.current = mergedRef.current.map((b, i) =>
      i === bubblePos ? { ...b, text: b.text + delta } : b,
    );
    return mergedRef.current;
  };

  const resetTranscript = () => {
    rawMessagesRef.current = new Map();
    orderedIndicesRef.current = [];
    mergedRef.current = [];
    indexToBubblePosRef.current = new Map();
  };

  useEffect(() => {
    if (!isActive) {
      // Cleanup
      if (wsRef.current) {
        sendControlMessage(wsRef.current, 'stop');
        wsRef.current.close();
        wsRef.current = null;
      }
      if (audioCaptureRef.current) {
        audioCaptureRef.current.stop();
        audioCaptureRef.current = null;
      }
      if (audioPlaybackRef.current) {
        audioPlaybackRef.current.stop();
        audioPlaybackRef.current = null;
      }
      return;
    }

    resetTranscript();
    setMessages([]);

    // Establish WebSocket connection
    const wsUrl = createWebSocketURL();
    const newWs = new WebSocket(wsUrl);
    wsRef.current = newWs;

    const playback = new AudioPlaybackManager();
    audioPlaybackRef.current = playback;

    const handleAudioFrame = (data: Float32Array) => {
      if (newWs.readyState !== WebSocket.OPEN) return;
      newWs.send(
        JSON.stringify({
          type: 'audio',
          data: encodeAudioFrame(data),
        }),
      );
    };

    const handleSocketMessage = (event: MessageEvent) => {
      try {
        const message = JSON.parse(event.data);

        if (message.type === 'status') {
          setStatus(message.message);
        } else if (message.type === 'transcript') {
          setMessages(
            applyTranscriptDelta(message.index, message.role, message.delta),
          );
        } else if (message.type === 'audio') {
          audioPlaybackRef.current?.playChunk(message.data);
        } else if (message.type === 'clear_audio') {
          // User barged in: stop whatever assistant audio is already
          // scheduled client-side instead of letting it finish playing out.
          audioPlaybackRef.current?.clear();
        }
      } catch (err) {
        console.error('Failed to parse WebSocket message:', err);
      }
    };

    newWs.onopen = async () => {
      setStatus('Connected');

      playback.initialize();

      // Send initial config
      sendConfigMessage(newWs, {
        prompt_key: promptKey,
        timeout,
      });

      // Initialize audio capture
      const manager = new AudioCaptureManager();
      await manager.initialize(handleAudioFrame);
      audioCaptureRef.current = manager;

      // Start conversation
      sendControlMessage(newWs, 'start');
    };

    newWs.onmessage = handleSocketMessage;

    newWs.onerror = (event) => {
      setStatus('Connection error');
      console.error('WebSocket error:', event);
    };

    newWs.onclose = () => {
      setStatus('Disconnected');
    };

    return () => {
      if (newWs.readyState === WebSocket.OPEN) {
        newWs.close();
      }
      audioCaptureRef.current?.stop();
      audioCaptureRef.current = null;
      audioPlaybackRef.current?.stop();
      audioPlaybackRef.current = null;
      wsRef.current = null;
    };
  }, [isActive, promptKey, timeout]);

  return { messages, status };
}
