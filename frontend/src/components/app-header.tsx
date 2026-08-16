"use client";

import { FileTextIcon, GaugeIcon, MessagesSquareIcon, SettingsIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ThemeToggle } from "@/components/theme-toggle";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Chat", icon: MessagesSquareIcon },
  { href: "/documents", label: "Documents", icon: FileTextIcon },
  { href: "/dashboard", label: "Dashboard", icon: GaugeIcon },
  { href: "/settings", label: "Settings", icon: SettingsIcon },
] as const;

export function AppHeader() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-40 flex h-14 items-center gap-6 border-b bg-background/95 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/80 md:px-6">
      <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
        <span className="flex size-6 items-center justify-center rounded-md bg-primary font-mono text-xs text-primary-foreground">
          P
        </span>
        Pandu RAG
      </Link>
      <nav aria-label="Main" className="flex flex-1 items-center gap-1">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
                active
                  ? "bg-secondary text-foreground"
                  : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
              )}
            >
              <Icon className="size-4" aria-hidden />
              <span className="hidden sm:inline">{label}</span>
            </Link>
          );
        })}
      </nav>
      <ThemeToggle />
    </header>
  );
}
