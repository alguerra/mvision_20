"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { useToast } from "@/components/ui/toast"
import { saveConfig, type EnvironmentConfig } from "@/lib/api"
import { ArrowLeft, Save, Loader2 } from "lucide-react"

interface DeviceConfigProps {
  initialConfig: EnvironmentConfig;
  onBack: () => void;
}

export function DeviceConfig({ initialConfig, onBack }: DeviceConfigProps) {
  const [config, setConfig] = useState<EnvironmentConfig>(initialConfig);
  const [saving, setSaving] = useState(false);
  const { toast } = useToast();

  const handleChange = (field: keyof EnvironmentConfig, value: string) => {
    setConfig(prev => ({ ...prev, [field]: value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);

    try {
      const result = await saveConfig(config);
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

  return (
    <div className="min-h-screen p-4 md:p-8">
      <div className="max-w-xl mx-auto">
        <Button variant="ghost" onClick={onBack} className="mb-4">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Voltar
        </Button>

        <Card>
          <CardHeader>
            <CardTitle>Configuracao do Dispositivo</CardTitle>
            <CardDescription>
              Configure a identificacao deste equipamento
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="environment_id">ID do Ambiente</Label>
                <Input
                  id="environment_id"
                  placeholder="Ex: UTI-LEITO-01"
                  value={config.environment_id}
                  onChange={(e) => handleChange('environment_id', e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  Identificador unico deste dispositivo
                </p>
              </div>

              <div className="space-y-2">
                <Label htmlFor="hospital">Hospital</Label>
                <Input
                  id="hospital"
                  placeholder="Nome do hospital"
                  value={config.hospital}
                  onChange={(e) => handleChange('hospital', e.target.value)}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="sector">Setor</Label>
                <Input
                  id="sector"
                  placeholder="Ex: UTI, Enfermaria, Emergencia"
                  value={config.sector}
                  onChange={(e) => handleChange('sector', e.target.value)}
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="bed">Leito</Label>
                <Input
                  id="bed"
                  placeholder="Numero do leito"
                  value={config.bed}
                  onChange={(e) => handleChange('bed', e.target.value)}
                />
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
                    Salvar Configuracao
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
