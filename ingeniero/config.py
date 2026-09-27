"""Ajustes del ingeniero. Las ventanas óptimas dependen mucho del coche:
si tu coche trabaja en otros rangos, cambia el perfil aquí."""
from dataclasses import dataclass, field, fields


@dataclass(frozen=True)
class Perfil:
    nombre: str
    temp_neum_min: float  # °C, temperatura media de banda de rodadura
    temp_neum_max: float
    psi_min: float  # presión en caliente
    psi_max: float
    temp_freno_min: float
    temp_freno_max: float


PERFILES = {
    "gt": Perfil("GT / Turismo de carreras", 75, 95, 26.0, 28.5, 250, 750),
    "formula": Perfil("Monoplaza", 85, 105, 20.5, 23.5, 300, 900),
    "calle": Perfil("Coche de calle", 60, 90, 28.0, 36.0, 150, 600),
}

# Palabras en el nombre del coche (carModel) que eligen el perfil automáticamente.
_AUTO = [
    ("formula", ("formula", "f1", "f2", "f3", "tatuus", "ferrari_sf", "lotus_98t", "lotus_49",
                 "lotus_72", "rss_formula", "indy", "exos")),
    ("gt", ("gt3", "gt2", "gte", "gt4", "cup", "dtm", "lmp", "_lms", "rsr", "tcr", "wtcc",
            "p4-5", "group", "gr3", "gr4")),
]


def perfil_para_coche(car_model: str, forzado: str | None = None, personalizados: dict | None = None) -> Perfil:
    """Perfil del coche: el personalizado (Ajustes) manda; si no, el forzado; si no, por el nombre del coche."""
    if personalizados and car_model in personalizados:
        try:
            return Perfil(**personalizados[car_model])
        except TypeError:
            pass
    if forzado:
        return PERFILES[forzado]
    modelo = (car_model or "").lower()
    for clave, palabras in _AUTO:
        if any(p in modelo for p in palabras):
            return PERFILES[clave]
    return PERFILES["calle"]


@dataclass
class Config:
    perfil_forzado: str | None = None  # "gt", "formula" o "calle"; None = según el coche

    # Combustible
    margen_vueltas_combustible: float = 1.0  # vueltas extra de seguridad
    aviso_vueltas_combustible: float = 3.0

    # Desgaste (AC: 100 = nuevo)
    desgaste_aviso: float = 94.0
    desgaste_critico: float = 90.0

    # Detección de bloqueos y patinadas
    umbral_bloqueo: float = -0.22  # ratio de deslizamiento de la rueda frenando
    umbral_patinada: float = 0.22
    velocidad_min_deteccion: float = 40.0  # km/h

    # Ingeniero
    verbosidad: int = 1  # 0 = solo avisos críticos, 1 = normal, 2 = muy hablador
    pitido_radio: bool = True
    hablar_solo_en_rectas: bool = True
    modo_delta: str = "sesion"  # "sesion" (mejor de hoy) o "referencia" (récord guardado)
    coaching_curvas: bool = True

    # Voz
    voz_activada: bool = True
    motor_voz: str = "piper"  # "piper" (neuronal offline) o "sapi" (Windows); si Piper falla se usa SAPI
    voz_piper: str | None = None  # ruta al modelo .onnx de Piper
    reconocimiento_activado: bool = True
    dispositivo_micro: int | None = None
    # Botones: acción -> código ("J0B5" = mando 0 botón 5, "K7C" = tecla F13). "hablar" = push-to-talk
    botones: dict = field(default_factory=dict)

    # Ventanas óptimas propias por coche (carModel -> campos de Perfil)
    perfiles_personalizados: dict = field(default_factory=dict)

    # Integraciones
    hud_en_juego: bool = True
    web_activada: bool = False
    web_puerto: int = 8080
    web_pin: str = ""

    # Grabación
    hz_grabacion: int = 20

    def a_dict(self):
        return {f.name: getattr(self, f.name) for f in fields(self)}

    def cargar_dict(self, d):
        nombres = {f.name for f in fields(self)}
        for k, v in (d or {}).items():
            if k in nombres:
                setattr(self, k, v)
        return self
