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
  warning_code?: string;
  detail?: string;
};

export type AudioDevice = {
  id?: string;
  is_default?: boolean;
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

export type GpuStatusResult = {
  ok: boolean;
  state?: "cpu" | "available" | "setup_available" | "setup_failed" | "setting_up";
  label?: string;
  message?: string;
  runtime_ready?: boolean;
  runtime_root?: string;
  error?: string;
};

export type SettingsResult = {
  ok: boolean;
  output_root?: string;
  default_output_root?: string;
  prompt_template?: string;
  default_prompt_template?: string;
  error?: string;
};

export type Capabilities = {
  ok: boolean;
  platform: string;
  updates: boolean;
  cuda_setup: boolean;
  transcribe_devices: string[];
  models: { id: string; label: string }[];
  default_model: string;
  permissions?: { microphone?: string; system_audio?: string; error?: string };
};

export type PromptResult = { ok: boolean; text?: string; saved?: boolean; error?: string };
