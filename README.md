# Ingeniero de carrera para Assetto Corsa

Telemetría en tiempo real, rivales en vivo, análisis de pilotaje curva a curva, estrategia de carrera
y un ingeniero que te habla por radio (solo en las rectas) y te escucha.

## Instalación desde GitHub

Requisitos: Windows, Python 3.12 y Assetto Corsa.

```
git clone https://github.com/Nestro08/AssetoMOD.git
cd AssetoMOD
python -m venv venv
venv\Scripts\pip install -r requirements.txt
```

Los modelos de voz no están en el repositorio (pesan demasiado):
- **Reconocimiento de voz**: descarga `vosk-model-small-es-0.42.zip` de https://alphacephei.com/vosk/models
  y déjalo en la carpeta `model\` (se descomprime solo al arrancar).
- **Voz neuronal**: se descarga desde el programa, en Ajustes → Voz → Descargar voz.

Sin ellos el programa funciona igual, pero con la voz de Windows y sin órdenes por micrófono.

## Arrancar

| Archivo | Para qué |
|---|---|
| **`Ingeniero.bat`** | Uso normal con Assetto Corsa (sin ventana de consola) |
| **`Ingeniero_DEMO.bat`** | Simulador con 11 rivales, para probar sin el juego |
| `Ingeniero_consola.bat` | Igual que el normal, pero enseñando los mensajes de error |

Opciones: `venv\Scripts\python.exe main.py --help`. Los errores quedan en `datos\ingeniero.log`.

### La app de AC (rivales y HUD dentro del juego)

La memoria oficial de AC solo trae datos de tu coche. Para ver a los rivales hace falta la app
**IngenieroPuente**, que corre dentro de AC. Se instala con el botón **🔌 Instalar app en AC**
(ya está instalada y activada en tu AC). En pista, ábrela desde la barra de apps de la derecha
para ver el HUD: delta, posición, rival delante/detrás, combustible y el último mensaje de radio.

## Qué hace

**En pantalla:** motor y luces de cambio, mandos, fuerzas G, daños y entorno, cronometraje con delta
en vivo y sectores, trazas, tabla de vueltas, neumáticos (interior/medio/exterior, núcleo, presión, vida,
freno), combustible y plan de parada, mapa con rivales y marcas de bloqueos, **clasificación en vivo**.

**El ingeniero habla solo en las rectas** (espera a que haya hueco antes de la próxima frenada; lo
urgente sale siempre):
- Informe de vuelta: tiempo, récord personal, **curva donde más pierdes y por qué**, rivales y tendencias.
- Rivales: «Defiende», «¡Ataca!», «le recortas 3 décimas, lo alcanzas en 4 vueltas», paradas de rivales,
  coches doblados o que te doblan, tráfico en clasificación.
- Estrategia: ventana de parada, «entra esta vuelta», «echa 23,5 litros», dónde sales si paras ahora.
- Banderas, límites de pista, limitador, daños, combustible, temperaturas, desgaste, bloqueos repetidos.

**Por voz** (sin internet) o con botones / F1–F12: combustible, neumáticos, frenos, tiempos, estrategia,
ajustes, dónde pierdo, resumen, repite, rivales, curvas, presiones, posición, clima, daños, silencio, habla.

## Ventanas

- **📈 Análisis de vueltas**: compara vueltas (de hoy, tu referencia o sesiones guardadas) con velocidad,
  gas/freno, volante, marcha y delta por distancia; tabla **curva a curva** (frenada, velocidad mínima,
  salida, gas, consejo) y **mapa de ganancias**. Exporta a **MoTeC i2** (.ld + .ldx).
- **⛽ Estrategia**: plan de carrera (sin parar / repostar / repostar y ruedas) con ventana y litros,
  degradación del neumático, pérdida en boxes medida, posición tras parar y **calculadora de presiones en frío**.
- **⚙ Ajustes**: verbosidad, hablar en rectas, voz (Windows o neuronal), micrófono, **botones del volante**
  (asignar pulsándolos), **perfil propio por coche**, HUD, panel web y app de AC.

## Memoria entre sesiones (`datos/ingeniero.db`)

Tu vuelta de referencia por coche y pista (delta contra tu récord desde la primera vuelta), historial de
vueltas, consumo medio, pérdida en boxes por pista y cuánto sube la presión de cada coche en caliente.

## Panel web e ingeniero remoto

Actívalo en Ajustes (o `--web`). Desde el móvil o la tablet, en tu red, abre la dirección que aparece en
la barra de herramientas (incluye el PIN). Un compañero puede **escribirte mensajes que oyes por la radio**.

## Voz neuronal

Instalada y activada por defecto (voz española *davefx*, sin internet). Puedes descargar otra voz o volver a
la de Windows en Ajustes → Voz. Si la voz neuronal fallase, se usa la de Windows automáticamente.

> Importante: onnxruntime debe quedarse en la versión 1.18 (ver `requirements.txt`). Las versiones nuevas
> chocan con las librerías de PyQt5 y cierran el programa al arrancar la voz.

## Sesiones grabadas (`sesiones/`)

Autoguardado cada minuto y al cerrar: `.parquet` (telemetría completa a 20 Hz), `.json` (datos y vueltas)
y `.xlsx` (hoja de vueltas y telemetría a 5 Hz). Se pueden abrir en la ventana de análisis.

## Ejecutable

Ya construido en **`dist\IngenieroCarrera\IngenieroCarrera.exe`**: funciona sin Python, así que puedes copiar
la carpeta `dist\IngenieroCarrera` entera a otro PC (unos 500 MB, con las voces). Admite las mismas opciones
(`IngenieroCarrera.exe --demo`). Para regenerarlo tras cambiar el código: `construir_exe.bat`.

## Estructura

```
main.py                      arranque y opciones
app_ac/IngenieroPuente/      app que va dentro de AC (puente de datos + HUD)
ingeniero/memoria_ac.py      memoria compartida de AC
ingeniero/puente.py          comunicación con la app de AC
ingeniero/demo.py            simulador (pista, físicas, 11 rivales, boxes)
ingeniero/analisis.py        trazas por distancia, delta, sectores, consumo, bloqueos, neumáticos
ingeniero/rivales.py         clasificación y diferencias con puntos de control
ingeniero/curvas.py          detección de curvas y análisis curva a curva
ingeniero/estrategia.py      paradas, degradación, undercut, presiones
ingeniero/ingeniero.py       qué dice el ingeniero y cuándo
ingeniero/voz.py             radio (solo en rectas) y reconocimiento de voz
ingeniero/voz_neuronal.py    voz neuronal Piper
ingeniero/mandos.py          botones del volante y teclas globales
ingeniero/base_datos.py      memoria entre sesiones (SQLite)
ingeniero/grabador.py        grabación y exportación
ingeniero/motec.py           exportación a MoTeC i2
ingeniero/sesiones.py        abrir sesiones guardadas
ingeniero/web.py             panel web e ingeniero remoto
ingeniero/app.py             núcleo sin interfaz
ingeniero/ventana.py, widgets.py, analisis_ui.py, estrategia_ui.py, ajustes_ui.py   interfaz
ingeniero/config.py, ajustes.py, rutas.py, arranque.py, instalar_ac.py
```
