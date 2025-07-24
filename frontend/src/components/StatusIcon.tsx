import React from 'react';

export type Status = 'connected' | 'reconnecting' | 'disconnected' | 'failed';

interface StatusIconProps {
  status: Status;
}

const StatusIcon = ({ status }: StatusIconProps) => {
    switch (status) {
        case 'connected':
            return <svg className="h-6 w-6 text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>;
        case 'reconnecting':
            return <svg className="h-6 w-6 text-yellow-400 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h5M20 20v-5h-5" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 9a9 9 0 0114.65-4.65L20 5M4 15a9 9 0 0014.65 4.65L20 19" /></svg>;
        case 'disconnected':
            return <svg className="h-6 w-6 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18.364 5.636a9 9 0 010 12.728m-12.728 0a9 9 0 010-12.728m12.728 0L5.636 18.364" /></svg>;
        case 'failed':
            return <svg className="h-6 w-6 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>;
        default:
            return null;
    }
};

export default StatusIcon;
