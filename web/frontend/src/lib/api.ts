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

// Diagnostics types
export interface AlertImage {
  filename: string;
  timestamp: string;
  state: string;
  size_kb: number;
}

export interface AlertImagesResponse {
  images: AlertImage[];
  total: number;
  dev_mode: boolean;
}

export interface LogFile {
  filename: string;
  size_kb: number;
  modified: string;
}

export interface LogFilesResponse {
  files: LogFile[];
}

export interface LogEntry {
  line_number: number;
  timestamp: string;
  level: string;
  category: string;
  details: string;
}

export interface LogsResponse {
  entries: LogEntry[];
  total_lines: number;
  file_name: string;
  available_files: string[];
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

// Diagnostics
export async function getAlertImages(): Promise<AlertImagesResponse> {
  return apiRequest('/diagnostics/images');
}

export function getAlertImageUrl(filename: string): string {
  return `${API_BASE}/diagnostics/images/${encodeURIComponent(filename)}`;
}

export async function getLogFiles(): Promise<LogFilesResponse> {
  return apiRequest('/diagnostics/logs/files');
}

export interface GetLogsParams {
  file?: string;
  level?: string;
  category?: string;
  search?: string;
  limit?: number;
  offset?: number;
}

export async function getLogs(params: GetLogsParams = {}): Promise<LogsResponse> {
  const searchParams = new URLSearchParams();
  if (params.file) searchParams.set('file', params.file);
  if (params.level) searchParams.set('level', params.level);
  if (params.category) searchParams.set('category', params.category);
  if (params.search) searchParams.set('search', params.search);
  if (params.limit !== undefined) searchParams.set('limit', params.limit.toString());
  if (params.offset !== undefined) searchParams.set('offset', params.offset.toString());

  const queryString = searchParams.toString();
  return apiRequest(`/diagnostics/logs${queryString ? `?${queryString}` : ''}`);
}
