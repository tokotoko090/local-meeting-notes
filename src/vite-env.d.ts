/// <reference types="vite/client" />

export type BackendEvent = {
  id?: number;
  event: string;
  message?: string;
  output_dir?: string;
  duration_seconds?: number;
  mic_device?: string;
  system_device?: string;
  file?: string;
  model?: string;
  transcribe_device?: string;
  code?: number;
};

export type AudioDevice = {
  index: number;
  name: string;
  channels: number;
  sample_rate: number;
  is_loopback: boolean;
  is_input: boolean;
  kind: "mic" | "system" | "other";
};

export type UpdateCheckResult = {
  ok: boolean;
  current_version?: string;
  latest_version?: string;
  update_available?: boolean;
  release_url?: string;
  asset_name?: string;
  asset_size?: number;
  installer_path?: string;
  error?: string;
};

declare global {
  interface Window {
    meetingNotes: {
      listDevices: () => Promise<{ ok: boolean; output: string; devices: AudioDevice[]; error?: string }>;
      startRecording: (options: { model: string; transcribeDevice: string; micDeviceIndex?: number | ""; systemDeviceIndex?: number | "" }) => Promise<{ ok: boolean; error?: string }>;
      stopRecording: () => Promise<{ ok: boolean; error?: string }>;
      transcribeExisting?: (options: { outputDir: string; model: string; transcribeDevice: string }) => Promise<{ ok: boolean; output_dir?: string; error?: string }>;
      pickOutputFolder?: () => Promise<{ ok: boolean; output_dir?: string; canceled?: boolean; error?: string }>;
      openOutputFolder: (outputDir?: string) => Promise<{ ok: boolean; error?: string }>;
      copyPrompt: (outputDir?: string) => Promise<{ ok: boolean; error?: string }>;
      shutdown?: () => Promise<{ ok: boolean; error?: string }>;
      onBackendEvent: (callback: (payload: BackendEvent) => void) => () => void;
    };
  }
}
