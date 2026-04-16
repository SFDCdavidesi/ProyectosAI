import os
import time
import mss
import argparse
import imagehash
import re  # Añadido para procesar el tiempo de espera
from PIL import Image
from google import genai
from dotenv import load_dotenv

# --- CARGAR CONFIGURACIÓN EXTERNA ---
load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_ID = os.getenv("MODEL_ID", "gemini-2.0-flash") # Actualizado a flash-2.0 si prefieres
TEMP_IMAGE = os.getenv("TEMP_IMAGE", "captura_quiz.png")
MONITOR_NUMERO = os.getenv("MONITOR_NUMERO")
MONITOR_NUMERO = int(MONITOR_NUMERO) if MONITOR_NUMERO else None

# Inicializar cliente
client = genai.Client(api_key=API_KEY)

def call_gemini_with_retry(prompt, image_path):
    """Llamada a Gemini con manejo de cuota (Error 429)"""
    while True:
        try:
            with Image.open(image_path) as f:
                return client.models.generate_content(model=MODEL_ID, contents=[prompt, f])
        except Exception as e:
            error_msg = str(e)
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                # Intentamos extraer los segundos que pide esperar el error
                # El error suele decir: "Please retry in 17.94s"
                wait_time = 20  # Por defecto
                match = re.search(r"retry in ([\d\.]+)s", error_msg)
                if match:
                    wait_time = float(match.group(1)) + 1
                
                print(f"\n[!] Límite alcanzado. Esperando {wait_time:.2f} segundos para reintentar...")
                time.sleep(wait_time)
            else:
                print(f"\n[!] Error inesperado en Gemini: {e}")
                return None

def obtener_captura(monitor_id):
    with mss.mss() as sct:
        monitor = sct.monitors[monitor_id]
        sct_img = sct.grab(monitor)
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        return img

def es_un_test(img):
    try:
        img_path = "check_test.png"
        img.save(img_path)
        prompt = "Responde solo 'SI' si esta imagen contiene un cuestionario o preguntas, de lo contrario responde 'NO'."
        
        res = call_gemini_with_retry(prompt, img_path)
        if res and res.text:
            return "SI" in res.text.upper()
        return False
    except:
        return False

def resolver_gemini(img):
    img.save(TEMP_IMAGE)
    prompt = "Ayúdame a resolver esta cuestión. Formato: 'Número -> Opción'. Solo la respuesta."
    
    response = call_gemini_with_retry(prompt, TEMP_IMAGE)
    if response and response.text:
        print(f"\n{'='*30}\nRESULTADO: {response.text.strip()}\n{'='*30}")

def gestionar_monitor(monitor_pref):
    with mss.mss() as sct:
        num_fisicos = len(sct.monitors) - 1
        if monitor_pref and 1 <= monitor_pref <= num_fisicos:
            return monitor_pref
        if num_fisicos <= 1:
            return 1
        print("\n--- Selección de Pantalla ---")
        for i in range(1, len(sct.monitors)):
            m = sct.monitors[i]
            print(f"[{i}] Pantalla {i}: {m['width']}x{m['height']}")
        return int(input(f"Selecciona monitor (1-{num_fisicos}): "))

def modo_automatico(monitor_id, intervalo):
    print(f"\n[MODO AUTO] Monitoreando pantalla {monitor_id} cada {intervalo}s...")
    ultima_hash = None
    ultimo_cambio_t = time.time()

    while True:
        img_actual = obtener_captura(monitor_id)
        hash_actual = imagehash.phash(img_actual)

        if ultima_hash is None:
            print("\n[!] Ejecutando captura inicial...")
            if es_un_test(img_actual):
                resolver_gemini(img_actual)
            ultima_hash = hash_actual
            ultimo_cambio_t = time.time()
        else:
            dif = hash_actual - ultima_hash
            ahora = time.time()
            umbral = 1 if (ahora - ultimo_cambio_t) > 30 else 3

            if dif >= umbral:
                print(f"\n[!] Cambio detectado (Dif: {dif}). Verificando...")
                if es_un_test(img_actual):
                    resolver_gemini(img_actual)
                    ultima_hash = hash_actual
                    ultimo_cambio_t = ahora
                else:
                    print(" [x] Cambio no relevante (no es un test).")
                    ultima_hash = hash_actual
            else:
                print(".", end="", flush=True)

        time.sleep(intervalo)

def modo_manual(monitor_id):
    print(f"\n[MODO MANUAL] Monitor {monitor_id}. Enter para capturar.")
    while True:
        acc = input("Presiona Enter para capturar... ").lower().strip()
        if acc == "salir":
            break
        img = obtener_captura(monitor_id)
        resolver_gemini(img)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-automatico", type=int, help="Segundos entre capturas")
    args = parser.parse_args()

    if not API_KEY:
        print("Error: No se encontró GEMINI_API_KEY en el archivo .env")
    else:
        target_monitor = gestionar_monitor(MONITOR_NUMERO)
        try:
            if args.automatico:
                modo_automatico(target_monitor, args.automatico)
            else:
                modo_manual(target_monitor)
        except KeyboardInterrupt:
            print("\nSaliendo...")
        finally:
            for f in [TEMP_IMAGE, "check_test.png"]:
                if os.path.exists(f):
                    os.remove(f)