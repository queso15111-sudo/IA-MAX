import os
import sqlite3
import uuid
import random
import base64
from flask import Flask, render_template, request, jsonify, session
from openai import OpenAI
from tavily import TavilyClient

app = Flask(__name__)

# ==============================================================================
# CONFIGURACIÓN DE API KEYS Y SESIONES - CON RESPALDO SEGURO
# ==============================================================================
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "clave_secreta_para_sesiones_max")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "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")
IMG_API_KEY = os.environ.get("IMG_API_KEY", "AIzaSyACpRZjPxNFQLkY3jP_lN7OZWARbTbKBQM")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "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")

client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_API_KEY
)

img_client = OpenAI(api_key=IMG_API_KEY)
tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

# ==============================================================================
# APARTADO PARA TODOS LOS USUARIOS MANUALES QUE QUIERAS CREAR
# ==============================================================================
USUARIOS_ESTATICOS = {
    'admin': '123456',
}

codigos_verificacion = {}

# ==============================================================================
# CONFIGURACIÓN DE BASE DE DATOS COMPATIBLE CON RENDER (NUBE)
# ==============================================================================
# Si está en Render, usa la carpeta /tmp que tiene todos los permisos de escritura
if os.environ.get("RENDER"):
    DB_PATH = "/tmp/usuarios_ia.db"
else:
    DB_PATH = "usuarios_ia.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            email TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            verificado INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            user_email TEXT,
            titulo TEXT,
            FOREIGN KEY(user_email) REFERENCES usuarios(email)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mensajes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT,
            role TEXT,
            content TEXT,
            image_data TEXT,
            FOREIGN KEY(chat_id) REFERENCES chats(id)
        )
    ''')
    
    conn.commit()
    conn.close()

# Forzar la creación de la base de datos y sus tablas al arrancar
init_db()

# ==========================================
# RUTAS DE AUTENTICACIÓN Y SESIÓN
# ==========================================
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/verificar_sesion')
def verificar_sesion():
    if 'user' in session:
        return jsonify({"autenticado": True, "user": session['user']})
    return jsonify({"autenticado": False})

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    email = data.get('email')
    password = data.get('pass')
    
    if len(password) < 6:
        return jsonify({"success": False, "error": "La contraseña debe tener al menos 6 caracteres"})
        
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO usuarios (email, password, verificado) VALUES (?, ?, 0)', (email, password))
        conn.commit()
        
        codigo = str(random.randint(100000, 999999))
        codigos_verificacion[email] = codigo
        
        print("\n" + "="*50)
        print(f"📩 CORREO ENVIADO A: {email}")
        print(f"🔑 CÓDIGO DE VERIFICACIÓN: {codigo}")
        print("="*50 + "\n")
        
        return jsonify({"success": True})
    except sqlite3.IntegrityError:
        return jsonify({"success": False, "error": "El usuario ya existe"})
    finally:
        conn.close()

@app.route('/verificar_codigo', methods=['POST'])
def verificar_codigo():
    data = request.json
    email = data.get('email')
    codigo = data.get('codigo')
    
    if codigos_verificacion.get(email) == codigo:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE usuarios SET verificado = 1 WHERE email = ?', (email,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Código de verificación incorrecto"})

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('pass')
    
    if email in USUARIOS_ESTATICOS and USUARIOS_ESTATICOS[email] == password:
        session['user'] = email
        return jsonify({"success": True})
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM usuarios WHERE email = ? AND password = ? AND verificado = 1', (email, password))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        session['user'] = email
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Credenciales inválidas o cuenta no verificada"})

@app.route('/logout')
def logout():
    session.pop('user', None)
    return jsonify({"success": True})

# ==========================================
# GESTIÓN DE CHATS (HISTORIAL)
# ==========================================
@app.route('/obtener_chats')
def obtener_chats():
    if 'user' not in session:
        return jsonify([])
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT id, titulo FROM chats WHERE user_email = ?', (session['user'],))
    chats = [{"id": row[0], "titulo": row[1]} for row in cursor.fetchall()]
    conn.close()
    return jsonify(chats)

@app.route('/crear_chat', methods=['POST'])
def crear_chat():
    if 'user' not in session:
        return jsonify({"error": "No autorizado"}), 401
    chat_id = str(uuid.uuid4())
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO chats (id, user_email, titulo) VALUES (?, ?, ?)', (chat_id, session['user'], "Nueva conversación"))
    conn.commit()
    conn.close()
    return jsonify({"chat_id": chat_id})

@app.route('/obtener_mensajes')
def obtener_mensajes():
    chat_id = request.args.get('chat_id')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT role, content, image_data FROM mensajes WHERE chat_id = ? ORDER BY id ASC', (chat_id,))
    mensajes = [{"role": row[0], "content": row[1], "image_data": row[2]} for row in cursor.fetchall()]
    conn.close()
    return jsonify(mensajes)

# ==========================================
# NÚCLEO MULTIMODAL (PROCESAMIENTO DE PETICIONES)
# ==========================================
@app.route('/preguntar', methods=['POST'])
def preguntar():
    if 'user' not in session:
        return jsonify({"error": "No autorizado"}), 401
        
    data = request.json
    mensaje_usuario = data.get('mensaje', '').strip()
    chat_id = data.get('chat_id')
    modelo_seleccionado = data.get('modelo', 'flash') 
    imagen_b64 = data.get('imagen') 

    peticion_crear_img = any(palabra in mensaje_usuario.lower() for palabra in ["genera una imagen", "crea una imagen", "dibuja", "generar imagen"])
    
    if peticion_crear_img and not imagen_b64:
        respuesta_ia = "Actualmente mi núcleo en Groq me permite analizar imágenes, pero no tengo un modelo integrado para crearlas desde cero. ¡Prueba subiendo una foto!"
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO mensajes (chat_id, role, content, image_data) VALUES (?, ?, ?, ?)', (chat_id, 'user', mensaje_usuario, None))
        cursor.execute('INSERT INTO mensajes (chat_id, role, content, image_data) VALUES (?, ?, ?, ?)', (chat_id, 'assistant', respuesta_ia, None))
        conn.commit()
        conn.close()
        return jsonify({"respuesta": respuesta_ia, "imagen": None})

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO mensajes (chat_id, role, content, image_data) VALUES (?, ?, ?, ?)', 
                   (chat_id, 'user', mensaje_usuario, imagen_b64))
    conn.commit()

    cursor.execute('SELECT titulo FROM chats WHERE id = ?', (chat_id,))
    fila_chat = cursor.fetchone()
    titulo_contexto = fila_chat[0] if fila_chat else ""

    contexto_internet = ""
    palabras_vacias = ["bien", "ok", "hola", "bueno", "gracias", "listo", "dale", "adios", "hasta luego", "siguiente", "no", "si", "perfecto"]
    es_mensaje_vacio = mensaje_usuario.lower().strip() in palabras_vacias or len(mensaje_usuario) <= 2

    if mensaje_usuario and not imagen_b64 and not es_mensaje_vacio:
        try:
            if titulo_contexto and titulo_contexto != "Nueva conversación" and len(mensaje_usuario) < 30:
                termino_busqueda = f"{titulo_contexto} {mensaje_usuario}"
            else:
                termino_busqueda = mensaje_usuario

            search_result = tavily_client.get_search_context(query=termino_busqueda, search_depth="advanced")
            contexto_internet = f"\n\n[INFORMACIÓN EN TIEMPO REAL RECOLECTADA DE INTERNET (AÑO 2026)]:\n{search_result}"
        except Exception as e:
            print(f"⚠️ Error en Tavily: {str(e)}")

    cursor.execute('SELECT role, content, image_data FROM mensajes WHERE chat_id = ? ORDER BY id ASC', (chat_id,))
    historial_db = cursor.fetchall()
    
    system_prompt = (
        "Eres MAX, un asistente inteligente de última generación operando en el año 2026. "
        "Fuiste creado y programado exclusivamente por Ruben Maza. Si alguien te pregunta "
        "quién te creó o quién es tu desarrollador, debes responder con orgullo que fue Ruben Maza.\n\n"
        "INFORMACIÓN IMPORTANTE SOBRE TU CREADOR:\n"
        "- Ruben Maza es un joven programador y desarrollador de software independiente.\n\n"
        "REGLAS DE SEGURIDAD Y CONFIGURACIÓN:\n"
        "- Está TOTALMENTE PROHIBIDO generar contenido pornográfico, erótico, obsceno o sexualmente explícito. Si un usuario te pide esto, niégate firmemente con educación.\n"
        "- Tienes la capacidad de adaptar tu modo de hablar, personalidad, tono y acento (por ejemplo, hablar como colombiano, mexicano, de forma graciosa, seria, etc.) SIEMPRE Y CUANDO el usuario te lo pida explícitamente en el chat.\n"
        "- Si no sabes la respuesta a algo o no tienes datos reales, prefiere admitirlo antes que inventar o alucinar información.\n\n"
        "Responde de forma clara, directa y con lógica natural.\n"
        "REGLAS CRÍTICAS DE CONVERSACIÓN:\n"
        "1. NUNCA te despidas con '¡Hasta luego!' o 'Adiós' a menos que el usuario se despida primero.\n"
        "2. Si el usuario te responde con palabras como 'bien', 'ok', 'listo' o similares, no cierres el chat. Mantén la conversación abierta preguntando en qué más puedes colaborar."
    )
    if contexto_internet:
        system_prompt += f"\n\nUsa la información de internet: {contexto_internet}"

    payload_mensajes = [{"role": "system", "content": system_prompt}]

    for row in historial_db:
        role = row['role']
        content = row['content']
        img_data = row['image_data']
        if img_data:
            payload_mensajes.append({
                "role": role,
                "content": [
                    {"type": "text", "text": content if content else "¿Qué hay en esta imagen?"},
                    {"type": "image_url", "image_url": {"url": img_data}}
                ]
            })
        else:
            payload_mensajes.append({"role": role, "content": content})

    if imagen_b64:
        modelo_ejecucion = "llama-3.2-11b-vision-instruct"
    else:
        modelo_ejecucion = "llama-3.1-8b-instant" if modelo_seleccionado == 'flash' else "llama-3.3-70b-versatile"

    try:
        completion = client.chat.completions.create(
            model=modelo_ejecucion,
            messages=payload_mensajes,
            temperature=0.5,
            max_tokens=1024
        )
        respuesta_ia = completion.choices[0].message.content
    except Exception as e:
        respuesta_ia = f"Error del núcleo: {str(e)}"

    cursor.execute('INSERT INTO mensajes (chat_id, role, content, image_data) VALUES (?, ?, ?, ?)', 
                   (chat_id, 'assistant', respuesta_ia, None))
    conn.commit()

    cursor.execute('SELECT COUNT(*) FROM mensajes WHERE chat_id = ?', (chat_id,))
    if cursor.fetchone()[0] <= 3 and mensaje_usuario and not es_mensaje_vacio:
        titulo_corto = mensaje_usuario[:25] + "..." if len(mensaje_usuario) > 25 else mensaje_usuario
        cursor.execute('UPDATE chats SET titulo = ? WHERE id = ?', (titulo_corto, chat_id))
        conn.commit()

    conn.close()
    return jsonify({"respuesta": respuesta_ia, "imagen": None})

@app.route('/generar_imagen', methods=['POST'])
def generar_imagen():
    if 'user' not in session:
        return jsonify({"error": "No autorizado"}), 401
    prompt = request.json.get('prompt')
    try:
        response = img_client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            n=1,
            size="1024x1024"
        )
        return jsonify({"success": True, "url": response.data[0].url})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

if __name__ == '__main__':
    app.run(debug=True, port=5000)