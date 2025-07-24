import React from 'react';

interface ClientIdManagerProps {
  clientId: string;
  onClientIdChange: (newId: string) => void;
  onRegenerate: () => void;
  isEditable: boolean;
}

const ClientIdManager = ({ clientId, onClientIdChange, onRegenerate, isEditable }: ClientIdManagerProps) => {
  return (
    <div className="bg-gray-800/50 ring-1 ring-white/10 rounded-xl shadow-lg p-4 sm:p-6 mb-8">
      <label htmlFor="clientId" className="block text-sm font-medium leading-6 text-gray-300">
        Client ID
      </label>
      <div className="mt-2 flex rounded-md shadow-sm">
        <input
          type="text"
          name="clientId"
          id="clientId"
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
      <p className="mt-2 text-xs text-gray-500">
        This ID uniquely identifies this browser tab to the backend. Changes are saved automatically.
        {!isEditable && " Disconnect to edit."}
      </p>
    </div>
  );
};

export default ClientIdManager;
