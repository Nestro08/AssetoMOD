import mmap

SHM_NAME = "Local\\acpmf_physics"

SIZE = 2048

def crear_conexion():
    return mmap.mmap(-1,SIZE,tagname=SHM_NAME, access=mmap.ACCESS_READ)