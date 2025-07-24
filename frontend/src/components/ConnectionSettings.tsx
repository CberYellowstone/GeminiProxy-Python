
import React from 'react';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  clientId: string;
  onClientIdChange: (newId: string) => void;
  onRegenerate: () => void;
  websocketUrl: string;
  onWebsocketUrlChange: (newUrl: string) => void;
  isEditable: boolean;
}

const ConnectionSettings = ({
  isOpen,
  onClose,
  clientId,
  onClientIdChange,
  onRegenerate,
  websocketUrl,
  onWebsocketUrlChange,
  isEditable,
}: SettingsModalProps) => {
  if (!isOpen) {
    return null;
  }

  return (
    <div 
      className="relative z-10" 
      aria-labelledby="modal-title" 
      role="dialog" 
      aria-modal="true"
    >
      <div 
        className="fixed inset-0 bg-gray-900 bg-opacity-75 transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      ></div>

      <div className="fixed inset-0 z-10 w-screen overflow-y-auto">
        <div className="flex min-h-full items-end justify-center p-4 text-center sm:items-center sm:p-0">
          <div className="relative transform overflow-hidden rounded-xl bg-gray-800 text-left shadow-2xl ring-1 ring-white/10 transition-all sm:my-8 sm:w-full sm:max-w-lg">
            <div className="bg-gray-800 p-4 sm:p-6">
              <div className="sm:flex sm:items-start">
                <div className="w-full text-center sm:text-left">
                  <h3 className="text-lg font-semibold leading-6 text-white" id="modal-title">
                    Connection Settings
                  </h3>
                  <p className="mt-1 text-sm text-gray-400">
                    Changes are saved automatically. Disconnect to edit.
                  </p>
                </div>
              </div>

              <div className="mt-6 space-y-6">
                {/* WebSocket URL Section */}
                <div>
                  <label htmlFor="modalWebsocketUrl" className="block text-sm font-medium leading-6 text-gray-300">
                    WebSocket URL
                  </label>
                  <div className="mt-2">
                    <input
                      type="text"
                      name="modalWebsocketUrl"
                      id="modalWebsocketUrl"
                      value={websocketUrl}
                      onChange={(e) => onWebsocketUrlChange(e.target.value)}
                      disabled={!isEditable}
                      className="block w-full rounded-md border-0 bg-white/5 py-2 px-3 text-white ring-1 ring-inset ring-white/10 focus:ring-2 focus:ring-inset focus:ring-indigo-500 sm:text-sm sm:leading-6 placeholder:text-gray-400 disabled:cursor-not-allowed disabled:bg-gray-700/50 disabled:text-gray-400 transition-colors"
                      placeholder="e.g., ws://localhost:8000/ws"
                      aria-label="WebSocket URL"
                    />
                  </div>
                </div>

                {/* Client ID Section */}
                <div>
                  <label htmlFor="modalClientId" className="block text-sm font-medium leading-6 text-gray-300">
                    Client ID
                  </label>
                  <div className="mt-2 flex rounded-md shadow-sm">
                    <input
                      type="text"
                      name="modalClientId"
                      id="modalClientId"
                      value={clientId}
                      onChange={(e) => onClientIdChange(e.target.value)}
                      disabled={!isEditable}
                      className="block w-full min-w-0 flex-1 rounded-none rounded-l-md border-0 bg-white/5 py-2 px-3 text-white ring-1 ring-inset ring-white/10 focus:ring-2 focus:ring-inset focus:ring-indigo-500 sm:text-sm sm:leading-6 placeholder:text-gray-400 disabled:cursor-not-allowed disabled:bg-gray-700/50 disabled:text-gray-400 transition-colors"
                      placeholder="Enter your client ID"
                      aria-label="Client ID"
                    />
                    <button
                      type="button"
                      onClick={onRegenerate}
                      disabled={!isEditable}
                      className="relative -ml-px inline-flex items-center gap-x-1.5 rounded-r-md px-3 py-2 text-sm font-semibold text-gray-200 ring-1 ring-inset ring-white/10 hover:bg-gray-700 disabled:cursor-not-allowed disabled:bg-gray-700/50 disabled:text-gray-400 transition-colors"
                      aria-label="Regenerate Client ID"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5" aria-hidden="true">
                        <path fillRule="evenodd" d="M15.312 11.424a5.5 5.5 0 0 1-9.458 2.152l.662-.661a4.5 4.5 0 0 0 7.625-1.76l.661.662.01-.01Zm-10.624-2.848a5.5 5.5 0 0 1 9.458-2.152l-.662.661a4.5 4.5 0 0 0-7.625 1.76l-.661-.662-.01.01Zm.104 3.052.662-.661a4.5 4.5 0 0 0-1.76-7.625l-.661.662-3.053 3.053.01.01a5.5 5.5 0 0 1 4.802 4.56Zm9.458-3.052-.662.661a4.5 4.5 0 0 0 1.76 7.625l.661-.662 3.053-3.053-.01-.01a5.5 5.5 0 0 1-4.802-4.56Z" clipRule="evenodd" />
                      </svg>
                      Regenerate
                    </button>
                  </div>
                </div>
              </div>
            </div>
            <div className="bg-gray-800/50 px-4 py-3 sm:flex sm:flex-row-reverse sm:px-6">
              <button
                type="button"
                className="inline-flex w-full justify-center rounded-md bg-indigo-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-indigo-500 sm:ml-3 sm:w-auto transition-colors"
                onClick={onClose}
              >
                Done
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ConnectionSettings;
