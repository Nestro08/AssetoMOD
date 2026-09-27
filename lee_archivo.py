import pandas as pd
df = pd.read_parquet('sesion_TU_ARCHIVO.parquet')
print(df.describe()) # Te dará medias, máximos y mínimos de tu sesión