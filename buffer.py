import time

def leer_datos():
    memoria = crear_conexion()
    try:
        while True: 
            memoria.seek(0)
            datos = SPageFilePhysics.from_buffer(memoria)
            print(f"Velocidad: {datos.speedKmh:.2f} km/h, RPM: {datos.rpms}")
            time.sleep(0.05)
    finally:
        memoria.close()
