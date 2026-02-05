"use client"

import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Logo } from "@/components/Logo"
import { DeviceConfig } from "@/components/DeviceConfig"
import { SystemSettings } from "@/components/SystemSettings"
import { PasswordChange } from "@/components/PasswordChange"
import { AlertImages } from "@/components/AlertImages"
import { LogViewer } from "@/components/LogViewer"
import { useToast } from "@/components/ui/toast"
import {
  logout,
  getConfig,
  getSettings,
  getSystemInfo,
  getServiceStatus,
  restartService,
  type EnvironmentConfig,
  type SystemInfo,
  type ServiceStatus,
  type SystemSettings as SystemSettingsType
} from "@/lib/api"
import {
  LogOut,
  Monitor,
  Settings,
  Key,
  Server,
  RefreshCw,
  Loader2,
  Wifi,
  FileText,
  Image
} from "lucide-react"

type View = 'dashboard' | 'device' | 'settings' | 'password' | 'images' | 'logs';

interface DashboardProps {
  onLogout: () => void;
}

export function Dashboard({ onLogout }: DashboardProps) {
  const [view, setView] = useState<View>('dashboard');
  const [config, setConfig] = useState<EnvironmentConfig | null>(null);
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null);
  const [serviceStatus, setServiceStatus] = useState<ServiceStatus | null>(null);
  const [settings, setSettings] = useState<SystemSettingsType | null>(null);
  const [loading, setLoading] = useState(true);
  const [restarting, setRestarting] = useState(false);
  const { toast } = useToast();

  const loadData = async () => {
    try {
      const [configData, infoData, statusData, settingsData] = await Promise.all([
        getConfig(),
        getSystemInfo(),
        getServiceStatus(),
        getSettings()
      ]);
      setConfig(configData);
      setSystemInfo(infoData);
      setServiceStatus(statusData);
      setSettings(settingsData);
    } catch (err) {
      toast({
        title: "Erro ao carregar dados",
        description: err instanceof Error ? err.message : "Erro desconhecido",
        variant: "destructive"
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleLogout = async () => {
    try {
      await logout();
      onLogout();
    } catch (err) {
      toast({
        title: "Erro ao sair",
        description: err instanceof Error ? err.message : "Erro desconhecido",
        variant: "destructive"
      });
    }
  };

  const handleRestart = async () => {
    setRestarting(true);
    try {
      const result = await restartService();
      toast({
        title: result.success ? "Sucesso" : "Erro",
        description: result.message,
        variant: result.success ? "success" : "destructive"
      });
      // Reload status after a delay
      setTimeout(loadData, 2000);
    } catch (err) {
      toast({
        title: "Erro ao reiniciar",
        description: err instanceof Error ? err.message : "Erro desconhecido",
        variant: "destructive"
      });
    } finally {
      setRestarting(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (view === 'device') {
    return (
      <DeviceConfig
        initialConfig={config!}
        onBack={() => { setView('dashboard'); loadData(); }}
      />
    );
  }

  if (view === 'settings') {
    return (
      <SystemSettings onBack={() => setView('dashboard')} />
    );
  }

  if (view === 'password') {
    return (
      <PasswordChange onBack={() => setView('dashboard')} />
    );
  }

  if (view === 'images') {
    return (
      <AlertImages onBack={() => setView('dashboard')} />
    );
  }

  if (view === 'logs') {
    return (
      <LogViewer onBack={() => setView('dashboard')} />
    );
  }

  return (
    <div className="min-h-screen p-4 md:p-8">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <header className="flex items-center justify-between mb-8">
          <Logo />
          <Button variant="outline" size="sm" onClick={handleLogout}>
            <LogOut className="h-4 w-4 mr-2" />
            Sair
          </Button>
        </header>

        {/* Cards Grid */}
        <div className="grid md:grid-cols-2 gap-4">
          {/* Device Card */}
          <Card
            className="cursor-pointer hover:border-primary/50 transition-colors"
            onClick={() => setView('device')}
          >
            <CardHeader>
              <div className="flex items-center gap-3">
                <Monitor className="h-6 w-6 text-primary" />
                <CardTitle className="text-lg">Dispositivo</CardTitle>
              </div>
              <CardDescription>
                Configuração do ambiente
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-xl font-semibold">
                {config?.environment_id || "Não configurado"}
              </p>
              <p className="text-sm text-muted-foreground">
                {config?.hospital} - {config?.sector}
              </p>
            </CardContent>
          </Card>

          {/* Settings Card */}
          <Card
            className="cursor-pointer hover:border-primary/50 transition-colors"
            onClick={() => setView('settings')}
          >
            <CardHeader>
              <div className="flex items-center gap-3">
                <Settings className="h-6 w-6 text-primary" />
                <CardTitle className="text-lg">Configuracoes</CardTitle>
              </div>
              <CardDescription>
                Ajustes do sistema
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Modo desenvolvedor, deteccao, EMA...
              </p>
            </CardContent>
          </Card>

          {/* System Status Card */}
          <Card>
            <CardHeader>
              <div className="flex items-center gap-3">
                <Server className="h-6 w-6 text-primary" />
                <CardTitle className="text-lg">Sistema</CardTitle>
              </div>
              <CardDescription>
                Status do servico principal
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center gap-2">
                <div
                  className={`h-3 w-3 rounded-full ${
                    serviceStatus?.running ? "bg-green-500" : "bg-red-500"
                  }`}
                />
                <span>
                  {serviceStatus?.running ? "Online" : "Offline"}
                </span>
              </div>
              {systemInfo && (
                <div className="text-sm text-muted-foreground space-y-1">
                  <div className="flex items-center gap-2">
                    <Wifi className="h-4 w-4" />
                    <span>{systemInfo.ip_addresses[0] || "N/A"}</span>
                  </div>
                  <p>Host: {systemInfo.hostname}</p>
                </div>
              )}
              <Button
                variant="outline"
                size="sm"
                onClick={handleRestart}
                disabled={restarting}
              >
                {restarting ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Reiniciando...
                  </>
                ) : (
                  <>
                    <RefreshCw className="h-4 w-4 mr-2" />
                    Reiniciar Servico
                  </>
                )}
              </Button>
            </CardContent>
          </Card>

          {/* Password Card */}
          <Card
            className="cursor-pointer hover:border-primary/50 transition-colors"
            onClick={() => setView('password')}
          >
            <CardHeader>
              <div className="flex items-center gap-3">
                <Key className="h-6 w-6 text-primary" />
                <CardTitle className="text-lg">Seguranca</CardTitle>
              </div>
              <CardDescription>
                Alterar senha de acesso
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Clique para alterar a senha
              </p>
            </CardContent>
          </Card>

          {/* Logs Card - Always visible */}
          <Card
            className="cursor-pointer hover:border-primary/50 transition-colors"
            onClick={() => setView('logs')}
          >
            <CardHeader>
              <div className="flex items-center gap-3">
                <FileText className="h-6 w-6 text-primary" />
                <CardTitle className="text-lg">Logs</CardTitle>
              </div>
              <CardDescription>
                Historico de eventos do sistema
              </CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Visualizar alertas, transicoes e eventos
              </p>
            </CardContent>
          </Card>

          {/* Alert Images Card - Only visible when DEV_MODE is active */}
          {settings?.DEV_MODE && (
            <Card
              className="cursor-pointer hover:border-primary/50 transition-colors border-yellow-500/30"
              onClick={() => setView('images')}
            >
              <CardHeader>
                <div className="flex items-center gap-3">
                  <Image className="h-6 w-6 text-yellow-500" />
                  <CardTitle className="text-lg">Imagens DEV</CardTitle>
                </div>
                <CardDescription>
                  Capturas de alertas (modo dev)
                </CardDescription>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">
                  Imagens salvas durante alertas
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
