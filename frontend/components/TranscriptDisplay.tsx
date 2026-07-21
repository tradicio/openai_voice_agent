'use client';

interface Message {
  role: 'user' | 'assistant';
  text: string;
  seq: number;
}

export default function TranscriptDisplay({
  messages,
}: {
  messages: Message[];
}) {
  return (
    <div className="transcript">
      {messages.length === 0 ? (
        <p className="text-gray-500 text-sm">No messages yet...</p>
      ) : (
        messages.map((msg) => (
          <div key={msg.seq} className={`message ${msg.role}`}>
            <strong>{msg.role === 'user' ? 'You:' : 'Assistant:'}</strong>{' '}
            {msg.text}
          </div>
        ))
      )}
    </div>
  );
}
