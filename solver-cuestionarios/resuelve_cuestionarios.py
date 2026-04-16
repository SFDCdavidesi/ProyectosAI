import os
import time
import mss
import argparse
import imagehash
from PIL import Image
from google import genai
from dotenv import load_dotenv

# --- CARGAR CONFIGURACIÓN EXTERNA ---
load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_ID = os.getenv("MODEL_ID", "gemini-flash-latest")
TEMP_IMAGE = os.getenv("TEMP_IMAGE", "captura_quiz.png")
# Convertimos a int si existe, si no, None
MONITOR_NUMERO = os.getenv("MONITOR_NUMERO")
MONITOR_NUMERO = int(MONITOR_NUMERO) if MONITOR_NUMERO else None

# Inicializar cliente
client = genai.Client(api_key=API_KEY)

def obtener_captura(monitor_id):
    with mss.mss() as sct:
        monitor = sct.monitors[monitor_id]
        sct_img = sct.grab(monitor)
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        return img

def es_un_test(img):
    try:
        img.save("check_test.png")
        prompt = "Responde solo 'SI' si esta imagen contiene un cuestionario o preguntas, de lo contrario responde 'NO'."
        with Image.open("check_test.png") as f:
            res = client.models.generate_content(model=MODEL_ID, contents=[prompt, f])
        return "SI" in res.text.upper()
    except:
        return False

def resolver_gemini(img):
    img.save(TEMP_IMAGE)
    prompt = "Ayúdame a resolver esta cuestión. Formato: 'Número -> Opción'. Solo la respuesta."
    try:
        with Image.open(TEMP_IMAGE) as f:
            response = client.models.generate_content(model=MODEL_ID, contents=[prompt, f])
        print(f"\n{'='*30}\nRESULTADO: {response.text.strip()}\n{'='*30}")
    except Exception as e:
        print(f"\n[!] Error en Gemini: {e}")

def gestionar_monitor(monitor_pref):
    with mss.mss() as sct:
        num_fisicos = len(sct.monitors) - 1
        if monitor_pref and 1 <= monitor_pref <= num_fisicos:
            return monitor_pref
        
        if num_fisicos <= 1: return 1
        
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

        # 1. Captura Inicial (Sin esperar comparación)
        if ultima_hash is None:
            print("\n[!] Ejecutando captura inicial...")
            if es_un_test(img_actual):
                resolver_gemini(img_actual)
            ultima_hash = hash_actual
            ultimo_cambio_t = time.time()
        
        # 2. Comparación de cambios
        else:
            dif = hash_actual - ultima_hash
            ahora = time.time()
            
            # Ajuste de sensibilidad si pasan 30s
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
        if acc == "salir": break
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
                if os.path.exists(f): os.remove(f)