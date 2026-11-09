"""Rigenera i dataset sintetici di esempio con seed fisso.

Uso: cd backend && uv run python ../samples/genera_campioni.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent


def vendite_mensili(rng: np.random.Generator) -> pd.DataFrame:
    mesi = pd.period_range("2017-01", "2024-12", freq="M")
    t = np.arange(len(mesi))
    trend = 1200 + 9.5 * t
    stagione = 260 * np.sin(2 * np.pi * (t % 12) / 12 - np.pi / 3) + 120 * (mesi.month == 12)
    rumore = rng.normal(0, 45, len(t))
    return pd.DataFrame({"Mese": mesi.strftime("%Y-%m"), "Vendite": np.round(trend + stagione + rumore, 1)})


def sensore_orario(rng: np.random.Generator) -> pd.DataFrame:
    ore = pd.date_range("2025-03-01 00:00", periods=60 * 24, freq="h")
    righe = []
    for nome, base, ampiezza, fase in (("sensore_a", 18.0, 4.0, 0.0), ("sensore_b", 22.5, 6.0, 1.5)):
        h = ore.hour.to_numpy()
        giorno = np.arange(len(ore)) / 24
        valori = (base + ampiezza * np.sin(2 * np.pi * (h - 9 + fase) / 24) + 0.02 * giorno
                  + rng.normal(0, 0.6, len(ore)))
        df = pd.DataFrame({"timestamp": ore.strftime("%Y-%m-%d %H:%M"), "sensore": nome,
                           "temperatura": np.round(valori, 2)})
        # Buchi: alcune ore sparse e un blocco di 6 ore consecutive.
        sparse = rng.choice(len(df), size=25, replace=False)
        blocco = np.arange(700, 706) if nome == "sensore_a" else np.arange(1100, 1106)
        righe.append(df.drop(index=np.union1d(sparse, blocco)))
    return pd.concat(righe).sort_values(["timestamp", "sensore"]).reset_index(drop=True)


def main() -> None:
    rng = np.random.default_rng(20251109)
    vendite_mensili(rng).to_csv(OUT / "vendite_mensili.csv", index=False)
    sensore_orario(rng).to_csv(OUT / "sensore_orario.csv", index=False)


if __name__ == "__main__":
    main()
