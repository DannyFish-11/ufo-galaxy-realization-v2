// Lumiv 共享类型定义

interface BackendState {
  phase: 'silent' | 'liminal' | 'manifest';
  intent: number;
  speaking: boolean;
  activeTask: string | null;
  taskProgress: number;
}

interface AmbientTickPayload {
  phase?: string;
  intent?: number;
  speaking?: boolean;
  depth_factor?: number;
  active_task?: string;
  task_progress?: number;
}

interface WSMessage {
  type: string;
  event_category?: string;
  event_action?: string;
  payload?: AmbientTickPayload | any;
}

interface ElectronAPI {
  onBackendState?: (callback: (state: BackendState) => void) => void;
  onBackendStatus?: (callback: (status: {connected: boolean}) => void) => void;
  onDisplayChanged?: (callback: (info: {width: number; height: number; scaleFactor: number}) => void) => void;
  onDevTogglePhase?: (callback: () => void) => void;
  getBackendUrl?: () => Promise<string>;
  setClickThrough?: (enable: boolean) => void;
  quitApp?: () => void;
  platform?: string;
}

declare global {
  interface Window {
    lumivAPI?: ElectronAPI;
    lumivApp?: any;
  }
}
