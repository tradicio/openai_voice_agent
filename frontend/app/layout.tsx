import type { ReactNode } from 'react';
import './globals.css';

export const metadata = {
  title: 'OpenAI Realtime Voice Chat',
  description: 'Voice conversation with OpenAI using Next.js',
};

export default function RootLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <html lang="en">
      <body className="bg-gray-50">
        <main className="min-h-screen flex items-center justify-center p-4">
          <div className="w-full max-w-md bg-white rounded-lg shadow-lg p-6">
            {children}
          </div>
        </main>
      </body>
    </html>
  );
}
