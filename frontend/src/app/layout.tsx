import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { AppSidebar } from "@/components/app-sidebar";
import { Providers } from "@/components/providers";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "Pandu RAG",
    template: "%s · Pandu RAG",
  },
  description:
    "Production-grade retrieval-augmented generation: hybrid search, streamed answers with citations, evals and cost telemetry.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full">
        <Providers>
          {/* Dark rounded app frame floating on the warm backdrop. */}
          <div className="mx-auto h-dvh max-w-[120rem] p-2 sm:p-4">
            <div className="flex h-full overflow-hidden rounded-[1.75rem] bg-chrome shadow-2xl ring-1 ring-black/20">
              <AppSidebar />
              <main className="flex min-w-0 flex-1 flex-col overflow-hidden p-2 pl-0 sm:p-2.5 sm:pl-0">
                {children}
              </main>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
