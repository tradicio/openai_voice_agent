'use client';

interface Message {
  role: 'user' | 'assistant';
  text: string;
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
        messages.map((msg, idx) => (
          <div key={idx} className={`message ${msg.role}`}>
            <strong>{msg.role === 'user' ? 'You:' : 'Assistant:'}</strong>{' '}
            {msg.text}
          </div>
        ))
      )}
    </div>
  );
}
