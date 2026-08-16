"use client";

import { CheckCircle2Icon, XCircleIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { checkHealth } from "@/lib/api/client";
import { useSettings } from "@/lib/settings-store";

export default function SettingsPage() {
  const settings = useSettings();
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [health, setHealth] = useState<"unknown" | "checking" | "ok" | "down">("unknown");

  // The store rehydrates from localStorage on the client; sync the form after
  // mount so SSR markup and the first client render agree.
  useEffect(() => {
    setBaseUrl(useSettings.getState().apiBaseUrl);
    setApiKey(useSettings.getState().apiKey);
  }, []);

  const save = () => {
    settings.setApiBaseUrl(baseUrl);
    settings.setApiKey(apiKey);
    toast.success("Settings saved", {
      description: "Stored in this browser's localStorage only.",
    });
  };

  const testConnection = async () => {
    setHealth("checking");
    const ok = await checkHealth(baseUrl);
    setHealth(ok ? "ok" : "down");
  };

  return (
    <div className="canvas-panel min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-2xl space-y-6 p-6 lg:p-8">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Settings</h1>
          <p className="text-sm text-muted-foreground">
            Connection to the Pandu backend. Nothing here ever leaves this browser.
          </p>
        </div>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">API connection</CardTitle>
            <CardDescription>
              The key is sent as an <code className="font-mono text-xs">X-API-Key</code> header and
              kept in localStorage — never in cookies.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="api-base-url">API base URL</Label>
              <Input
                id="api-base-url"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="http://localhost:8000"
                autoComplete="off"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="api-key">API key</Label>
              <Input
                id="api-key"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="dev key from backend .env"
                autoComplete="off"
              />
            </div>
            <div className="flex items-center gap-2">
              <Button onClick={save}>Save</Button>
              <Button variant="outline" onClick={testConnection} disabled={health === "checking"}>
                {health === "checking" ? "Checking…" : "Test connection"}
              </Button>
              {health === "ok" ? (
                <span className="flex items-center gap-1 text-sm text-emerald-600 dark:text-emerald-500">
                  <CheckCircle2Icon className="size-4" aria-hidden /> Healthy
                </span>
              ) : health === "down" ? (
                <span className="flex items-center gap-1 text-sm text-destructive">
                  <XCircleIcon className="size-4" aria-hidden /> Unreachable
                </span>
              ) : null}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Models & providers</CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            Model selection, fallback order and pricing are configured server-side via environment
            variables (<code className="font-mono text-xs">LLM_*</code> /{" "}
            <code className="font-mono text-xs">EMBEDDING_*</code> in the backend{" "}
            <code className="font-mono text-xs">.env</code>). The dashboard reports which models
            were actually used per call.
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Quickstart</CardTitle>
          </CardHeader>
          <CardContent>
            <ol className="list-decimal space-y-2 pl-5 text-sm text-muted-foreground">
              <li>
                Start the stack: <code className="font-mono text-xs">docker compose up</code> at the
                repo root (API on port 8000).
              </li>
              <li>Paste the API key from the backend .env above and save.</li>
              <li>
                Build a corpus on the <span className="font-medium text-foreground">Documents</span>{" "}
                page — upload a few PDFs or Markdown files and wait for status{" "}
                <span className="font-medium text-foreground">Ready</span>.
              </li>
              <li>
                Ask questions in <span className="font-medium text-foreground">Chat</span>; every
                answer streams with [n] citations you can trace to the exact chunk.
              </li>
            </ol>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
