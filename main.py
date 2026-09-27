"""Ingeniero de carrera para Assetto Corsa.

Uso:
    python main.py                 # se conecta a Assetto Corsa
    python main.py --demo          # simulador para probar sin el juego
    python main.py --help          # todas las opciones
"""
import argparse
import logging
import logging.handlers
import sys

from ingeniero import rutas
from ingeniero.config import PERFILES, Config


def codigo_boton(texto):
    """'J0B5' (mando 0, botón 5), 'F13', 'NUM0', 'A' o '0x91' -> código de asignación."""
    t = texto.strip().upper()
    if t.startswith("J") and "B" in t:
        return t
    if t.startswith("0X"):
        return f"K{int(t, 16):X}"
    if t.startswith("F") and t[1:].isdigit() and 1 <= int(t[1:]) <= 24:
        return f"K{0x6F + int(t[1:]):X}"
    if t.startswith("NUM") and t[3:].isdigit():
        return f"K{0x60 + int(t[3:]):X}"
    if len(t) == 1 and t.isalnum():
        return f"K{ord(t):X}"
    raise argparse.ArgumentTypeError(f"botón o tecla no reconocido: {texto}")


def configurar_registro():
    rutas.asegurar()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    archivo = logging.handlers.RotatingFileHandler(rutas.REGISTRO, maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    archivo.setFormatter(fmt)
    manejadores = [archivo]
    if sys.stderr is not None:  # con pythonw o el .exe no hay consola
        consola = logging.StreamHandler()
        consola.setFormatter(fmt)
        manejadores.append(consola)
    logging.basicConfig(level=logging.INFO, handlers=manejadores)


def main():
    ap = argparse.ArgumentParser(description="Telemetría en tiempo real e ingeniero de carrera por voz para Assetto Corsa")
    ap.add_argument("--demo", action="store_true", help="usar el simulador en lugar de AC")
    ap.add_argument("--vueltas", type=int, default=15, help="vueltas de la carrera demo")
    ap.add_argument("--velocidad", type=float, default=1.0, help="multiplicador de tiempo de la demo")
    ap.add_argument("--parada-demo", type=int, metavar="VUELTA", help="en la demo, entrar a boxes en esa vuelta")
    ap.add_argument("--perfil", choices=sorted(PERFILES), help="forzar ventanas óptimas (por defecto según el coche)")
    ap.add_argument("--verbosidad", type=int, choices=(0, 1, 2), help="0 = solo lo crítico, 1 = normal, 2 = muy hablador")
    ap.add_argument("--sin-voz", action="store_true", help="no hablar (solo texto en pantalla)")
    ap.add_argument("--sin-micro", action="store_true", help="no escuchar órdenes por micrófono")
    ap.add_argument("--sin-pitido", action="store_true", help="sin pitido de radio antes de cada mensaje")
    ap.add_argument("--boton-hablar", "--tecla-hablar", type=codigo_boton, metavar="BOTON",
                    help="push-to-talk: J0B5 (mando 0, botón 5), F13, NUM0, 0x91... Funciona aunque AC tenga el foco")
    ap.add_argument("--web", action="store_true", help="activar el panel web para móvil/tablet")
    args = ap.parse_args()

    configurar_registro()
    config = Config()
    from ingeniero import ajustes
    ajustes.cargar(config)  # lo guardado en la ventana de Ajustes
    # La línea de comandos manda sobre lo guardado
    if args.perfil:
        config.perfil_forzado = args.perfil
    if args.verbosidad is not None:
        config.verbosidad = args.verbosidad
    if args.sin_voz:
        config.voz_activada = False
    if args.sin_micro:
        config.reconocimiento_activado = False
    if args.sin_pitido:
        config.pitido_radio = False
    if args.boton_hablar:
        config.botones = dict(config.botones, hablar=args.boton_hablar)
    if args.web:
        config.web_activada = True

    if config.motor_voz == "piper":
        # onnxruntime (voz neuronal) debe cargarse ANTES que PyQt5: al revés, sus librerías de C++ chocan y el
        # programa se cierra de golpe.
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            pass
    from PyQt5.QtWidgets import QApplication

    from ingeniero.arranque import crear_aplicacion
    from ingeniero.ventana import VentanaPrincipal

    qt = QApplication(sys.argv)
    app = crear_aplicacion(config, demo=args.demo, vueltas=args.vueltas, velocidad=args.velocidad,
                           parada_demo=args.parada_demo)
    ventana = VentanaPrincipal(app)
    ventana.show()
    sys.exit(qt.exec_())


if __name__ == "__main__":
    main()
