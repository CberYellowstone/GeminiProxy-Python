import { useEffect, useState } from 'react';
import './App.css';
import LogViewer from './components/LogViewer';
import StatusDisplay from './components/StatusDisplay';
import webSocketService from './services/webSocketService';

// Define a more specific type for the log entries
type LogEntry = {
  level: 'info' | 'warn' | 'error' | 'sent' | 'received';
  message: string;
  timestamp: Date;
};

function App() {
  const [status, setStatus] = useState<string>('Connecting...');
  const [clientId, setClientId] = useState<string>('');
  const [logs, setLogs] = useState<LogEntry[]>([]);

  useEffect(() => {
    // Set client ID immediately from the service instance
    setClientId(webSocketService.getClientId());

    // Define handlers with proper types
    const handleStatusChange = (event: Event) => {
        const customEvent = event as CustomEvent<string>;
        setStatus(customEvent.detail);
    };

    const handleLog = (event: Event) => {
        const customEvent = event as CustomEvent<LogEntry>;
        setLogs(prevLogs => [...prevLogs, customEvent.detail]);
    };

    // Add event listeners
    webSocketService.addEventListener('statusChange', handleStatusChange);
    webSocketService.addEventListener('log', handleLog);

    // Cleanup function to remove listeners on component unmount
    return () => {
        webSocketService.removeEventListener('statusChange', handleStatusChange);
        webSocketService.removeEventListener('log', handleLog);
    };
  }, []); // Empty dependency array ensures this runs only once on mount

  // Format logs for display
  const formattedLogs = logs.map((log: LogEntry) => 
    `${log.timestamp.toLocaleTimeString()} [${log.level.toUpperCase()}] ${log.message}`
  );

  return (
    <div className="bg-gray-900 text-white min-h-screen font-mono">
      <div className="container mx-auto p-4">
        <h1 className="text-3xl font-bold mb-4">Gemini Proxy Frontend</h1>
        <StatusDisplay status={status} clientId={clientId} />
        <LogViewer logs={formattedLogs} />
      </div>
    </div>
  );
}

export default App;