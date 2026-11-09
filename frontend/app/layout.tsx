import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Previsioni con Timestral",
  description: "Forecasting locale di serie temporali con i modelli Timestral di Mistral AI",
};

// Applica il tema salvato prima del primo paint, per evitare il lampo chiaro/scuro.
const themeScript = `(function(){try{var t=localStorage.getItem("tema");var d=t?t==="scuro":matchMedia("(prefers-color-scheme: dark)").matches;if(d)document.documentElement.classList.add("dark")}catch(e){}})()`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="it" suppressHydrationWarning className="h-full antialiased">
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-full">{children}</body>
    </html>
  );
}
