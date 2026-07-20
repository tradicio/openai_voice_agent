'use client';

import { useEffect, useState, useCallback } from 'react';
import { AudioCaptureManager } from '@/lib/audioCapture';
import { createWebSocketURL, sendControlMessage, sendConfigMessage } from '@/lib/api';

interface Message {
  role: 'user' | 'assistant';
  text: string;
}

export function useAudioStream(
  isActive: boolean,
  promptKey: string,
  timeout: number,
) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [status, setStatus] = useState('');
  const [ws, setWs] = useState<WebSocket | null>(null);
  const [audioCapture, setAudioCapture] = useState<AudioCaptureManager | null>(
    null,
  );

  const handleAudioFrame = useCallback(
    (data: Float32Array) => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        // Convert Float32 to Int16 PCM
        const buffer = new ArrayBuffer(data.length * 2);
        const view = new Int16Array(buffer);
        for (let i = 0; i < data.length; i++) {
          view[i] = Math.max(-1, Math.min(1, data[i])) * 0x7fff;
        }
        const base64 = btoa(String.fromCharCode(...new Uint8Array(buffer)));
        ws.send(
          JSON.stringify({
            type: 'audio',
            data: base64,
          }),
        );
      }
    },
    [ws],
  );

  // Initialize WebSocket and audio capture when active
  useEffect(() => {
    if (!isActive) {
      // Cleanup
      if (ws) {
        sendControlMessage(ws, 'stop');
        ws.close();
        setWs(null);
      }
      if (audioCapture) {
        audioCapture.stop();
        setAudioCapture(null);
      }
      return;
    }

    // Establish WebSocket connection
    const wsUrl = createWebSocketURL();
    const newWs = new WebSocket(wsUrl);

    newWs.onopen = async () => {
      setStatus('Connected');
      setWs(newWs);

      // Send initial config
      sendConfigMessage(newWs, {
        prompt_key: promptKey,
        timeout,
      });

      // Initialize audio capture
      const manager = new AudioCaptureManager();
      await manager.initialize(handleAudioFrame);
      setAudioCapture(manager);

      // Start conversation
      sendControlMessage(newWs, 'start');
    };

    newWs.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);

        if (message.type === 'status') {
          setStatus(message.message);
        } else if (message.type === 'transcript') {
          setMessages((prev) => [
            ...prev,
            { role: message.role, text: message.delta },
          ]);
        }
      } catch (err) {
        console.error('Failed to parse WebSocket message:', err);
      }
    };

    newWs.onerror = (event) => {
      setStatus(`Error: ${event}`);
      console.error('WebSocket error:', event);
    };

    newWs.onclose = () => {
      setStatus('Disconnected');
    };

    return () => {
      if (newWs.readyState === WebSocket.OPEN) {
        newWs.close();
      }
      if (audioCapture) {
        audioCapture.stop();
      }
    };
  }, [isActive, promptKey, timeout]);

  return { messages, status };
}
