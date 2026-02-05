"use client"

import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { useToast } from "@/components/ui/toast"
import {
  getAlertImages,
  getAlertImageUrl,
  type AlertImage,
} from "@/lib/api"
import { ArrowLeft, Loader2, Image as ImageIcon, X, AlertTriangle, AlertCircle } from "lucide-react"

interface AlertImagesProps {
  onBack: () => void;
}

export function AlertImages({ onBack }: AlertImagesProps) {
  const [images, setImages] = useState<AlertImage[]>([]);
  const [devMode, setDevMode] = useState(true);
  const [loading, setLoading] = useState(true);
  const [selectedImage, setSelectedImage] = useState<AlertImage | null>(null);
  const { toast } = useToast();

  useEffect(() => {
    loadImages();
  }, []);

  const loadImages = async () => {
    try {
      const data = await getAlertImages();
      setImages(data.images);
      setDevMode(data.dev_mode);
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

  const formatTimestamp = (timestamp: string) => {
    // Format: 20240115_143022 -> 15/01/2024 14:30:22
    const match = timestamp.match(/(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/);
    if (match) {
      const [, year, month, day, hour, min, sec] = match;
      return `${day}/${month}/${year} ${hour}:${min}:${sec}`;
    }
    return timestamp;
  };

  const getStateBadge = (state: string) => {
    if (state === "RISCO_POTENCIAL") {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200">
          <AlertTriangle className="h-3 w-3" />
          Risco Potencial
        </span>
      );
    }
    if (state === "PACIENTE_FORA") {
      return (
        <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200">
          <AlertCircle className="h-3 w-3" />
          Paciente Fora
        </span>
      );
    }
    return (
      <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-200">
        {state}
      </span>
    );
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!devMode) {
    return (
      <div className="min-h-screen p-4 md:p-8">
        <div className="max-w-4xl mx-auto">
          <Button variant="ghost" onClick={onBack} className="mb-4">
            <ArrowLeft className="h-4 w-4 mr-2" />
            Voltar
          </Button>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ImageIcon className="h-5 w-5" />
                Imagens de Alerta
              </CardTitle>
              <CardDescription>
                Capturas de tela em momentos de alerta
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="text-center py-8">
                <AlertTriangle className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
                <p className="text-lg font-medium">DEV_MODE Desabilitado</p>
                <p className="text-sm text-muted-foreground mt-2">
                  As imagens de alerta so sao capturadas quando o modo desenvolvedor esta ativo.
                </p>
                <p className="text-sm text-muted-foreground">
                  Ative DEV_MODE nas configuracoes para habilitar esta funcionalidade.
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen p-4 md:p-8">
      <div className="max-w-6xl mx-auto">
        <Button variant="ghost" onClick={onBack} className="mb-4">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Voltar
        </Button>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ImageIcon className="h-5 w-5" />
              Imagens de Alerta
            </CardTitle>
            <CardDescription>
              {images.length} imagens capturadas (maximo: 50)
            </CardDescription>
          </CardHeader>
          <CardContent>
            {images.length === 0 ? (
              <div className="text-center py-8">
                <ImageIcon className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
                <p className="text-muted-foreground">Nenhuma imagem de alerta capturada</p>
              </div>
            ) : (
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                {images.map((image) => (
                  <div
                    key={image.filename}
                    className="group relative aspect-video bg-muted rounded-lg overflow-hidden cursor-pointer hover:ring-2 hover:ring-primary transition-all"
                    onClick={() => setSelectedImage(image)}
                  >
                    <img
                      src={getAlertImageUrl(image.filename)}
                      alt={`Alerta ${image.state}`}
                      className="w-full h-full object-cover"
                      loading="lazy"
                    />
                    <div className="absolute inset-0 bg-gradient-to-t from-black/60 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
                    <div className="absolute bottom-0 left-0 right-0 p-2">
                      {getStateBadge(image.state)}
                      <p className="text-xs text-white/80 mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        {formatTimestamp(image.timestamp)}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Modal for enlarged image */}
        {selectedImage && (
          <div
            className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
            onClick={() => setSelectedImage(null)}
          >
            <div
              className="relative max-w-4xl w-full bg-background rounded-lg overflow-hidden"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="absolute top-2 right-2 z-10">
                <Button
                  variant="ghost"
                  size="sm"
                  className="bg-black/50 hover:bg-black/70 text-white"
                  onClick={() => setSelectedImage(null)}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>
              <img
                src={getAlertImageUrl(selectedImage.filename)}
                alt={`Alerta ${selectedImage.state}`}
                className="w-full h-auto"
              />
              <div className="p-4 bg-background">
                <div className="flex items-center justify-between">
                  {getStateBadge(selectedImage.state)}
                  <span className="text-sm text-muted-foreground">
                    {formatTimestamp(selectedImage.timestamp)}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground mt-2">
                  {selectedImage.filename} ({selectedImage.size_kb} KB)
                </p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
