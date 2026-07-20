'use client';

import { useEffect, useState } from 'react';

interface Prompt {
  key: string;
  label: string;
}

export default function PromptSelector({
  onSelect,
  disabled,
}: {
  onSelect: (key: string) => void;
  disabled: boolean;
}) {
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [selected, setSelected] = useState('');

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
    fetch(`${apiUrl}/api/prompts`)
      .then((res) => res.json())
      .then((data) => {
        setPrompts(data.prompts);
        if (data.prompts.length > 0) {
          setSelected(data.prompts[0].key);
        }
      })
      .catch((err) => console.error('Failed to fetch prompts:', err));
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const key = e.target.value;
    setSelected(key);
    onSelect(key);
  };

  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-2">
        Assistant Prompt
      </label>
      <select
        value={selected}
        onChange={handleChange}
        disabled={disabled}
        className="disabled:opacity-50"
      >
        {prompts.map((p) => (
          <option key={p.key} value={p.key}>
            {p.label}
          </option>
        ))}
      </select>
    </div>
  );
}
