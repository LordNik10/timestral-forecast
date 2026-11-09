"use client";

import { useSyncExternalStore } from "react";

function subscribe(onChange: () => void): () => void {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => observer.disconnect();
}

const isDark = () => document.documentElement.classList.contains("dark");

export function ThemeToggle() {
  const dark = useSyncExternalStore(subscribe, isDark, () => false);

  function toggle() {
    const next = !dark;
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("tema", next ? "scuro" : "chiaro");
    } catch {
      // archiviazione non disponibile: il tema vale solo per questa visita
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      className="rounded-lg border border-line bg-surface px-3 py-1.5 text-xs font-medium text-muted hover:text-ink"
      aria-label={dark ? "Passa al tema chiaro" : "Passa al tema scuro"}
    >
      {dark ? "☀ Chiaro" : "☾ Scuro"}
    </button>
  );
}
