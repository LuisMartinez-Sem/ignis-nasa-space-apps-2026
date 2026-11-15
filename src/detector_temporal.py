"""Detector temporal de llamas (fría/caliente) con una TCN causal en PyTorch.

Por qué una TCN causal y no una RNN: (1) es 100 % causal, así que el resultado por
lote es IDÉNTICO al de streaming muestra a muestra (se verifica en tests); (2) tiene
campo receptivo finito y conocido, lo que acota la latencia y la memoria; (3) entrena
en paralelo, y a ~16k parámetros infiere en fracciones de milisegundo en CPU.

La persistencia de la alarma (K muestras seguidas) es lo que evita que un pico de un
solo sensor —la falsa alarma de la ISS en 2015— escale a evacuación.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from pydantic import BaseModel
from torch import nn

from src.senales import (
    ESCALAS,
    FRECUENCIA_HZ,
    N_CANALES,
    Clase,
    generar_secuencias,
    normalizar,
)

logger = logging.getLogger(__name__)

VERSION_DETECTOR = "0.1.0"
TAM_KERNEL = 3
DILATACIONES: tuple[int, ...] = (1, 2, 4, 8, 16)
CANALES_OCULTOS = 32
# Dependencia hacia atrás de la última salida: 1 + (k-1)·Σ dilataciones (=63 muestras)
CAMPO_RECEPTIVO = 1 + (TAM_KERNEL - 1) * sum(DILATACIONES)
NOMBRES_CLASES: tuple[str, ...] = tuple(c.name for c in Clase)

UMBRAL_ALARMA = 0.60          # P(fría)+P(caliente) mínima para contar un voto
MUESTRAS_PERSISTENCIA = 3     # votos consecutivos para disparar (0.3 s a 10 Hz)
UMBRAL_REPOSO = 0.30          # por debajo se considera "despejado"
MUESTRAS_REPOSO = 10          # votos consecutivos de despejado para rearmar
GRACIA_ETIQUETA_S = 0.8       # tras el inicio real el evento aún no es observable
ETIQUETA_IGNORADA = -100


class ErrorDetector(RuntimeError):
    """Detector sin entrenar, archivo corrupto o configuración inválida."""


class BloqueCausal(nn.Module):
    """Convolución dilatada causal + normalización por canal + residual."""

    def __init__(self, canales: int, dilatacion: int, dropout: float) -> None:
        super().__init__()
        self.relleno = (TAM_KERNEL - 1) * dilatacion
        self.conv = nn.Conv1d(canales, canales, TAM_KERNEL, dilation=dilatacion)
        # LayerNorm sobre canales (no sobre tiempo): una norma temporal filtraría futuro
        self.norma = nn.LayerNorm(canales)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """x: (B, C, T) -> (B, C, T); relleno solo a la izquierda => causal."""
        y = self.conv(F.pad(x, (self.relleno, 0)))
        y = self.norma(y.transpose(1, 2)).transpose(1, 2)
        return x + self.dropout(F.gelu(y))


class RedDetectora(nn.Module):
    """TCN causal: (B, T, C) de señales normalizadas -> (B, T, 3) logits por muestra."""

    def __init__(self, canales_entrada: int = N_CANALES, ocultos: int = CANALES_OCULTOS,
                 dropout: float = 0.1) -> None:
        super().__init__()
        self.entrada = nn.Conv1d(canales_entrada, ocultos, 1)
        self.bloques = nn.ModuleList(BloqueCausal(ocultos, d, dropout) for d in DILATACIONES)
        self.salida = nn.Conv1d(ocultos, len(NOMBRES_CLASES), 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Propaga la secuencia completa; la salida en t solo depende de x[:t+1]."""
        h = self.entrada(x.transpose(1, 2))
        for bloque in self.bloques:
            h = bloque(h)
        return self.salida(h).transpose(1, 2)


class MetricasDetector(BaseModel):
    """Resumen del entrenamiento (la evaluación completa vive en benchmark_deteccion)."""

    perdida_validacion: float
    exactitud_por_muestra: float
    epocas_entrenadas: int
    n_parametros: int
    n_secuencias_entrenamiento: int
    origen_datos: str = "sintetico"


@dataclass(frozen=True)
class PasoDetector:
    """Resultado de procesar una muestra en streaming."""

    t_s: float
    clase: str
    probabilidades: dict[str, float]
    alarma_activa: bool
    alarma_nueva: bool
    latencia_ms: float


def primera_alarma(votos: np.ndarray, persistencia: int) -> np.ndarray:
    """Índice de la primera muestra donde hay `persistencia` votos seguidos (o -1).

    Vectorizado con sumas acumuladas; `votos` es (n, T) booleano.
    """
    n, pasos = votos.shape
    if persistencia > pasos:
        return np.full(n, -1)
    acumulado = np.concatenate([np.zeros((n, 1), dtype=np.int32), np.cumsum(votos, axis=1, dtype=np.int32)], axis=1)
    ventanas = acumulado[:, persistencia:] - acumulado[:, :-persistencia]  # termina en t = persistencia-1 ..
    cumple = ventanas == persistencia
    hay = cumple.any(axis=1)
    primero = cumple.argmax(axis=1) + persistencia - 1
    return np.where(hay, primero, -1)


class DetectorTemporal:
    """Red entrenada + utilidades de inferencia por lote y streaming."""

    def __init__(self, red: RedDetectora | None = None) -> None:
        torch.set_num_threads(1)  # latencia predecible: sin sobrecoste de sincronización
        self.red = red if red is not None else RedDetectora()
        self.red.eval()
        self.metricas: MetricasDetector | None = None
        self.entrenado = False

    # --- Inferencia -----------------------------------------------------------
    @torch.inference_mode()
    def probabilidades(self, senales: np.ndarray, tamano_lote: int = 256) -> np.ndarray:
        """P(clase) por muestra para (n, T, C) en unidades físicas -> (n, T, 3)."""
        if senales.ndim != 3 or senales.shape[-1] != N_CANALES:
            raise ValueError(f"Se esperaba (n, T, {N_CANALES}); llegó {senales.shape}")
        self.red.eval()
        salidas = []
        for inicio in range(0, len(senales), tamano_lote):
            x = torch.from_numpy(normalizar(senales[inicio : inicio + tamano_lote]))
            salidas.append(torch.softmax(self.red(x), dim=-1).numpy())
        return np.concatenate(salidas, axis=0)

    def streaming(self, frecuencia_hz: float = FRECUENCIA_HZ) -> DetectorStreaming:
        """Crea un procesador muestra a muestra con estado propio."""
        if not self.entrenado:
            raise ErrorDetector("El detector no está entrenado")
        return DetectorStreaming(self, frecuencia_hz)

    # --- Persistencia ---------------------------------------------------------
    def guardar(self, ruta: Path) -> None:
        """Guarda pesos + metadatos. Se carga con weights_only=True (sin pickle ejecutable)."""
        if not self.entrenado or self.metricas is None:
            raise ErrorDetector("No se puede guardar un detector sin entrenar")
        ruta.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "version": VERSION_DETECTOR,
                "campo_receptivo": CAMPO_RECEPTIVO,
                "canales": N_CANALES,
                "escalas": [float(e) for e in ESCALAS],
                "estado": self.red.state_dict(),
                "metricas": self.metricas.model_dump(),
            },
            ruta,
        )
        logger.info("Detector guardado", extra={"ruta": str(ruta)})

    @classmethod
    def cargar(cls, ruta: Path) -> DetectorTemporal:
        """Carga un detector guardado, verificando compatibilidad.

        Raises:
            ErrorDetector: si falta el archivo, está corrupto o es incompatible.
        """
        if not ruta.is_file():
            raise ErrorDetector(f"No existe el detector: {ruta}")
        try:
            contenido = torch.load(ruta, map_location="cpu", weights_only=True)
            if contenido["version"] != VERSION_DETECTOR:
                raise ErrorDetector(f"Versión incompatible: {contenido['version']}")
            if contenido["canales"] != N_CANALES or contenido["campo_receptivo"] != CAMPO_RECEPTIVO:
                raise ErrorDetector("La arquitectura guardada no coincide con el código actual")
            if not np.allclose(contenido["escalas"], ESCALAS):
                raise ErrorDetector("Las escalas de normalización cambiaron; reentrenar")
            red = RedDetectora()
            red.load_state_dict(contenido["estado"])
            detector = cls(red)
            detector.metricas = MetricasDetector(**contenido["metricas"])
            detector.entrenado = True
        except ErrorDetector:
            raise
        except Exception as error:  # torch.load puede fallar de muchas formas con archivos rotos
            logger.error("Detector ilegible", extra={"ruta": str(ruta)}, exc_info=True)
            raise ErrorDetector(f"Detector ilegible ({ruta.name}): {error}") from error
        return detector


class DetectorStreaming:
    """Procesa muestras de una en una con histéresis (persistencia + rearme)."""

    def __init__(self, detector: DetectorTemporal, frecuencia_hz: float = FRECUENCIA_HZ) -> None:
        self._detector = detector
        self._dt = 1.0 / frecuencia_hz
        self._ventana = np.zeros((CAMPO_RECEPTIVO, N_CANALES), dtype=np.float32)
        self._n = 0
        self._votos: deque[bool] = deque(maxlen=MUESTRAS_PERSISTENCIA)
        self._reposo: deque[bool] = deque(maxlen=MUESTRAS_REPOSO)
        self._alarma = False

    def paso(self, muestra: np.ndarray) -> PasoDetector:
        """Procesa una muestra física de forma (C,) y devuelve el estado del detector."""
        muestra = np.asarray(muestra, dtype=np.float32)
        if muestra.shape != (N_CANALES,):
            raise ValueError(f"Se esperaba una muestra de {N_CANALES} canales")
        inicio = time.perf_counter()
        self._ventana = np.roll(self._ventana, -1, axis=0)
        self._ventana[-1] = muestra / ESCALAS
        self._n += 1
        # Con menos de CAMPO_RECEPTIVO muestras se usa solo lo observado: replica el
        # relleno por capa del entrenamiento (rellenar con ceros daría otra función)
        disponibles = min(self._n, CAMPO_RECEPTIVO)
        x = torch.from_numpy(self._ventana[-disponibles:][None])
        with torch.inference_mode():
            probs = torch.softmax(self._detector.red(x)[0, -1], dim=-1).numpy()
        latencia_ms = (time.perf_counter() - inicio) * 1000.0

        p_evento = float(probs[Clase.LLAMA_FRIA] + probs[Clase.LLAMA_CALIENTE])
        self._votos.append(p_evento >= UMBRAL_ALARMA)
        self._reposo.append(p_evento < UMBRAL_REPOSO)
        alarma_nueva = False
        if not self._alarma and len(self._votos) == MUESTRAS_PERSISTENCIA and all(self._votos):
            self._alarma = alarma_nueva = True
        elif self._alarma and len(self._reposo) == MUESTRAS_REPOSO and all(self._reposo):
            self._alarma = False
        return PasoDetector(
            t_s=(self._n - 1) * self._dt,
            clase=NOMBRES_CLASES[int(probs.argmax())],
            probabilidades={nombre: float(p) for nombre, p in zip(NOMBRES_CLASES, probs)},
            alarma_activa=self._alarma,
            alarma_nueva=alarma_nueva,
            latencia_ms=latencia_ms,
        )


def _etiquetas_con_gracia(etiquetas: np.ndarray, meta, frecuencia_hz: float) -> np.ndarray:
    """Ignora la pérdida justo tras cada inicio real: ahí el evento aún no es observable.

    Sin esto la red aprendería a "adivinar" el inicio y a disparar de más.
    """
    pasos = etiquetas.shape[1]
    t = (np.arange(pasos) / frecuencia_hz)[None, :]
    resultado = etiquetas.copy()
    inicio = meta["t_inicio_s"].to_numpy()[:, None]
    caliente = meta["t_caliente_s"].to_numpy()[:, None]
    es_trans = (meta["tipo"].to_numpy() == "fria_a_caliente")[:, None]
    tras_inicio = (t >= inicio) & (t < inicio + GRACIA_ETIQUETA_S)  # NaN => False
    tras_transicion = es_trans & (t >= caliente) & (t < caliente + GRACIA_ETIQUETA_S)
    resultado[tras_inicio | tras_transicion] = ETIQUETA_IGNORADA
    return resultado


def entrenar_detector(
    n_secuencias: int = 1500,
    epocas: int = 25,
    semilla: int = 0,
    tamano_lote: int = 64,
    paciencia: int = 6,
) -> DetectorTemporal:
    """Entrena el detector sobre secuencias sintéticas con parada temprana.

    Args:
        n_secuencias: secuencias de entrenamiento (la validación usa n/5, semilla distinta).
        epocas: máximo de épocas.
        semilla: semilla de generación y de inicialización.
        tamano_lote: tamaño de minilote.
        paciencia: épocas sin mejora de validación antes de parar.

    Returns:
        Detector listo (con los mejores pesos de validación).
    """
    torch.manual_seed(semilla)
    n_val = max(100, n_secuencias // 5)
    x_ent, y_ent, meta_ent = generar_secuencias(n_secuencias, semilla=semilla)
    x_val, y_val, meta_val = generar_secuencias(n_val, semilla=semilla + 10_000)
    y_ent = _etiquetas_con_gracia(y_ent, meta_ent, FRECUENCIA_HZ)
    y_val = _etiquetas_con_gracia(y_val, meta_val, FRECUENCIA_HZ)

    t_x_ent, t_y_ent = torch.from_numpy(normalizar(x_ent)), torch.from_numpy(y_ent)
    t_x_val, t_y_val = torch.from_numpy(normalizar(x_val)), torch.from_numpy(y_val)

    detector = DetectorTemporal()
    red = detector.red
    pesos = torch.tensor([1.0, 2.0, 2.0])  # los eventos son minoría por muestra
    optimizador = torch.optim.AdamW(red.parameters(), lr=3e-3, weight_decay=1e-4)
    pasos_por_epoca = int(np.ceil(n_secuencias / tamano_lote))
    programa = torch.optim.lr_scheduler.OneCycleLR(
        optimizador, max_lr=6e-3, total_steps=epocas * pasos_por_epoca
    )

    def perdida(logits: torch.Tensor, objetivo: torch.Tensor) -> torch.Tensor:
        return F.cross_entropy(
            logits.reshape(-1, len(NOMBRES_CLASES)), objetivo.reshape(-1),
            weight=pesos, ignore_index=ETIQUETA_IGNORADA,
        )

    mejor_perdida, mejor_estado, sin_mejora, epocas_hechas = float("inf"), None, 0, 0
    for epoca in range(epocas):
        red.train()
        orden = torch.randperm(n_secuencias)
        for inicio in range(0, n_secuencias, tamano_lote):
            lote = orden[inicio : inicio + tamano_lote]
            optimizador.zero_grad(set_to_none=True)
            perdida(red(t_x_ent[lote]), t_y_ent[lote]).backward()
            nn.utils.clip_grad_norm_(red.parameters(), 1.0)
            optimizador.step()
            programa.step()
        red.eval()
        with torch.inference_mode():
            logits_val = red(t_x_val)
            perdida_val = float(perdida(logits_val, t_y_val))
        epocas_hechas = epoca + 1
        logger.info("Época detector", extra={"epoca": epocas_hechas, "perdida_val": round(perdida_val, 4)})
        if perdida_val < mejor_perdida - 1e-4:
            mejor_perdida, sin_mejora = perdida_val, 0
            mejor_estado = {k: v.detach().clone() for k, v in red.state_dict().items()}
        else:
            sin_mejora += 1
            if sin_mejora >= paciencia:
                break

    if mejor_estado is not None:
        red.load_state_dict(mejor_estado)
    red.eval()
    with torch.inference_mode():
        prediccion = red(t_x_val).argmax(-1)
        valido = t_y_val != ETIQUETA_IGNORADA
        exactitud = float((prediccion[valido] == t_y_val[valido]).float().mean())
    detector.metricas = MetricasDetector(
        perdida_validacion=mejor_perdida,
        exactitud_por_muestra=exactitud,
        epocas_entrenadas=epocas_hechas,
        n_parametros=sum(p.numel() for p in red.parameters()),
        n_secuencias_entrenamiento=n_secuencias,
    )
    detector.entrenado = True
    logger.info("Detector entrenado", extra=detector.metricas.model_dump())
    return detector
