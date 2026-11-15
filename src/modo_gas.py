"""Modo gas (EXPERIMENTAL): modelo SEPARADO del de sólidos, entrenado con las tablas de CFI-G (PSI-159).

Qué predice (y qué NO): con llamas difusivas esféricas de etano/propano/butano, estima la probabilidad de IGNICIÓN CALIENTE y el
tiempo de quemado. NO predice velocidad de propagación ni alimenta el índice de riesgo de sólidos: son problemas físicos distintos.
Limitaciones honestas: ~330 ensayos de una sola investigación, ~90 % con ignición (clase muy desbalanceada) y filas del mismo día muy
parecidas entre sí; por eso se valida dejando fuera días completos y se compara con el modelo trivial.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import brier_score_loss, r2_score, roc_auc_score
from sklearn.model_selection import GroupKFold

CARACTERISTICAS = ["presion_kpa", "fraccion_o2", "fraccion_combustible", "flujo_combustible_mg_s", "carbonos", "es_inversa"]
CARBONOS = {"ethane": 2, "propane": 3, "butane": 4}


@dataclass
class CondicionesGas:
    """Entrada del modo gas. `fraccion_o2` y `fraccion_combustible` en 0–1; `combustible`: etano|propano|butano."""
    presion_kpa: float
    fraccion_o2: float
    fraccion_combustible: float
    flujo_combustible_mg_s: float
    combustible: str = "propano"
    llama_inversa: bool = False


@dataclass
class ResultadoGas:
    probabilidad_ignicion_caliente: float
    tiempo_quemado_s: float
    fuera_de_dominio: bool
    advertencias: list[str] = field(default_factory=list)
    modo: str = "gas"
    experimental: bool = True


def _combustible_base(texto: str) -> str | None:
    t = str(texto).lower()
    for k in CARBONOS:
        if k in t:
            return k
    return None


def cargar_tablas_gas(directorio: Path) -> pd.DataFrame:
    """Lee las tablas Normal e Inversa, las unifica y añade `tipo_combustible='gas'`. Las filas vacías del CSV se descartan."""
    marcos = []
    for ruta in sorted(Path(directorio).glob("*.csv")):
        d = pd.read_csv(ruta).dropna(how="all")
        d.columns = [" ".join(c.split()) for c in d.columns]
        d = d[d["Fuel"].notna()].copy()
        inversa = "inverse" in ruta.name.lower() or d["Flame Type"].astype(str).str.lower().str.startswith("inv").all()
        o2 = d["XO2"] if "XO2" in d else d["XO2 before test"]
        xf = d["Xf before test"] if "Xf before test" in d else d["Xf"]
        flujo = d["HC burnrate (mg/s)"] if "HC burnrate (mg/s)" in d else d["mHC (mg/s)"]
        marco = pd.DataFrame({
            "archivo": ruta.name, "dia": d["Day"].astype(int).to_numpy(), "combustible_crudo": d["Fuel"].to_numpy(),
            "presion_kpa": pd.to_numeric(d["approx p (bar)"], errors="coerce").to_numpy() * 100.0,
            "fraccion_o2": pd.to_numeric(o2, errors="coerce").to_numpy(),
            "fraccion_combustible": pd.to_numeric(xf, errors="coerce").to_numpy(),
            "flujo_combustible_mg_s": pd.to_numeric(flujo, errors="coerce").to_numpy(),
            "es_inversa": int(inversa),
            "ignicion_cruda": d["Hot ignition"].astype(str).str.strip().str.lower().to_numpy(),
            "tiempo_quemado_s": pd.to_numeric(d["burn time (sec)"], errors="coerce").to_numpy(),
        })
        marcos.append(marco)
    datos = pd.concat(marcos, ignore_index=True)
    datos["tipo_combustible"] = "gas"
    datos["combustible"] = datos["combustible_crudo"].map(_combustible_base)
    datos["carbonos"] = datos["combustible"].map(CARBONOS)
    datos["grupo"] = datos["archivo"] + "|" + datos["dia"].astype(str)
    # «flash» (ignición dudosa) y filas sin dato de entrada se excluyen: no se adivina
    datos = datos[datos["ignicion_cruda"].isin(["yes", "no"])].dropna(subset=CARACTERISTICAS + ["combustible"])
    datos = datos[datos["flujo_combustible_mg_s"] > 0]
    datos["ignicion"] = (datos["ignicion_cruda"] == "yes").astype(int)
    return datos.reset_index(drop=True)


class ModeloGas:
    """Dos Random Forest (clasificador de ignición y regresor de tiempo de quemado). Independiente del modelo de sólidos."""

    def __init__(self, n_arboles: int = 300, semilla: int = 42) -> None:
        self._clf = RandomForestClassifier(n_estimators=n_arboles, min_samples_leaf=2, class_weight="balanced", random_state=semilla)
        self._reg = RandomForestRegressor(n_estimators=n_arboles, min_samples_leaf=2, random_state=semilla)
        self.dominio: dict[str, tuple[float, float]] = {}
        self.metricas: dict[str, float] = {}
        self.entrenado = False

    def entrenar(self, datos: pd.DataFrame) -> None:
        X = datos[CARACTERISTICAS]
        self._clf.fit(X, datos["ignicion"])
        con = datos[(datos["ignicion"] == 1) & datos["tiempo_quemado_s"].notna() & (datos["tiempo_quemado_s"] > 0)]
        self._reg.fit(con[CARACTERISTICAS], np.log1p(con["tiempo_quemado_s"]))
        self.dominio = {c: (float(datos[c].min()), float(datos[c].max())) for c in CARACTERISTICAS if c not in ("es_inversa", "carbonos")}
        self.entrenado = True

    def validar(self, datos: pd.DataFrame, pliegues: int = 5) -> dict[str, float]:
        """Validación cruzada dejando fuera DÍAS completos y comparación con el modelo trivial (siempre la clase mayoritaria)."""
        X, y, g = datos[CARACTERISTICAS], datos["ignicion"].to_numpy(), datos["grupo"].to_numpy()
        p = np.full(len(datos), np.nan); t_pred = np.full(len(datos), np.nan)
        for tr, te in GroupKFold(n_splits=min(pliegues, datos["grupo"].nunique())).split(X, y, g):
            clf = RandomForestClassifier(n_estimators=200, min_samples_leaf=2, class_weight="balanced", random_state=7).fit(X.iloc[tr], y[tr])
            p[te] = clf.predict_proba(X.iloc[te])[:, 1] if len(set(y[tr])) > 1 else float(y[tr][0])
            m = (datos["ignicion"].to_numpy()[tr] == 1) & (datos["tiempo_quemado_s"].to_numpy()[tr] > 0)
            reg = RandomForestRegressor(n_estimators=200, min_samples_leaf=2, random_state=7).fit(X.iloc[tr][m], np.log1p(datos["tiempo_quemado_s"].to_numpy()[tr][m]))
            t_pred[te] = np.expm1(reg.predict(X.iloc[te]))
        base = float(y.mean())
        mt = (y == 1) & (datos["tiempo_quemado_s"].to_numpy() > 0)
        real = datos["tiempo_quemado_s"].to_numpy()[mt]
        self.metricas = {
            "n_filas": float(len(datos)), "fraccion_ignicion": base,
            "auc_ignicion": float(roc_auc_score(y, p)), "brier_modelo": float(brier_score_loss(y, p)), "brier_trivial": float(brier_score_loss(y, np.full(len(y), base))),
            "r2_tiempo_quemado_log": float(r2_score(np.log1p(real), np.log1p(t_pred[mt]))),
        }
        return self.metricas

    def predecir(self, c: CondicionesGas) -> ResultadoGas:
        if not self.entrenado:
            raise RuntimeError("El modelo de gases no está entrenado")
        clave = _combustible_base(c.combustible) or _combustible_base({"etano": "ethane", "propano": "propane", "butano": "butane"}.get(c.combustible.lower(), ""))
        if clave is None:
            raise ValueError(f"Combustible no soportado: {c.combustible!r} (etano, propano, butano)")
        fila = pd.DataFrame([{"presion_kpa": c.presion_kpa, "fraccion_o2": c.fraccion_o2, "fraccion_combustible": c.fraccion_combustible,
                              "flujo_combustible_mg_s": c.flujo_combustible_mg_s, "carbonos": CARBONOS[clave], "es_inversa": int(c.llama_inversa)}])[CARACTERISTICAS]
        avisos = ["Modo gas EXPERIMENTAL: ~330 ensayos de CFI-G (PSI-159); no validado por expertos y no alimenta el índice de riesgo de sólidos."]
        fuera = False
        for k, (lo, hi) in self.dominio.items():
            v = float(fila.iloc[0][k])
            if not lo <= v <= hi:
                fuera = True; avisos.append(f"{k}={v:g} fuera del rango entrenado [{lo:g}, {hi:g}]: extrapolación.")
        p = float(self._clf.predict_proba(fila)[0, list(self._clf.classes_).index(1)])
        return ResultadoGas(p, float(np.expm1(self._reg.predict(fila)[0])), fuera, avisos)

    def guardar(self, ruta: Path) -> None:
        Path(ruta).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, ruta)

    @staticmethod
    def cargar(ruta: Path) -> "ModeloGas":
        return joblib.load(ruta)
