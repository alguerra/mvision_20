/**
 * API client for MVision backend
 */

const API_BASE = '/api';

export interface EnvironmentConfig {
  environment_id: string;
  hospital: string;
  sector: string;
  bed: string;
}

export interface SystemSettings {
  DEV_MODE: boolean;
  DEV_SKIP_BED_DETECTION: boolean;
  FLIP_HORIZONTAL: boolean;
  BED_RECHECK_INTERVAL_HOURS: number;
  POSE_FRAMES_TO_CONFIRM: number;
  EMA_ALPHA: number;
  EMA_THRESHOLD_ENTER_RISK: number;
  EMA_THRESHOLD_EXIT_RISK: number;
}

export interface SystemInfo {
  hostname: string;
  ip_addresses: string[];
  platform: string;
  model?: string;
}

export interface ServiceStatus {
  running: boolean;
  enabled: boolean;
  status: string;
}

async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    credentials: 'include',
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Erro desconhecido' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

// Auth
export async function login(password: string): Promise<{ success: boolean; message: string }> {
  return apiRequest('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ password }),
  });
}

export async function logout(): Promise<{ success: boolean }> {
  return apiRequest('/auth/logout', { method: 'POST' });
}

export async function checkAuth(): Promise<{ authenticated: boolean }> {
  return apiRequest('/auth/check');
}

export async function changePassword(
  currentPassword: string,
  newPassword: string
): Promise<{ success: boolean; message: string }> {
  return apiRequest('/auth/password', {
    method: 'POST',
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  });
}

// Config
export async function getConfig(): Promise<EnvironmentConfig> {
  return apiRequest('/config');
}

export async function saveConfig(config: EnvironmentConfig): Promise<{ success: boolean; message: string }> {
  return apiRequest('/config', {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

// Settings
export async function getSettings(): Promise<SystemSettings> {
  return apiRequest('/settings');
}

export async function saveSettings(settings: Partial<SystemSettings>): Promise<{ success: boolean; message: string }> {
  return apiRequest('/settings', {
    method: 'POST',
    body: JSON.stringify(settings),
  });
}

// System
export async function getSystemInfo(): Promise<SystemInfo> {
  return apiRequest('/system/info');
}

export async function getServiceStatus(): Promise<ServiceStatus> {
  return apiRequest('/system/status');
}

export async function restartService(): Promise<{ success: boolean; message: string }> {
  return apiRequest('/system/restart', { method: 'POST' });
}
