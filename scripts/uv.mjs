// Esegue uv anche quando non è nel PATH: prima `uv`, poi l'eseguibile del pacchetto Python `uv`
// (installazione con `pip install uv`). Uso: node scripts/uv.mjs <argomenti di uv>
import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";

function findUv() {
  if (spawnSync("uv", ["--version"], { stdio: "ignore" }).status === 0) return "uv";
  for (const python of ["python", "python3", "py"]) {
    // UTF-8 esplicito: su Windows Python stamperebbe nella codepage locale, corrompendo i percorsi
    // con lettere accentate nel nome utente.
    const probe = spawnSync(python, ["-c", "import uv; print(uv.find_uv_bin())"], {
      encoding: "utf8",
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    });
    const path = probe.status === 0 ? probe.stdout.trim() : "";
    if (path && existsSync(path)) return path;
  }
  return null;
}

const uv = findUv();
if (!uv) {
  console.error(
    "uv non trovato: installalo (https://docs.astral.sh/uv/ oppure `pip install uv`) " +
      "e verifica che `uv` o `python -m uv` funzionino da questo terminale.",
  );
  process.exit(1);
}

const child = spawn(uv, process.argv.slice(2), { stdio: "inherit" });
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
child.on("exit", (code, signal) => process.exit(code ?? (signal ? 1 : 0)));
