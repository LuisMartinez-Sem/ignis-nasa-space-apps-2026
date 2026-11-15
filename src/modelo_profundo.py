"""Motor profundo: ensemble de redes (PyTorch) con incertidumbre y afinado con datos reales.

Diseño:
- *Deep ensemble* de K MLP entrenados a la vez como un único tensor de pesos (K, in, out)
  con `torch.bmm`: K veces la diversidad por el coste de una sola pasada.
- Cada miembro predice media y log-varianza (NLL heteroscedástica) de log1p(velocidad)
  y el logit de propagación. La incertidumbre total = aleatoria (media de varianzas)
  + epistémica (desacuerdo entre miembros): la parte epistémica crece fuera de los
  datos vistos, que es justo cuando el operador debe desconfiar.
- `afinar()` reentrena con pocos datos reales a tasa baja: se preentrena con el prior
  físico sintético y se ajusta a PSI cuando llegue (aprendizaje por transferencia).
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn.functional as F
from pydantic import BaseModel
from torch import nn

from src.data_loader import COLUMNAS_ENTRADA
from src.envolvente import Envolvente
from src.evaluacion import MetricasEntrenamiento, calcular_metricas
from src.model import ErrorModelo, PrediccionCruda
from src.preprocessing import (
    COLUMNAS_CARACTERISTICAS,
    construir_matriz_caracteristicas,
    construir_objetivos,
    dividir_datos,
)

logger = logging.getLogger(__name__)

VERSION_PROFUNDO = "0.1.0"
SALIDAS = 3  # media log1p(v), log-varianza, logit de propagación
LOGVAR_MIN, LOGVAR_MAX = -8.0, 3.0


class CapaEnsemble(nn.Module):
    """K capas lineales independientes aplicadas en paralelo: x (K,B,in) -> (K,B,out)."""

    def __init__(self, miembros: int, entradas: int, salidas: int) -> None:
        super().__init__()
        self.peso = nn.Parameter(torch.empty(miembros, entradas, salidas))
        self.sesgo = nn.Parameter(torch.zeros(miembros, 1, salidas))
        nn.init.kaiming_normal_(self.peso, nonlinearity="relu")

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Producto por lotes: cada miembro usa sus propios pesos."""
        return torch.baddbmm(self.sesgo, x, self.peso)


class RedEnsemble(nn.Module):
    """MLP de `capas` ocultas con GELU; cabeza de 3 salidas por miembro."""

    def __init__(self, miembros: int, entradas: int, ocultos: int = 64, capas: int = 3) -> None:
        super().__init__()
        dims = [entradas] + [ocultos] * capas
        self.capas = nn.ModuleList(CapaEnsemble(miembros, dims[i], dims[i + 1]) for i in range(capas))
        self.cabeza = CapaEnsemble(miembros, ocultos, SALIDAS)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """x: (K, B, F) -> (K, B, 3)."""
        for capa in self.capas:
            x = F.gelu(capa(x))
        return self.cabeza(x)


class ResultadoAfinado(BaseModel):
    """Efecto medido de afinar con datos reales (sobre su propia partición de prueba)."""

    mae_antes_mm_s: float
    mae_despues_mm_s: float
    mejora_relativa: float
    n_entrenamiento: int
    n_prueba: int
    epocas: int


def _perdida(salida: torch.Tensor, y_log: torch.Tensor, propaga: torch.Tensor) -> torch.Tensor:
    """NLL gaussiana heteroscedástica (velocidad) + BCE (propagación), por miembro y promediada."""
    media, logvar = salida[..., 0], salida[..., 1].clamp(LOGVAR_MIN, LOGVAR_MAX)
    nll = 0.5 * (logvar + (y_log - media) ** 2 * torch.exp(-logvar)).mean()
    bce = F.binary_cross_entropy_with_logits(salida[..., 2], propaga)
    return nll + bce


class ModeloProfundo:
    """Ensemble profundo con la misma interfaz que `ModeloPropagacion` (`MotorPrediccion`)."""

    nombre = "profundo"

    def __init__(self, miembros: int = 5, ocultos: int = 64, semilla: int = 42) -> None:
        self.miembros = miembros
        self.ocultos = ocultos
        self.semilla = semilla
        self.red: RedEnsemble | None = None
        self.media = np.zeros(len(COLUMNAS_CARACTERISTICAS), dtype=np.float32)
        self.desviacion = np.ones(len(COLUMNAS_CARACTERISTICAS), dtype=np.float32)
        self.metricas: MetricasEntrenamiento | None = None
        self.origen_datos: str = "desconocido"
        self.envolvente: Envolvente = Envolvente()

    @property
    def entrenado(self) -> bool:
        """True si la red está lista para predecir."""
        return self.red is not None

    # --- Utilidades internas --------------------------------------------------
    def _normalizar(self, caracteristicas: np.ndarray) -> torch.Tensor:
        return torch.from_numpy(((caracteristicas - self.media) / self.desviacion).astype(np.float32))

    @staticmethod
    def _tensores(datos: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        velocidad, propaga = construir_objetivos(datos)
        caracteristicas = construir_matriz_caracteristicas(datos).to_numpy(dtype=np.float32)
        return caracteristicas, np.log1p(velocidad).astype(np.float32), propaga.astype(np.float32)

    def _ajustar(
        self,
        datos_ent: pd.DataFrame,
        datos_val: pd.DataFrame,
        epocas: int,
        tasa: float,
        tamano_lote: int,
        paciencia: int,
    ) -> int:
        """Bucle de entrenamiento con parada temprana; devuelve las épocas realizadas."""
        assert self.red is not None
        x_ent_np, y_ent_np, p_ent_np = self._tensores(datos_ent)
        x_ent = self._normalizar(x_ent_np)
        y_ent, p_ent = torch.from_numpy(y_ent_np), torch.from_numpy(p_ent_np)
        x_val_np, y_val_np, p_val_np = self._tensores(datos_val)
        x_val = self._normalizar(x_val_np)[None].expand(self.miembros, -1, -1)
        y_val = torch.from_numpy(y_val_np)[None].expand(self.miembros, -1)
        p_val = torch.from_numpy(p_val_np)[None].expand(self.miembros, -1)

        n = len(x_ent)
        pasos_por_epoca = max(1, int(np.ceil(n / tamano_lote)))
        optimizador = torch.optim.AdamW(self.red.parameters(), lr=tasa, weight_decay=1e-4)
        programa = torch.optim.lr_scheduler.OneCycleLR(
            optimizador, max_lr=tasa * 2, total_steps=epocas * pasos_por_epoca
        )
        mejor, mejor_estado, sin_mejora, hechas = float("inf"), None, 0, 0
        for epoca in range(epocas):
            self.red.train()
            # Cada miembro recorre los datos en su propio orden => diversidad del ensemble
            orden = torch.stack([torch.randperm(n) for _ in range(self.miembros)])
            for inicio in range(0, n, tamano_lote):
                idx = orden[:, inicio : inicio + tamano_lote]
                optimizador.zero_grad(set_to_none=True)
                _perdida(self.red(x_ent[idx]), y_ent[idx], p_ent[idx]).backward()
                nn.utils.clip_grad_norm_(self.red.parameters(), 2.0)
                optimizador.step()
                programa.step()
            self.red.eval()
            with torch.inference_mode():
                perdida_val = float(_perdida(self.red(x_val), y_val, p_val))
            hechas = epoca + 1
            if perdida_val < mejor - 1e-4:
                mejor, sin_mejora = perdida_val, 0
                mejor_estado = {k: v.detach().clone() for k, v in self.red.state_dict().items()}
            else:
                sin_mejora += 1
                if sin_mejora >= paciencia:
                    break
        if mejor_estado is not None:
            self.red.load_state_dict(mejor_estado)
        self.red.eval()
        return hechas

    # --- API pública ----------------------------------------------------------
    def entrenar(
        self,
        datos: pd.DataFrame,
        origen_datos: str,
        epocas: int = 120,
        tasa: float = 3e-3,
        tamano_lote: int = 128,
        paciencia: int = 15,
    ) -> MetricasEntrenamiento:
        """Entrena con la misma partición de prueba que el RF (comparación justa).

        Raises:
            ErrorModelo: si el dataset solo contiene una clase de propagación.
        """
        torch.manual_seed(self.semilla)
        entrenamiento, prueba = dividir_datos(datos, self.semilla)
        _, p_ent = construir_objetivos(entrenamiento)
        if p_ent.min() == p_ent.max():
            raise ErrorModelo("El dataset solo contiene una clase de propagación")
        sub_ent, sub_val = dividir_datos(entrenamiento, self.semilla + 1, fraccion_prueba=0.15)

        caracteristicas = construir_matriz_caracteristicas(sub_ent).to_numpy(dtype=np.float32)
        self.media = caracteristicas.mean(axis=0)
        self.desviacion = np.maximum(caracteristicas.std(axis=0), 1e-6)
        self.red = RedEnsemble(self.miembros, len(COLUMNAS_CARACTERISTICAS), self.ocultos)
        hechas = self._ajustar(sub_ent, sub_val, epocas, tasa, tamano_lote, paciencia)

        v_pru, p_pru = construir_objetivos(prueba)
        prediccion = self.predecir(prueba)
        self.metricas = calcular_metricas(
            v_pru, prediccion.velocidad_mm_s, p_pru, prediccion.probabilidad_propagacion, len(entrenamiento)
        )
        self.origen_datos = origen_datos
        self.envolvente = Envolvente.desde_datos(datos, COLUMNAS_ENTRADA)
        logger.info("Ensemble profundo entrenado", extra={**self.metricas.model_dump(), "epocas": hechas})
        return self.metricas

    def predecir(self, datos: pd.DataFrame) -> PrediccionCruda:
        """Predicción por lote con incertidumbre total (aleatoria + epistémica).

        Raises:
            ErrorModelo: si el modelo no está entrenado.
        """
        if self.red is None:
            raise ErrorModelo("El modelo profundo no está entrenado")
        caracteristicas = construir_matriz_caracteristicas(datos).to_numpy(dtype=np.float32)
        x = self._normalizar(caracteristicas)[None].expand(self.miembros, -1, -1)
        with torch.inference_mode():
            salida = self.red.eval()(x)
        media = salida[..., 0]
        varianza = torch.exp(salida[..., 1].clamp(LOGVAR_MIN, LOGVAR_MAX))
        media_log = media.mean(dim=0)
        # Ley de varianza total en el espacio log; delta method para volver a mm/s
        varianza_log = varianza.mean(dim=0) + media.var(dim=0, unbiased=False)
        velocidad = torch.expm1(media_log).clamp(min=0.0)
        incertidumbre = (velocidad + 1.0) * torch.sqrt(varianza_log)
        probabilidad = torch.sigmoid(salida[..., 2]).mean(dim=0)
        return PrediccionCruda(
            velocidad_mm_s=velocidad.numpy().astype(float),
            incertidumbre_mm_s=incertidumbre.numpy().astype(float),
            probabilidad_propagacion=probabilidad.numpy().astype(float),
        )

    def afinar(
        self,
        datos_reales: pd.DataFrame,
        datos_replay: pd.DataFrame | None = None,
        epocas: int = 60,
        tasa: float = 5e-4,
        tamano_lote: int = 32,
        paciencia: int = 10,
    ) -> ResultadoAfinado:
        """Ajusta el modelo preentrenado a datos reales (transfer learning).

        Tasa baja para no destruir el prior físico; `datos_replay` (muestra del dataset
        sintético) se mezcla en el entrenamiento para evitar el olvido catastrófico.
        Mide el MAE en una partición de prueba de los datos reales ANTES y DESPUÉS.

        Raises:
            ErrorModelo: si el modelo no está preentrenado.
        """
        if self.red is None:
            raise ErrorModelo("Hay que preentrenar el modelo antes de afinarlo")
        torch.manual_seed(self.semilla)
        ent_real, prueba_real = dividir_datos(datos_reales, self.semilla)
        v_pru, _ = construir_objetivos(prueba_real)
        mae_antes = float(np.abs(self.predecir(prueba_real).velocidad_mm_s - v_pru).mean())

        sub_ent, sub_val = dividir_datos(ent_real, self.semilla + 1, fraccion_prueba=0.2)
        if datos_replay is not None and len(datos_replay) > 0:
            replay = datos_replay.sample(n=min(len(datos_replay), len(sub_ent)), random_state=self.semilla)
            sub_ent = pd.concat([sub_ent, replay], ignore_index=True)
        hechas = self._ajustar(sub_ent, sub_val, epocas, tasa, tamano_lote, paciencia)

        mae_despues = float(np.abs(self.predecir(prueba_real).velocidad_mm_s - v_pru).mean())
        self.envolvente = self.envolvente.unir(Envolvente.desde_datos(datos_reales, COLUMNAS_ENTRADA))
        self.origen_datos = "sintetico+real" if "real" not in self.origen_datos else self.origen_datos
        mejora = (mae_antes - mae_despues) / mae_antes if mae_antes > 0 else 0.0
        return ResultadoAfinado(
            mae_antes_mm_s=mae_antes, mae_despues_mm_s=mae_despues, mejora_relativa=float(mejora),
            n_entrenamiento=len(sub_ent), n_prueba=len(prueba_real), epocas=hechas,
        )

    def guardar(self, ruta: Path) -> None:
        """Guarda pesos y metadatos (se carga con weights_only=True: sin pickle ejecutable)."""
        if self.red is None:
            raise ErrorModelo("No se puede guardar un modelo sin entrenar")
        ruta.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "version": VERSION_PROFUNDO,
                "columnas": list(COLUMNAS_CARACTERISTICAS),
                "miembros": self.miembros,
                "ocultos": self.ocultos,
                "semilla": self.semilla,
                "media": self.media.tolist(),
                "desviacion": self.desviacion.tolist(),
                "estado": self.red.state_dict(),
                "metricas": self.metricas.model_dump() if self.metricas else None,
                "origen_datos": self.origen_datos,
                "envolvente": {k: list(v) for k, v in self.envolvente.limites.items()},
            },
            ruta,
        )
        logger.info("Modelo profundo guardado", extra={"ruta": str(ruta)})

    @classmethod
    def cargar(cls, ruta: Path) -> ModeloProfundo:
        """Carga un modelo guardado verificando versión y columnas.

        Raises:
            ErrorModelo: si falta el archivo, está corrupto o es incompatible.
        """
        if not ruta.is_file():
            raise ErrorModelo(f"No existe el modelo profundo: {ruta}")
        try:
            c = torch.load(ruta, map_location="cpu", weights_only=True)
            if c["version"] != VERSION_PROFUNDO:
                raise ErrorModelo(f"Versión incompatible: {c['version']}")
            if c["columnas"] != list(COLUMNAS_CARACTERISTICAS):
                raise ErrorModelo("Las columnas del modelo no coinciden con el código actual")
            modelo = cls(c["miembros"], c["ocultos"], c["semilla"])
            modelo.red = RedEnsemble(c["miembros"], len(COLUMNAS_CARACTERISTICAS), c["ocultos"])
            modelo.red.load_state_dict(c["estado"])
            modelo.red.eval()
            modelo.media = np.asarray(c["media"], dtype=np.float32)
            modelo.desviacion = np.asarray(c["desviacion"], dtype=np.float32)
            modelo.origen_datos = c["origen_datos"]
            modelo.envolvente = Envolvente(limites={k: tuple(v) for k, v in c["envolvente"].items()})
            if c["metricas"]:
                modelo.metricas = MetricasEntrenamiento(**c["metricas"])
        except ErrorModelo:
            raise
        except Exception as error:  # torch.load puede fallar de muchas formas con archivos rotos
            logger.error("Modelo profundo ilegible", extra={"ruta": str(ruta)}, exc_info=True)
            raise ErrorModelo(f"Modelo profundo ilegible ({ruta.name}): {error}") from error
        return modelo
