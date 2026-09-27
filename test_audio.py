import speech_recognition as sr

print("Lista de dispositivos de audio:")
mic_list = sr.Microphone.list_microphone_names()
for i, name in enumerate(mic_list):
    print(f"ID {i}: {name}")

r = sr.Recognizer()
with sr.Microphone() as source:
    print("\nPor favor, di algo ahora mismo...")
    try:
        audio = r.listen(source, timeout=5)
        print("He detectado audio. Procesando...")
        texto = r.recognize_google(audio, language="es-ES")
        print(f"He entendido: {texto}")
    except Exception as e:
        print(f"Error: {e}")