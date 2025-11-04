import { useEffect, useRef } from 'react';

const getLogColor = (log: string): string => {
  const lowerLog = log.toLowerCase();
  if (lowerLog.includes('error') || lowerLog.includes('failed')) return 'text-red-400';
  if (lowerLog.includes('established') || lowerLog.includes('reconnected') || lowerLog.includes('successfully executed')) return 'text-green-400';
  if (lowerLog.includes('command:')) return 'text-cyan-400';
  if (lowerLog.includes('reconnecting') || lowerLog.includes('lost')) return 'text-yellow-400';
  if (lowerLog.includes('connecting to') || lowerLog.includes('closed by user')) return 'text-blue-400';
  return 'text-gray-400';
};

interface EventLogProps {
  logs: string[];
  onClear: () => void;
}

const EventLog = ({ logs, onClear }: EventLogProps) => {
  const logContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = 0;
    }
  }, [logs]);

  return (
    <div className="bg-gray-800/50 ring-1 ring-white/10 rounded-xl shadow-lg flex-grow flex flex-col min-h-0">
      <div className="flex items-center justify-between px-4 py-2 border-b border-white/10 flex-shrink-0">
        <div className="flex items-center space-x-2">
          <div className="w-3 h-3 bg-red-500 rounded-full"></div>
          <div className="w-3 h-3 bg-yellow-500 rounded-full"></div>
          <div className="w-3 h-3 bg-green-500 rounded-full"></div>
        </div>
        <p className="text-sm font-medium text-gray-300">Live Event Log</p>
        <button 
          onClick={onClear} 
          className="text-xs text-gray-400 hover:text-white transition-colors"
          aria-label="Clear logs"
        >
          Clear
        </button>
      </div>
      
      <div ref={logContainerRef} className="p-4 overflow-y-auto font-mono text-sm flex-grow">
        {logs.length === 0 ? (
          <p className="text-gray-500">Awaiting events...</p>
        ) : (
          logs.map((log, index) => (
            <p key={index} className={getLogColor(log)}>
              {log}
            </p>
          ))
        )}
      </div>
    </div>
  );
};

export default EventLog;
