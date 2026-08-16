"use client";

import { useQuery } from "@tanstack/react-query";
import { FileTextIcon, GaugeIcon, MessagesSquareIcon, SettingsIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { ThemeToggle } from "@/components/theme-toggle";
import { checkHealth } from "@/lib/api/client";
import { useSettings } from "@/lib/settings-store";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Chat", icon: MessagesSquareIcon },
  { href: "/documents", label: "Documents", icon: FileTextIcon },
  { href: "/dashboard", label: "Dashboard", icon: GaugeIcon },
  { href: "/settings", label: "Settings", icon: SettingsIcon },
] as const;

function apiHost(baseUrl: string): string {
  try {
    return new URL(baseUrl).host;
  } catch {
    return baseUrl;
  }
}

/**
 * Honest analogue of the reference's bottom sidebar card: live backend
 * reachability (same /health check as Settings) plus the API host.
 */
function ConnectionCard() {
  const apiBaseUrl = useSettings((s) => s.apiBaseUrl);
  // The settings store rehydrates from localStorage on the client; wait for
  // mount so SSR markup and the first client render agree.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const health = useQuery({
    queryKey: ["health", apiBaseUrl],
    queryFn: () => checkHealth(apiBaseUrl),
    enabled: mounted,
    refetchInterval: 30_000,
    retry: false,
  });
  const status = !mounted || health.isPending ? "checking" : health.data ? "ok" : "down";
  const label =
    status === "ok" ? "API connected" : status === "down" ? "API unreachable" : "Checking API…";

  return (
    <div
      className="rounded-xl bg-chrome-elevated/60 p-3 max-lg:flex max-lg:justify-center max-lg:bg-transparent max-lg:p-2"
      title={label}
    >
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "size-2 shrink-0 rounded-full",
            status === "ok" && "bg-emerald-400",
            status === "down" && "bg-red-400",
            status === "checking" && "animate-pulse bg-chrome-muted",
          )}
          aria-hidden
        />
        <span className="truncate text-xs font-medium text-chrome-foreground max-lg:hidden">
          {label}
        </span>
      </div>
      <p className="mt-1 truncate font-mono text-[0.65rem] text-chrome-muted max-lg:hidden">
        {mounted ? apiHost(apiBaseUrl) : "…"}
      </p>
    </div>
  );
}

/** Persistent dark left rail: brand, nav pills, connection status. */
export function AppSidebar() {
  const pathname = usePathname();

  return (
    <aside className="flex w-[4.25rem] shrink-0 flex-col gap-3 p-3 lg:w-56 lg:p-4">
      <div className="flex items-center gap-2.5 pb-1 max-lg:justify-center">
        <Link href="/" className="flex min-w-0 flex-1 items-center gap-2.5 max-lg:flex-none">
          <span
            className="brand-gradient flex size-8 shrink-0 items-center justify-center rounded-xl text-sm font-semibold text-white shadow-sm"
            aria-hidden
          >
            P
          </span>
          <span className="truncate font-semibold tracking-tight text-chrome-foreground max-lg:hidden">
            Pandu
          </span>
        </Link>
        <ThemeToggle className="text-chrome-muted hover:bg-chrome-elevated hover:text-chrome-foreground max-lg:hidden" />
      </div>

      <nav aria-label="Main" className="flex flex-1 flex-col gap-1">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors max-lg:justify-center max-lg:px-0",
                active
                  ? "bg-chrome-elevated text-chrome-foreground"
                  : "text-chrome-muted hover:bg-chrome-elevated/50 hover:text-chrome-foreground",
              )}
            >
              <Icon className="size-4 shrink-0" aria-hidden />
              <span className="max-lg:hidden">{label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="flex justify-center lg:hidden">
        <ThemeToggle className="text-chrome-muted hover:bg-chrome-elevated hover:text-chrome-foreground" />
      </div>
      <ConnectionCard />
    </aside>
  );
}
