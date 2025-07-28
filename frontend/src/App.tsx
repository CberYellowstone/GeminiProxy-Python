import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { geminiExecutor } from './geminiExecutor/geminiExecutor';
import { websocketService } from './websocketService';

// Import components
import ConnectionSettings from './components/ConnectionSettings';
import EventLog from './components/EventLog';
import Footer from './components/Footer';
import Header from './components/Header';
import StatusDashboard from './components/StatusDashboard';

const CLIENT_ID_STORAGE_KEY = 'gemini-proxy-clientId';
const WEBSOCKET_URL_STORAGE_KEY = 'gemini-proxy-ws-url';
const DEFAULT_WEBSOCKET_URL = ((import.meta as any).env?.VITE_WEBSOCKET_URL) || 'ws://localhost:8000/ws';

export type TestStatus = 'idle' | 'testing' | 'success' | 'failed';

const generateNewClientId = () => {
  return `browser-${Date.now().toString(36)}-${Math.random().toString(36).substring(2, 9)}`;
};

const App = () => {
  const [clientId, setClientId] = useState('');
  const [websocketUrl, setWebsocketUrl] = useState('');
  const [isConnected, setIsConnected] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [logs, setLogs] = useState<string[]>([]);
  const [reconnectionInfo, setReconnectionInfo] = useState<{ attempt: number, max: number } | null>(null);
  const [reconnectFailed, setReconnectFailed] = useState(false);
  const [isSettingsModalOpen, setIsSettingsModalOpen] = useState(false);
  const [testStatus, setTestStatus] = useState<TestStatus>('idle');
  const testStatusTimeoutRef = useRef<number | null>(null);


  const addLog = useCallback((message: string) => {
    const timestamp = new Date().toLocaleTimeString('en-US', { hour12: false });
    setLogs((prevLogs) => [`[${timestamp}] ${message}`, ...prevLogs.slice(0, 199)]);
  }, []);
  
  const clearLogs = () => {
    setLogs([]);
  };

  const connectApp = useCallback((urlToConnect: string, idToConnect: string) => {
    if (!urlToConnect || !idToConnect) {
      addLog("Connection settings are missing. Cannot connect.");
      return;
    }
    addLog(`Initializing connection for Client ID: ${idToConnect}`);
    setIsConnecting(true);
    setReconnectFailed(false);
    setReconnectionInfo(null);

    websocketService.connect(urlToConnect, idToConnect, {
      onOpen: () => {
        setIsConnected(true);
        setIsConnecting(false);
        setReconnectionInfo(null);
        setReconnectFailed(false);
      },
      onClose: () => {
        setIsConnected(false);
        setIsConnecting(false);
      },
      onError: () => {/* UI state change handled by onClose */},
      onLog: addLog,
      onReconnecting: (attempt, max) => {
        setIsConnected(false);
        setIsConnecting(false);
        setReconnectionInfo({ attempt, max });
        setReconnectFailed(false);
      },
      onReconnectSuccess: () => addLog("Successfully reconnected to the backend."),
      onReconnectFailed: () => {
        setIsConnecting(false);
        setReconnectionInfo(null);
        setReconnectFailed(true);
      },
    });
  }, [addLog]);

  // Effect for initial setup and cleanup
  useEffect(() => {
    let storedId = localStorage.getItem(CLIENT_ID_STORAGE_KEY);
    if (!storedId) {
      storedId = generateNewClientId();
      localStorage.setItem(CLIENT_ID_STORAGE_KEY, storedId);
      addLog(`No Client ID found. Generated a new one: ${storedId}`);
    } else {
      addLog(`Found existing Client ID: ${storedId}`);
    }
    setClientId(storedId);

    let storedUrl = localStorage.getItem(WEBSOCKET_URL_STORAGE_KEY);
    if (!storedUrl) {
      storedUrl = DEFAULT_WEBSOCKET_URL;
      localStorage.setItem(WEBSOCKET_URL_STORAGE_KEY, storedUrl);
      addLog(`Using default WebSocket URL: ${storedUrl}`);
    } else {
      addLog(`Found existing WebSocket URL: ${storedUrl}`);
    }
    setWebsocketUrl(storedUrl);
    
    connectApp(storedUrl, storedId);
    
    // Cleanup timeout on component unmount
    return () => {
      if (testStatusTimeoutRef.current) {
        clearTimeout(testStatusTimeoutRef.current);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Run only once on mount

  const handleClientIdChange = (newId: string) => {
    setClientId(newId);
    localStorage.setItem(CLIENT_ID_STORAGE_KEY, newId);
  };
  
  const handleWebsocketUrlChange = (newUrl: string) => {
    setWebsocketUrl(newUrl);
    localStorage.setItem(WEBSOCKET_URL_STORAGE_KEY, newUrl);
  };

  const handleRegenerateId = () => {
    const newId = generateNewClientId();
    handleClientIdChange(newId);
    addLog(`Generated and set new Client ID: ${newId}`);
  };

  const handleManualAction = () => {
    const isConnectingOrReconnecting = isConnecting || reconnectionInfo != null;

    if (isConnectingOrReconnecting) {
        addLog("Connection attempt cancelled by user.");
        websocketService.disconnect();
        setIsConnecting(false);
        setReconnectionInfo(null);
    } else if (isConnected) {
        websocketService.disconnect();
    } else { // Disconnected or Failed
        addLog("Manual connection attempt initiated.");
        connectApp(websocketUrl, clientId);
    }
  };

  const handleTestClick = async () => {
    if (testStatusTimeoutRef.current) {
        clearTimeout(testStatusTimeoutRef.current);
    }
    addLog('Starting Gemini API test...');
    setTestStatus('testing');
    try {
      const result = await geminiExecutor.testGeminiConnection();
      addLog(`Gemini test successful. Response: "${result.trim()}"`);
      setTestStatus('success');
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      addLog(`Gemini test FAILED: ${errorMessage}`);
      setTestStatus('failed');
    } finally {
      testStatusTimeoutRef.current = window.setTimeout(() => {
        setTestStatus('idle');
        testStatusTimeoutRef.current = null;
      }, 3000);
    }
  };

  const { status, statusText, statusColor } = useMemo(() => {
    if (isConnected) {
        return { status: 'connected' as const, statusText: 'Connected', statusColor: 'text-green-400' };
    }
    if (isConnecting) {
        return { status: 'reconnecting' as const, statusText: 'Connecting...', statusColor: 'text-yellow-400' };
    }
    if (reconnectionInfo) {
        return { status: 'reconnecting' as const, statusText: `Reconnecting... (${reconnectionInfo.attempt}/${reconnectionInfo.max})`, statusColor: 'text-yellow-400' };
    }
    if (reconnectFailed) {
        return { status: 'failed' as const, statusText: 'Connection Failed', statusColor: 'text-red-500' };
    }
    return { status: 'disconnected' as const, statusText: 'Disconnected', statusColor: 'text-gray-500' };
  }, [isConnected, isConnecting, reconnectionInfo, reconnectFailed]);

  const isEditable = !isConnected && !isConnecting && !reconnectionInfo;
  
  return (
    <main className="bg-gray-900 text-white min-h-screen font-sans flex flex-col items-center p-4 sm:p-6 lg:p-8">
        <div className="w-full max-w-6xl flex flex-col flex-grow">
            <Header />

            <StatusDashboard 
                status={status}
                statusText={statusText}
                statusColor={statusColor}
                isReconnecting={isConnecting || reconnectionInfo != null}
                isConnected={isConnected}
                isFailed={reconnectFailed}
                testStatus={testStatus}
                onActionClick={handleManualAction}
                onSettingsClick={() => setIsSettingsModalOpen(true)}
                onTestClick={handleTestClick}
            />
            
            <EventLog logs={logs} onClear={clearLogs} />
            
            <Footer />
        </div>

        <ConnectionSettings
            isOpen={isSettingsModalOpen}
            onClose={() => setIsSettingsModalOpen(false)}
            clientId={clientId}
            onClientIdChange={handleClientIdChange}
            onRegenerate={handleRegenerateId}
            websocketUrl={websocketUrl}
            onWebsocketUrlChange={handleWebsocketUrlChange}
            isEditable={isEditable}
        />
    </main>
  );
};

export default App;