import os
import sqlite3
import uuid
import random
import smtplib
from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
from openai import OpenAI

app = Flask(__name__)
app.secret_key = "clave_secreta_para_sesiones_max"
# Habilitamos CORS para que tu frontend en Netlify pueda hacer peticiones
CORS(app, resources={r"/*": {"origins": "*"}})

# ==========================================
# CONFIGURACIÓN
# ==========================================
API_KEY = "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"

client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=API_KEY
)

# ==========================================
# BASE DE DATOS - INICIALIZACIÓN
# ==========================================
def init_db():
    conn = sqlite3.connect('usuarios_ia.db')
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
            FOREIGN KEY(chat_id) REFERENCES chats(id)
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

# ==========================================
# RUTAS DE AUTENTICACIÓN
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
        cursor.execute('INSERT INTO usuarios (email, password, verificado) VALUES (?, ?, 1)', (email, password))
        conn.commit()
        return jsonify({"success": True})
    except sqlite3.IntegrityError:
        return jsonify({"success": False, "error": "El usuario ya existe"})
    finally:
        conn.close()

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('pass')
    
    conn = sqlite3.connect('usuarios_ia.db')
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM usuarios WHERE email = ? AND password = ?', (email, password))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        session['user'] = email
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Credenciales inválidas"})

@app.route('/logout')
def logout():
    session.pop('user', None)
    return jsonify({"success": True})

# ==========================================
# ELIMINAR CUENTA
# ==========================================
@app.route('/eliminar_cuenta', methods=['POST'])
def eliminar_cuenta():
    if 'user' not in session:
        return jsonify({"error": "No autorizado"}), 401
    
    email_usuario = session['user']
    conn = sqlite3.connect('usuarios_ia.db')
    cursor = conn.cursor()
    try:
        cursor.execute('SELECT id FROM chats WHERE user_email = ?', (email_usuario,))
        chats = cursor.fetchall()
        for chat_id in chats:
            cursor.execute('DELETE FROM mensajes WHERE chat_id = ?', (chat_id[0],))
        cursor.execute('DELETE FROM chats WHERE user_email = ?', (email_usuario,))
        cursor.execute('DELETE FROM usuarios WHERE email = ?', (email_usuario,))
        conn.commit()
        session.pop('user', None)
        return jsonify({"success": True, "message": "Cuenta eliminada"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})
    finally:
        conn.close()

# ==========================================
# GESTIÓN DE CHATS
# ==========================================
@app.route('/obtener_chats')
def obtener_chats():
    if 'user' not in session: return jsonify([])
    conn = sqlite3.connect('usuarios_ia.db')
    cursor = conn.cursor()
    cursor.execute('SELECT id, titulo FROM chats WHERE user_email = ?', (session['user'],))
    chats = [{"id": row[0], "titulo": row[1]} for row in cursor.fetchall()]
    conn.close()
    return jsonify(chats)

@app.route('/crear_chat', methods=['POST'])
def crear_chat():
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
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
    cursor.execute('SELECT role, content FROM mensajes WHERE chat_id = ? ORDER BY id ASC', (chat_id,))
    mensajes = [{"role": row[0], "content": row[1]} for row in cursor.fetchall()]
    conn.close()
    return jsonify(mensajes)

# ==========================================
# NÚCLEO (PROCESAMIENTO)
# ==========================================
@app.route('/preguntar', methods=['POST'])
def preguntar():
    if 'user' not in session: return jsonify({"error": "No autorizado"}), 401
        
    data = request.json
    mensaje_usuario = data.get('mensaje', '').strip()
    chat_id = data.get('chat_id')
    modelo_seleccionado = data.get('modelo', 'flash') 

    conn = sqlite3.connect('usuarios_ia.db')
    cursor = conn.cursor()
    cursor.execute('INSERT INTO mensajes (chat_id, role, content) VALUES (?, ?, ?)', (chat_id, 'user', mensaje_usuario))
    conn.commit()

    cursor.execute('SELECT role, content FROM mensajes WHERE chat_id = ? ORDER BY id ASC', (chat_id,))
    historial_db = cursor.fetchall()
    
    payload_mensajes = [{"role": "system", "content": "Eres MAX, un asistente inteligente. Si preguntan por tu creador, responde: Ruben Maza estudiante de 14 años que esta empezando en el mundo de la programacion."}]
    for role, content in historial_db:
        payload_mensajes.append({"role": role, "content": content})

    modelo_ejecucion = "llama-3.1-8b-instant" if modelo_seleccionado == 'flash' else "llama-3.3-70b-versatile"

    try:
        completion = client.chat.completions.create(model=modelo_ejecucion, messages=payload_mensajes, temperature=0.7, max_tokens=1024)
        respuesta_ia = completion.choices[0].message.content
    except Exception as e:
        respuesta_ia = f"Error: {str(e)}"

    cursor.execute('INSERT INTO mensajes (chat_id, role, content) VALUES (?, ?, ?)', (chat_id, 'assistant', respuesta_ia))
    conn.commit()
    cursor.close()
    conn.close()
    return jsonify({"respuesta": respuesta_ia})

if __name__ == '__main__':
    # Usamos la variable de entorno PORT si existe (necesario para la nube)
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)