"use client"

import { useState, useEffect, useCallback } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { useToast } from "@/components/ui/toast"
import {
  getLogs,
  getLogFiles,
  type LogEntry,
  type LogFile,
} from "@/lib/api"
import {
  ArrowLeft,
  Loader2,
  FileText,
  Search,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Filter,
  X
} from "lucide-react"

interface LogViewerProps {
  onBack: () => void;
}

const ENTRIES_PER_PAGE = 50;

export function LogViewer({ onBack }: LogViewerProps) {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [logFiles, setLogFiles] = useState<LogFile[]>([]);
  const [totalLines, setTotalLines] = useState(0);
  const [loading, setLoading] = useState(true);
  const [selectedFile, setSelectedFile] = useState("alerts.log");
  const [levelFilter, setLevelFilter] = useState<string>("");
  const [categoryFilter, setCategoryFilter] = useState<string>("");
  const [searchText, setSearchText] = useState("");
  const [currentPage, setCurrentPage] = useState(0);
  const [showFilters, setShowFilters] = useState(false);
  const { toast } = useToast();

  const loadLogs = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getLogs({
        file: selectedFile,
        level: levelFilter || undefined,
        category: categoryFilter || undefined,
        search: searchText || undefined,
        limit: ENTRIES_PER_PAGE,
        offset: currentPage * ENTRIES_PER_PAGE,
      });
      setEntries(data.entries);
      setTotalLines(data.total_lines);
    } catch (err) {
      toast({
        title: "Erro ao carregar logs",
        description: err instanceof Error ? err.message : "Erro desconhecido",
        variant: "destructive"
      });
    } finally {
      setLoading(false);
    }
  }, [selectedFile, levelFilter, categoryFilter, searchText, currentPage, toast]);

  const loadLogFiles = async () => {
    try {
      const data = await getLogFiles();
      setLogFiles(data.files);
    } catch (err) {
      // Silently fail, not critical
    }
  };

  useEffect(() => {
    loadLogFiles();
  }, []);

  useEffect(() => {
    loadLogs();
  }, [loadLogs]);

  const handleFileChange = (file: string) => {
    setSelectedFile(file);
    setCurrentPage(0);
  };

  const handleSearch = () => {
    setCurrentPage(0);
    loadLogs();
  };

  const clearFilters = () => {
    setLevelFilter("");
    setCategoryFilter("");
    setSearchText("");
    setCurrentPage(0);
  };

  const totalPages = Math.ceil(totalLines / ENTRIES_PER_PAGE);

  const getLevelBadge = (level: string) => {
    switch (level) {
      case "ERROR":
        return (
          <span className="inline-flex px-2 py-0.5 rounded text-xs font-medium bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200">
            ERROR
          </span>
        );
      case "WARNING":
        return (
          <span className="inline-flex px-2 py-0.5 rounded text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200">
            WARNING
          </span>
        );
      default:
        return (
          <span className="inline-flex px-2 py-0.5 rounded text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">
            INFO
          </span>
        );
    }
  };

  const getCategoryBadge = (category: string) => {
    switch (category) {
      case "ALERTA":
        return (
          <span className="inline-flex px-2 py-0.5 rounded text-xs font-medium bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300">
            ALERTA
          </span>
        );
      case "TRANSICAO":
        return (
          <span className="inline-flex px-2 py-0.5 rounded text-xs font-medium bg-purple-50 text-purple-700 dark:bg-purple-950 dark:text-purple-300">
            TRANSICAO
          </span>
        );
      case "SISTEMA":
        return (
          <span className="inline-flex px-2 py-0.5 rounded text-xs font-medium bg-green-50 text-green-700 dark:bg-green-950 dark:text-green-300">
            SISTEMA
          </span>
        );
      default:
        return (
          <span className="inline-flex px-2 py-0.5 rounded text-xs font-medium bg-gray-50 text-gray-700 dark:bg-gray-900 dark:text-gray-300">
            {category}
          </span>
        );
    }
  };

  return (
    <div className="min-h-screen p-4 md:p-8">
      <div className="max-w-6xl mx-auto">
        <Button variant="ghost" onClick={onBack} className="mb-4">
          <ArrowLeft className="h-4 w-4 mr-2" />
          Voltar
        </Button>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="flex items-center gap-2">
                  <FileText className="h-5 w-5" />
                  Logs do Sistema
                </CardTitle>
                <CardDescription>
                  {totalLines} entradas encontradas
                </CardDescription>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowFilters(!showFilters)}
                >
                  <Filter className="h-4 w-4 mr-2" />
                  Filtros
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={loadLogs}
                  disabled={loading}
                >
                  <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* File selector */}
            <div className="flex flex-wrap gap-2">
              {logFiles.length > 0 ? (
                logFiles.map((file) => (
                  <Button
                    key={file.filename}
                    variant={selectedFile === file.filename ? "default" : "outline"}
                    size="sm"
                    onClick={() => handleFileChange(file.filename)}
                  >
                    {file.filename}
                    <span className="ml-2 text-xs opacity-70">
                      ({file.size_kb} KB)
                    </span>
                  </Button>
                ))
              ) : (
                <Button
                  variant="default"
                  size="sm"
                  disabled
                >
                  alerts.log
                </Button>
              )}
            </div>

            {/* Filters */}
            {showFilters && (
              <div className="p-4 bg-muted/50 rounded-lg space-y-3">
                <div className="flex flex-wrap gap-3">
                  <div className="flex-1 min-w-[200px]">
                    <label className="text-xs text-muted-foreground mb-1 block">Buscar</label>
                    <div className="flex gap-2">
                      <Input
                        placeholder="Texto livre..."
                        value={searchText}
                        onChange={(e) => setSearchText(e.target.value)}
                        onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                        className="flex-1"
                      />
                      <Button size="sm" onClick={handleSearch}>
                        <Search className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>

                  <div className="w-32">
                    <label className="text-xs text-muted-foreground mb-1 block">Nivel</label>
                    <select
                      className="w-full h-9 px-3 rounded-md border border-input bg-background text-sm"
                      value={levelFilter}
                      onChange={(e) => { setLevelFilter(e.target.value); setCurrentPage(0); }}
                    >
                      <option value="">Todos</option>
                      <option value="INFO">INFO</option>
                      <option value="WARNING">WARNING</option>
                      <option value="ERROR">ERROR</option>
                    </select>
                  </div>

                  <div className="w-32">
                    <label className="text-xs text-muted-foreground mb-1 block">Categoria</label>
                    <select
                      className="w-full h-9 px-3 rounded-md border border-input bg-background text-sm"
                      value={categoryFilter}
                      onChange={(e) => { setCategoryFilter(e.target.value); setCurrentPage(0); }}
                    >
                      <option value="">Todas</option>
                      <option value="SISTEMA">SISTEMA</option>
                      <option value="TRANSICAO">TRANSICAO</option>
                      <option value="ALERTA">ALERTA</option>
                    </select>
                  </div>
                </div>

                {(levelFilter || categoryFilter || searchText) && (
                  <Button variant="ghost" size="sm" onClick={clearFilters}>
                    <X className="h-4 w-4 mr-2" />
                    Limpar filtros
                  </Button>
                )}
              </div>
            )}

            {/* Log entries */}
            {loading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
              </div>
            ) : entries.length === 0 ? (
              <div className="text-center py-12">
                <FileText className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
                <p className="text-muted-foreground">Nenhuma entrada encontrada</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b">
                      <th className="text-left py-2 px-2 font-medium text-muted-foreground w-8">#</th>
                      <th className="text-left py-2 px-2 font-medium text-muted-foreground w-40">Timestamp</th>
                      <th className="text-left py-2 px-2 font-medium text-muted-foreground w-20">Nivel</th>
                      <th className="text-left py-2 px-2 font-medium text-muted-foreground w-28">Categoria</th>
                      <th className="text-left py-2 px-2 font-medium text-muted-foreground">Detalhes</th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((entry) => (
                      <tr key={entry.line_number} className="border-b hover:bg-muted/50">
                        <td className="py-2 px-2 text-muted-foreground font-mono text-xs">
                          {entry.line_number}
                        </td>
                        <td className="py-2 px-2 font-mono text-xs whitespace-nowrap">
                          {entry.timestamp || "-"}
                        </td>
                        <td className="py-2 px-2">
                          {getLevelBadge(entry.level)}
                        </td>
                        <td className="py-2 px-2">
                          {getCategoryBadge(entry.category)}
                        </td>
                        <td className="py-2 px-2 font-mono text-xs break-all">
                          {entry.details}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between pt-4 border-t">
                <p className="text-sm text-muted-foreground">
                  Pagina {currentPage + 1} de {totalPages}
                </p>
                <div className="flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setCurrentPage(p => Math.max(0, p - 1))}
                    disabled={currentPage === 0 || loading}
                  >
                    <ChevronLeft className="h-4 w-4" />
                    Anterior
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setCurrentPage(p => Math.min(totalPages - 1, p + 1))}
                    disabled={currentPage >= totalPages - 1 || loading}
                  >
                    Proximo
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
