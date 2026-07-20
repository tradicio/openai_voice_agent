'use client';

interface ConversationButtonProps {
  isRecording: boolean;
  onStart: () => void;
  onStop: () => void;
}

export default function ConversationButton({
  isRecording,
  onStart,
  onStop,
}: ConversationButtonProps) {
  return (
    <button
      onClick={isRecording ? onStop : onStart}
      className={`w-full py-3 rounded-lg font-semibold text-white transition ${
        isRecording
          ? 'bg-red-600 hover:bg-red-700'
          : 'bg-green-600 hover:bg-green-700'
      }`}
    >
      {isRecording ? 'End Conversation' : 'Start Conversation'}
    </button>
  );
}
