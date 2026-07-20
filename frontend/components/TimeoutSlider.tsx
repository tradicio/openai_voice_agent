'use client';

import { useState } from 'react';

export default function TimeoutSlider({
  onchange,
  disabled,
}: {
  onchange: (timeout: number) => void;
  disabled: boolean;
}) {
  const [timeout, setTimeout] = useState(120);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = parseInt(e.target.value);
    setTimeout(value);
    onchange(value);
  };

  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-2">
        Maximum conversation time: {timeout}s
      </label>
      <input
        type="range"
        min="60"
        max="300"
        step="10"
        value={timeout}
        onChange={handleChange}
        disabled={disabled}
        className="disabled:opacity-50"
      />
    </div>
  );
}
