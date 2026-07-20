export default function Home() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-center text-gray-900">
        OpenAI Realtime Voice Chat
      </h1>
      <p className="text-center text-gray-600">
        Next.js frontend ready to connect to the backend API.
      </p>
      <div className="mt-6 p-4 bg-blue-50 rounded-lg border border-blue-200">
        <p className="text-sm text-blue-800">
          API URL: {process.env.NEXT_PUBLIC_API_URL}
        </p>
      </div>
    </div>
  );
}
