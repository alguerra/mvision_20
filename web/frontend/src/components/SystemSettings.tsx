"use client"

import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { useToast } from "@/components/ui/toast"
import { getSettings, saveSettings, type SystemSettings as SystemSettingsType } from "@/lib/api"
import { ArrowLeft, Save, Loader2 } from "lucide-react"

interface SystemSettingsProps {
  onBack: () => void;
}

export function SystemSettings({ onBack }: SystemSettingsProps) {
  const [settings, setSettings] = useState<SystemSettingsType | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const { toast } = useToast();

  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      const data = await getSettings();
      setSettings(data);
    } catch (err) {
      toast({
        title: "Erro ao carregar",
        description: err instanceof Error ? err.message : "Erro desconhecido",
        variant: "destructive"
      });
    } finally {
      setLoading(false);
    }
  };

  const handleBoolChange = (field: keyof SystemSettingsType, value: boolean) => {
    if (settings) {
      setSettings({ ...settings, [field]: value });
    }
  };

  const handleNumberChange = (field: keyof SystemSettingsType, value: string) => {
    if (settings) {
      const numValue = parseFloat(value);
      if (!isNaN(numValue)) {
        setSettings({ ...settings, [field]: numValue });
      }
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!settings) return;

    setSaving(true);
    try {
      const result = await saveSettings(settings);
      toast({
        title: "Sucesso",
        description: result.message,
        variant: "success"
      });
    } catch (err) {
      toast({
        title: "Erro ao salvar",
        description: err instanceof Error ? err.message : "Erro desconhecido",
        variant: "destructive"
      });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!settings) {
    return (
      <div className="min-h-screen p-4 md:p-8">
        <div className="max-w-xl mx-auto">
          <Button variant="ghost" onClick={onBack} className="mb-4">
            <ArrowLeft className="h-4 w-4 mr-2" />
            Voltar
          </Button>
          <p className="text-center text-muted-foreground">
            Erro ao carregar configuracoes
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen p-4 md:p-8">
      <div className="max-w-xl mx-auto">
        <Button variant="ghost" onClick={onBack} className="mb-4">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Voltar
        </Button>

        <Card>
          <CardHeader>
            <CardTitle>Configuracoes do Sistema</CardTitle>
            <CardDescription>
              Ajustes avancados do monitoramento
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-6">
              {/* Boolean Settings */}
              <div className="space-y-4">
                <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
                  Modo de Operacao
                </h3>

                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label>Modo Desenvolvedor</Label>
                    <p className="text-xs text-muted-foreground">
                      Salva imagens de alerta para debug
                    </p>
                  </div>
                  <Switch
                    checked={settings.DEV_MODE}
                    onCheckedChange={(checked) => handleBoolChange('DEV_MODE', checked)}
                  />
                </div>

                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label>Pular Deteccao de Leito</Label>
                    <p className="text-xs text-muted-foreground">
                      Ignora calibracao de leito
                    </p>
                  </div>
                  <Switch
                    checked={settings.DEV_SKIP_BED_DETECTION}
                    onCheckedChange={(checked) => handleBoolChange('DEV_SKIP_BED_DETECTION', checked)}
                  />
                </div>

                <div className="flex items-center justify-between">
                  <div className="space-y-0.5">
                    <Label>Espelhar Imagem</Label>
                    <p className="text-xs text-muted-foreground">
                      Inverte a imagem horizontalmente
                    </p>
                  </div>
                  <Switch
                    checked={settings.FLIP_HORIZONTAL}
                    onCheckedChange={(checked) => handleBoolChange('FLIP_HORIZONTAL', checked)}
                  />
                </div>
              </div>

              {/* Numeric Settings */}
              <div className="space-y-4">
                <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
                  Parametros de Deteccao
                </h3>

                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="bed_recheck">Verificar Leito (horas)</Label>
                    <Input
                      id="bed_recheck"
                      type="number"
                      min="1"
                      value={settings.BED_RECHECK_INTERVAL_HOURS}
                      onChange={(e) => handleNumberChange('BED_RECHECK_INTERVAL_HOURS', e.target.value)}
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="pose_frames">Frames p/ Confirmar</Label>
                    <Input
                      id="pose_frames"
                      type="number"
                      min="1"
                      value={settings.POSE_FRAMES_TO_CONFIRM}
                      onChange={(e) => handleNumberChange('POSE_FRAMES_TO_CONFIRM', e.target.value)}
                    />
                  </div>
                </div>
              </div>

              {/* EMA Settings */}
              <div className="space-y-4">
                <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
                  Suavizacao (EMA)
                </h3>

                <div className="grid grid-cols-3 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="ema_alpha">Alpha</Label>
                    <Input
                      id="ema_alpha"
                      type="number"
                      step="0.1"
                      min="0"
                      max="1"
                      value={settings.EMA_ALPHA}
                      onChange={(e) => handleNumberChange('EMA_ALPHA', e.target.value)}
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="ema_enter">Entrar Risco</Label>
                    <Input
                      id="ema_enter"
                      type="number"
                      step="0.1"
                      min="0"
                      max="1"
                      value={settings.EMA_THRESHOLD_ENTER_RISK}
                      onChange={(e) => handleNumberChange('EMA_THRESHOLD_ENTER_RISK', e.target.value)}
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="ema_exit">Sair Risco</Label>
                    <Input
                      id="ema_exit"
                      type="number"
                      step="0.1"
                      min="0"
                      max="1"
                      value={settings.EMA_THRESHOLD_EXIT_RISK}
                      onChange={(e) => handleNumberChange('EMA_THRESHOLD_EXIT_RISK', e.target.value)}
                    />
                  </div>
                </div>
              </div>

              <Button type="submit" className="w-full" disabled={saving}>
                {saving ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Salvando...
                  </>
                ) : (
                  <>
                    <Save className="h-4 w-4 mr-2" />
                    Salvar Configuracoes
                  </>
                )}
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
