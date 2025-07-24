

import React from 'react';
import StatusIcon, { Status } from './StatusIcon';
import type { TestStatus } from '../App';

interface StatusDashboardProps {
  status: Status;
  statusText: string;
  statusColor: string;
  isReconnecting: boolean;
  isConnected: boolean;
  isFailed: boolean;
  testStatus: TestStatus;
  onActionClick: () => void;
  onSettingsClick: () => void;
  onTestClick: () => void;
}

const StatusDashboard = ({
  status,
  statusText,
  statusColor,
  isConnected,
  isReconnecting,
  isFailed,
  testStatus,
  onActionClick,
  onSettingsClick,
  onTestClick,
}: StatusDashboardProps) => {
  let buttonText: string;
  let buttonColorClass: string;

  if (isReconnecting) {
    buttonText = 'Cancel';
    buttonColorClass = 'bg-yellow-600 hover:bg-yellow-700 focus-visible:outline-yellow-600';
  } else if (isConnected) {
    buttonText = 'Disconnect';
    buttonColorClass = 'bg-red-600 hover:bg-red-700 focus-visible:outline-red-600';
  } else if (isFailed) {
    buttonText = 'Retry Connection';
    buttonColorClass = 'bg-indigo-600 hover:bg-indigo-700 focus-visible:outline-indigo-600';
  } else {
    buttonText = 'Connect';
    buttonColorClass = 'bg-indigo-600 hover:bg-indigo-700 focus-visible:outline-indigo-600';
  }
  
  let testButtonText: string;
  let testButtonColorClass: string;
  
  switch (testStatus) {
    case 'testing':
      testButtonText = 'Testing...';
      testButtonColorClass = 'bg-gray-600/50 text-gray-400 ring-gray-700';
      break;
    case 'success':
      testButtonText = 'Success!';
      testButtonColorClass = 'bg-green-600 hover:bg-green-700 ring-green-500 focus-visible:outline-green-500';
      break;
    case 'failed':
      testButtonText = 'Failed!';
      testButtonColorClass = 'bg-red-600 hover:bg-red-700 ring-red-500 focus-visible:outline-red-500';
      break;
    case 'idle':
    default:
      testButtonText = 'Test API';
      testButtonColorClass = 'ring-cyan-600 hover:bg-cyan-700 focus-visible:outline-cyan-500';
      break;
  }

  return (
    <div className="bg-gray-800/50 ring-1 ring-white/10 rounded-xl shadow-lg p-4 sm:p-6 mb-8 flex items-center justify-between flex-wrap gap-4">
      <div className="flex items-center space-x-4">
        <StatusIcon status={status} />
        <div>
          <p className="font-semibold text-white">Status</p>
          <p className={`text-sm ${statusColor}`}>{statusText}</p>
        </div>
      </div>
      <div className="flex items-center space-x-2">
        <button
          onClick={onTestClick}
          disabled={testStatus === 'testing'}
          className={`rounded-md px-3.5 py-2 text-sm font-semibold text-white shadow-sm ring-1 ring-inset focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 transition-colors disabled:cursor-not-allowed ${testButtonColorClass}`}
        >
          {testButtonText}
        </button>
        <button
          onClick={onSettingsClick}
          className="rounded-md px-3.5 py-2 text-sm font-semibold text-white shadow-sm ring-1 ring-inset ring-gray-600 hover:bg-gray-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-gray-500 transition-colors"
        >
          Settings
        </button>
        <button
          onClick={onActionClick}
          className={`rounded-md px-3.5 py-2 text-sm font-semibold text-white shadow-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 transition-colors ${buttonColorClass}`}
        >
          {buttonText}
        </button>
      </div>
    </div>
  );
};

export default StatusDashboard;