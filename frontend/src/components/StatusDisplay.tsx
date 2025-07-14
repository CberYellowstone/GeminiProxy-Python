import React from 'react';

interface StatusDisplayProps {
  status: string;
  clientId: string;
}

const StatusDisplay: React.FC<StatusDisplayProps> = ({ status, clientId }) => {
  const statusColor =
    status === 'Connected'
      ? 'text-green-400'
      : status.includes('Disconnected')
      ? 'text-yellow-400'
      : 'text-red-400';

  return (
    <div className="bg-gray-800 p-4 rounded-lg mb-4">
      <h2 className="text-lg font-bold mb-2">Connection Status</h2>
      <p>
        <span className="font-semibold">Status: </span>
        <span className={statusColor}>{status}</span>
      </p>
      <p>
        <span className="font-semibold">Client ID: </span>
        <span>{clientId || 'N/A'}</span>
      </p>
    </div>
  );
};

export default StatusDisplay;