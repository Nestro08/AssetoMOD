import mmap, ctypes, time, pandas as pd, matplotlib.pyplot as plt
from datetime import datetime

# --- 1. ESTRUCTURA DE DATOS (Mapeo de memoria de Assetto Corsa) ---
class Physics(ctypes.Structure):
    _fields_ = [
        ("packetId", ctypes.c_int), ("gas", ctypes.c_float), ("brake", ctypes.c_float),
        ("fuel", ctypes.c_float), ("gear", ctypes.c_int), ("rpms", ctypes.c_int),
        ("steerAngle", ctypes.c_float), ("speedKmh", ctypes.c_float),
        ("velocity", ctypes.c_float * 3), ("accG", ctypes.c_float * 3),
        ("wheelSlip", ctypes.c_float * 4), ("wheelLoad", ctypes.c_float * 4),
        ("pressure", ctypes.c_float * 4), ("angularSpeed", ctypes.c_float * 4),
        ("tyreWear", ctypes.c_float * 4), ("tyreTemperature", ctypes.c_float * 4),
        ("carCoordinates", ctypes.c_float * 3), ("padding", ctypes.c_char * 1860)
    ]

# --- 2. CONFIGURACIÓN ---
# Abrimos la memoria compartida de Assetto Corsa
shm = mmap.mmap(0, 2048, tagname="Local\\acpmf_physics", access=mmap.ACCESS_READ)
telemetry_data = []

plt.ion()
fig, ax = plt.subplots()
print("TELEMETRÍA ACTIVA. Cierra la ventana del gráfico para guardar el Excel.")

# --- 3. BUCLE PRINCIPAL ---
try:
    while plt.fignum_exists(fig.number):
        # Mapeamos la estructura desde el buffer
        phys = Physics.from_buffer(shm)
        
        # Guardamos datos en el registro
        row = {
            "Timestamp": datetime.now().strftime("%H:%M:%S.%f"),
            "Velocidad_Kmh": float(phys.speedKmh),
            "RPM": int(phys.rpms),
            "Marcha": int(phys.gear),
            "Combustible": float(phys.fuel),
            "Desgaste_FL": phys.tyreWear[0], "Desgaste_FR": phys.tyreWear[1],
            "Desgaste_RL": phys.tyreWear[2], "Desgaste_RR": phys.tyreWear[3],
            "Temp_FL": phys.tyreTemperature[0], "Temp_FR": phys.tyreTemperature[1]
        }
        telemetry_data.append(row)
        
        # Feedback visual simple
        ax.clear()
        ax.text(0.5, 0.5, f"Vel: {int(phys.speedKmh)} km/h\nRPM: {phys.rpms}", 
                ha='center', fontsize=15)
        plt.pause(0.05)
        
        # Limpieza de puntero para evitar errores de memoria
        del phys 

finally:
    # --- 4. CIERRE SEGURO ---
    shm.close()
    if telemetry_data:
        df = pd.DataFrame(telemetry_data)
        filename = f"telemetria_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        df.to_excel(filename, index=False)
        print(f"\nSesión terminada con éxito.")
        print(f"Datos exportados a: {filename}")