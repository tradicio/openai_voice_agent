const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function fetchPrompts() {
  const res = await fetch(`${API_URL}/api/prompts`);
  if (!res.ok) throw new Error('Failed to fetch prompts');
  return res.json();
}

export function sendControlMessage(ws: WebSocket, action: 'start' | 'stop') {
  ws.send(
    JSON.stringify({
      type: 'control',
      action,
    }),
  );
}

export function sendConfigMessage(
  ws: WebSocket,
  config: { prompt_key?: string; model?: string; voice?: string },
) {
  ws.send(
    JSON.stringify({
      type: 'config',
      ...config,
    }),
  );
}

export function createWebSocketURL(): string {
  const apiUrl = API_URL.replace('http://', 'ws://').replace('https://', 'wss://');
  return `${apiUrl}/ws/audio`;
}
