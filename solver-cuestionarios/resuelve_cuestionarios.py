import os
import time
import mss
import argparse
import imagehash
import re
import sys
from datetime import datetime
from PIL import Image
from google import genai
from dotenv import load_dotenv
from fpdf import FPDF

# --- CARGAR CONFIGURACIÓN ---
load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_ID = os.getenv("MODEL_ID", "gemini-2.0-flash")
TEMP_IMAGE = "captura_actual.png"
DEBUG_FOLDER = "capturas_debug"
RESULTS_FOLDER = "resultados"
MONITOR_NUMERO = os.getenv("MONITOR_NUMERO")
MONITOR_NUMERO = int(MONITOR_NUMERO) if MONITOR_NUMERO else None

# Asegurar que ambas carpetas existen
for folder in [DEBUG_FOLDER, RESULTS_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

# Inicializar cliente
client = genai.Client(api_key=API_KEY)

class QuizPDF(FPDF):
    """Generador de PDF actualizado con tablas a color"""
    def header(self):
        if self.page_no() == 1:
            self.set_font('helvetica', 'B', 15)
            self.set_text_color(50, 50, 50)
            self.cell(0, 10, 'Reporte de Cuestionario - Gemini', border=0, align='C', new_x="LMARGIN", new_y="NEXT")
            self.ln(5)

def call_gemini_with_retry(prompt, image_path):
    """Maneja errores de cuota (429) y saturación (503)"""
    intentos_503 = 0
    while True:
        try:
            with Image.open(image_path) as f:
                f.load()
                return client.models.generate_content(model=MODEL_ID, contents=[prompt, f])
        except Exception as e:
            err_msg = str(e)
            
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                wait_time = 20
                match = re.search(r"retry in ([\d\.]+)s", err_msg)
                if match: wait_time = float(match.group(1)) + 1
                print(f"\n[!] Cuota agotada. Reintentando en {wait_time:.2f}s...")
                time.sleep(wait_time)
            
            elif "503" in err_msg or "UNAVAILABLE" in err_msg or "Deadline expired" in err_msg:
                intentos_503 += 1
                espera = 5 * intentos_503
                print(f"\n[!] Servidor ocupado (503). Reintento #{intentos_503} en {espera}s...")
                time.sleep(espera)
                if intentos_503 > 5:
                    print("[!] Demasiados reintentos fallidos. Saltando captura.")
                    return None
            else:
                print(f"\n[!] Error crítico: {e}")
                return None

def procesar_pregunta(img, pdf_obj):
    """Captura, parsea el resultado y genera la tabla visual en el PDF de forma segura"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    debug_path = os.path.join(DEBUG_FOLDER, f"cap_{timestamp}.png")
    
    img.save(TEMP_IMAGE)
    img.save(debug_path)
    
    time.sleep(0.5)
    print(f" [.] Analizando captura {timestamp}...    ", end="\r")

    prompt = (
        "Analiza la imagen minuciosamente. Busca preguntas de test."
        "Si no hay preguntas, responde únicamente: 'No se detectó cuestionario'."
        "\nRespeta este formato EXACTO por cada pregunta encontrada, usando saltos de línea:\n"
        "PREGUNTA: [Número] - [Enunciado de la pregunta]\n"
        "OPCIONES: [Opciones separadas por guiones o comas]\n"
        "RESPUESTA: Pregunta [Número] -> [[Letra]] [Texto de la respuesta correcta]"
    )

    res = call_gemini_with_retry(prompt, TEMP_IMAGE)

    if res and res.text:
        if "No se detectó cuestionario" in res.text:
            print(f" [x] Captura {timestamp} omitida: No hay preguntas.        ")
            return

        # --- 1. SALIDA EN PANTALLA ---
        respuestas = re.findall(r"RESPUESTA:\s*(.*)", res.text, re.IGNORECASE)
        print("\n" + "="*50)
        if respuestas:
            for r in respuestas:
                print(f" > {r.strip()}")
        else:
            print(f" > Respuesta: {res.text[:100]}...")
        print("="*50)

        # --- 2. GUARDADO EN PDF (TABLAS VISUALES ANTI-CUELGUES) ---
        if pdf_obj:
            pdf_obj.add_page()
            pdf_obj.image(debug_path, x=10, y=20, w=180)
            pdf_obj.ln(115) 
            
            bloques = re.split(r'(?=PREGUNTA:)', res.text)
            
            for bloque in bloques:
                if "PREGUNTA:" not in bloque: continue
                
                p_match = re.search(r"PREGUNTA:\s*(.*?)(?=\nOPCIONES:|\nRESPUESTA:|$)", bloque, re.IGNORECASE | re.DOTALL)
                o_match = re.search(r"OPCIONES:\s*(.*?)(?=\nRESPUESTA:|$)", bloque, re.IGNORECASE | re.DOTALL)
                r_match = re.search(r"RESPUESTA:\s*(.*)", bloque, re.IGNORECASE)

                if p_match and r_match:
                    q_text = p_match.group(1).strip().encode('latin-1', 'replace').decode('latin-1')
                    r_text = r_match.group(1).strip().encode('latin-1', 'replace').decode('latin-1')
                    o_text = ""
                    if o_match:
                        o_text = o_match.group(1).strip().encode('latin-1', 'replace').decode('latin-1')

                    # --- DIBUJAR LA TABLA EN EL PDF (CORREGIDO) ---
                    pdf_obj.set_x(10) # Forzar cursor al margen
                    pdf_obj.set_draw_color(200, 200, 200)
                    
                    # Limpiamos posibles tabuladores que rompan fpdf2
                    q_text_clean = q_text.replace('\t', '    ')
                    r_text_clean = r_text.replace('\t', '    ')
                    o_text_clean = o_text.replace('\t', '    ') if o_text else ""
                    
                    # Fila 1: Pregunta (Azul suave)
                    pdf_obj.set_font("helvetica", "B", 11)
                    pdf_obj.set_fill_color(230, 242, 255)
                    pdf_obj.set_text_color(20, 40, 60)
                    pdf_obj.multi_cell(0, 8, f"{q_text_clean}", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")

                    # Fila 2: Opciones (Gris/Blanco)
                    if o_text_clean:
                        pdf_obj.set_font("helvetica", "", 10)
                        pdf_obj.set_fill_color(250, 250, 250)
                        pdf_obj.set_text_color(50, 50, 50)
                        pdf_obj.multi_cell(0, 7, o_text_clean, border=1, fill=True, new_x="LMARGIN", new_y="NEXT")

                    # Fila 3: Respuesta (Verde pastel)
                    pdf_obj.set_font("helvetica", "B", 11)
                    pdf_obj.set_fill_color(225, 245, 230)
                    pdf_obj.set_text_color(20, 60, 30)
                    pdf_obj.multi_cell(0, 8, f"Solución: {r_text_clean}", border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
                    
                    pdf_obj.ln(5) # Espacio entre tablas
                    
            print(f" [v] Tabla visual generada en PDF (Pág. {pdf_obj.page_no()})")

def gestionar_monitor():
    with mss.mss() as sct:
        num = len(sct.monitors) - 1
        if num <= 1: return 1
        print("\n--- Selección de Pantalla ---")
        for i in range(1, len(sct.monitors)):
            m = sct.monitors[i]
            print(f"[{i}] Pantalla {i}: {m['width']}x{m['height']}")
        try:
            return int(input(f"Selecciona monitor del TEST (1-{num}): "))
        except: return 1

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-automatico", type=int, help="Segundos entre capturas")
    parser.add_argument("-save-as-pdf", action="store_true", help="Generar reporte PDF")
    args = parser.parse_args()

    if not API_KEY:
        print("[!] Error: No hay GEMINI_API_KEY en .env")
        sys.exit(1)

    monitor_id = MONITOR_NUMERO if MONITOR_NUMERO else gestionar_monitor()
    pdf = QuizPDF() if args.save_as_pdf else None

    print(f"\n[*] Solver activo en Monitor {monitor_id}")
    print(f"[*] Las capturas irán a: ./{DEBUG_FOLDER}")
    print(f"[*] Los reportes irán a: ./{RESULTS_FOLDER}\n")
    
    try:
        if args.automatico:
            print(f"[MODO AUTO] Intervalo: {args.automatico}s. Ctrl+C para finalizar.")
            ultima_hash = None
            while True:
                with mss.mss() as sct:
                    sct_img = sct.grab(sct.monitors[monitor_id])
                    img_actual = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                
                h = imagehash.phash(img_actual)
                if ultima_hash is None or (h - ultima_hash) > 5:
                    procesar_pregunta(img_actual, pdf)
                    ultima_hash = h
                else:
                    print(".", end="", flush=True)
                time.sleep(args.automatico)
        else:
            print("[MODO MANUAL] ENTER para capturar. Escribe 'salir' para terminar.")
            while True:
                try:
                    accion = input("¿Capturar? ").lower().strip()
                    if accion == "salir": break
                    
                    with mss.mss() as sct:
                        sct_img = sct.grab(sct.monitors[monitor_id])
                        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                    procesar_pregunta(img, pdf)
                except EOFError: break
                
    except KeyboardInterrupt:
        print("\n\n[!] Finalizando programa...")
    
    finally:
        if pdf and pdf.page_no() > 0:
            nombre_f = os.path.join(RESULTS_FOLDER, f"resultado_{int(time.time())}.pdf")
            pdf.output(nombre_f)
            print(f"\n[OK] Reporte PDF visual guardado en: {nombre_f}")
        
        if os.path.exists(TEMP_IMAGE):
            os.remove(TEMP_IMAGE)
        print("[*] ¡Programa cerrado correctamente!")