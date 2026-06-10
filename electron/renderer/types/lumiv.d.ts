interface BackendState {
  phase: string;
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
  payload?: any;
}

interface ElectronAPI {
  onBackendState?: (cb: (s: BackendState) => void) => void;
  onBackendStatus?: (cb: (s: {connected: boolean}) => void) => void;
  getBackendUrl?: () => Promise<string>;
  setClickThrough?: (e: boolean) => void;
  quitApp?: () => void;
}
