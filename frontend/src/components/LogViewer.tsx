import React from 'react';

interface LogViewerProps {
  logs: string[];
}

const LogViewer: React.FC<LogViewerProps> = ({ logs }) => {
  return (
    <div className="bg-gray-800 p-4 rounded-lg h-96 overflow-y-auto">
      <h2 className="text-lg font-bold mb-2">Logs</h2>
      <pre className="text-sm whitespace-pre-wrap">
        {logs.map((log, index) => (
          <div key={index}>{log}</div>
        ))}
      </pre>
    </div>
  );
};

export default LogViewer;