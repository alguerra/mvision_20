"use client"

import { useState, useEffect } from "react"
import { LoginForm } from "@/components/LoginForm"
import { Dashboard } from "@/components/Dashboard"
import { ToastProvider } from "@/components/ui/toast"
import { checkAuth } from "@/lib/api"
import { Loader2 } from "lucide-react"

export default function Home() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);

  useEffect(() => {
    checkAuth()
      .then(({ authenticated }) => setAuthenticated(authenticated))
      .catch(() => setAuthenticated(false));
  }, []);

  // Loading state
  if (authenticated === null) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <ToastProvider>
      {authenticated ? (
        <Dashboard onLogout={() => setAuthenticated(false)} />
      ) : (
        <LoginForm onSuccess={() => setAuthenticated(true)} />
      )}
    </ToastProvider>
  );
}
