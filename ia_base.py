import os
import sqlite3
import uuid
import random
import base64
from flask import Flask, render_template, request, jsonify, session
from openai import OpenAI
from tavily import TavilyClient

app = Flask(__name__)
app.secret_key = "clave_secreta_para_sesiones_max"

# ==============================================================================
# APARTADO PARA TODOS LOS USUARIOS MANUALES QUE QUIERAS CREAR
# Formato: 'usuario_o_correo': 'contraseña'
# ==============================================================================
USUARIOS_ESTATICOS = {
    'admin': '123456',
    # Puedes seguir añadiendo todos los usuarios estáticos que quieras aquí abajo:
    # 'penagos': 'clave_secreta',
    # 'ejemplo@correo.com': 'clave123',
}
# ==============================================================================

# ==========================================
# CONFIGURACIÓN DE API KEYS - PRIVADO
# ==========================================
GROQ_API_KEY = "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"
IMG_API_KEY = "AIzaSyACpRZjPxNFQLkY3jP_lN7OZWARbTbKBQM"
TAVILY_API_KEY = "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"

client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_API_KEY
)

img_client = OpenAI(api_key=IMG_API_KEY)
tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

codigos_verificacion = {}

# ==========================================
# BASE DE DATOS - INICIALIZACIÓN
# ==========================================
def init_db():
    conn = sqlite3.connect('usuarios_ia.db')
    cursor = conn.cursor()
    
    # Tabla de usuarios
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            email TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            verificado INTEGER DEFAULT 0
        )
    ''')
    
    # Tabla de chats independientes
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            user_email TEXT,
            titulo TEXT,
            FOREIGN KEY(user_email) REFERENCES usuarios(email)
        )
    ''')
    
    # Tabla de mensajes (Con soporte nativo para imágenes en Base64)
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
        
    conn = sqlite3.connect('usuarios_ia.db')
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT INTO usuarios (email, password, verificado) VALUES (?, ?, 0)', (email, password))
        conn.commit()
        
        # Simulación de envío de Token por terminal
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
        conn = sqlite3.connect('usuarios_ia.db')
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
    
    # 1. Comprobación prioritaria en el apartado de usuarios estáticos
    if email in USUARIOS_ESTATICOS and USUARIOS_ESTATICOS[email] == password:
        session['user'] = email
        return jsonify({"success": True})
        
    # 2. Si no es un usuario estático, buscar en la Base de Datos SQLite
    conn = sqlite3.connect('usuarios_ia.db')
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
    conn = sqlite3.connect('usuarios_ia.db')
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
    conn = sqlite3.connect('usuarios_ia.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO chats (id, user_email, titulo) VALUES (?, ?, ?)', (chat_id, session['user'], "Nueva conversación"))
    conn.commit()
    conn.close()
    return jsonify({"chat_id": chat_id})

@app.route('/obtener_mensajes')
def obtener_mensajes():
    chat_id = request.args.get('chat_id')
    conn = sqlite3.connect('usuarios_ia.db')
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

    # Control por si el usuario pide explícitamente GENERAR una imagen desde cero
    peticion_crear_img = any(palabra in mensaje_usuario.lower() for palabra in ["genera una imagen", "crea una imagen", "dibuja", "generar imagen"])
    
    if peticion_crear_img and not imagen_b64:
        respuesta_ia = "Actualmente mi núcleo en Groq me permite analizar y leer imágenes con precisión milimétrica, pero no tengo un modelo de generación como Midjourney o DALL-E integrado para crear imágenes desde cero. ¡Prueba subiendo una foto y te ayudaré a analizarla o modificar su lógica!"
        
        conn = sqlite3.connect('usuarios_ia.db')
        cursor = conn.cursor()
        cursor.execute('INSERT INTO mensajes (chat_id, role, content, image_data) VALUES (?, ?, ?, ?)', (chat_id, 'user', mensaje_usuario, None))
        cursor.execute('INSERT INTO mensajes (chat_id, role, content, image_data) VALUES (?, ?, ?, ?)', (chat_id, 'assistant', respuesta_ia, None))
        conn.commit()
        conn.close()
        return jsonify({"respuesta": respuesta_ia, "imagen": None})

    # 1. Guardar el mensaje del usuario en la Base de Datos local
    conn = sqlite3.connect('usuarios_ia.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO mensajes (chat_id, role, content, image_data) VALUES (?, ?, ?, ?)', 
                   (chat_id, 'user', mensaje_usuario, imagen_b64))
    conn.commit()

    # OBTENER EL TÍTULO DEL CHAT PARA DARLE CONTEXTO A TAVILY
    cursor.execute('SELECT titulo FROM chats WHERE id = ?', (chat_id,))
    fila_chat = cursor.fetchone()
    titulo_contexto = fila_chat[0] if fila_chat else ""

    # BÚSQUEDA EN TIEMPO REAL CON TAVILY (Con filtro inteligente para mensajes de confirmación)
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
            print(f"⚠️ Error al consultar Tavily: {str(e)}")
            contexto_internet = ""

    # 2. Generar el contexto histórico estructurado para la API
    cursor.execute('SELECT role, content, image_data FROM mensajes WHERE chat_id = ? ORDER BY id ASC', (chat_id,))
    historial_db = cursor.fetchall()
    
    system_prompt = (
        "Eres MAX, un asistente inteligente multimodal de última generación operando en el año 2026. "
        "Responde de forma clara, directa, fluida y con lógica natural. "
        "REGLA CRÍTICA DE CONVERSACIÓN:\n"
        "1. NUNCA te despidas (no digas '¡Hasta luego!', 'Adiós' o 'Nos vemos') a menos que el usuario diga explícitamente que se va o se despida primero.\n"
        "2. Si el usuario te responde con palabras de confirmación cortas como 'bien', 'ok', 'listo', 'entendido' o similares, "
        "entiende que está validando lo que dijiste. Responde de forma receptiva, breve y mantén la conversación abierta. "
        "Por ejemplo, puedes responder cosas como: '¡Excelente! ¿Hay algo más en lo que te pueda ayudar con esto?', 'Perfecto, ¿qué otra duda tienes?', o '¡Entendido! Dime qué más necesitas'."
    )
    if contexto_internet:
        system_prompt += f"\n\nUsa la información recolectada de internet de forma prioritaria para responder con números y datos reales y actuales: {contexto_internet}"

    payload_mensajes = [
        {
            "role": "system",
            "content": system_prompt
        }
    ]

    for role, content, img_data in historial_db:
        if img_data:
            payload_mensajes.append({
                "role": role,
                "content": [
                    {"type": "text", "text": content if content else "¿Qué hay en esta imagen?"},
                    {"type": "image_url", "image_url": {"url": img_data}}
                ]
            })
        else:
            payload_mensajes.append({
                "role": role,
                "content": content
            })

    # 3. Selección de modelos VIGENTES de Groq
    if imagen_b64:
        modelo_ejecucion = "llama-3.2-11b-vision-instruct"
    else:
        modelo_ejecucion = "llama-3.1-8b-instant" if modelo_seleccionado == 'flash' else "llama-3.3-70b-versatile"

    try:
        # 4. Solicitud al entorno Cloud de Groq
        completion = client.chat.completions.create(
            model=modelo_ejecucion,
            messages=payload_mensajes,
            temperature=0.5,
            max_tokens=1024
        )
        respuesta_ia = completion.choices[0].message.content
    except Exception as e:
        respuesta_ia = f"Error del núcleo de control multimodal: {str(e)}"

    # 5. Guardar la respuesta de la IA en la BD
    cursor.execute('INSERT INTO mensajes (chat_id, role, content, image_data) VALUES (?, ?, ?, ?)', 
                   (chat_id, 'assistant', respuesta_ia, None))
    conn.commit()

    # 6. Actualizar dinámicamente el título del chat si es nuevo y tiene contenido real
    cursor.execute('SELECT COUNT(*) FROM mensajes WHERE chat_id = ?', (chat_id,))
    if cursor.fetchone()[0] <= 3 and mensaje_usuario and not es_mensaje_vacio:
        titulo_corto = mensaje_usuario[:25] + "..." if len(mensaje_usuario) > 25 else mensaje_usuario
        cursor.execute('UPDATE chats SET titulo = ? WHERE id = ?', (titulo_corto, chat_id))
        conn.commit()

    conn.close()
    return jsonify({"respuesta": respuesta_ia, "imagen": None})

# ==========================================
# RUTA PARA GENERAR IMÁGENES (NUEVA)
# ==========================================
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