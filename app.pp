from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
import os
import threading
import urllib.parse as urlparse
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key')

# Конфигурация базы данных
DATABASE_URL = os.environ.get('DATABASE_URL')

# Конфигурация Telegram бота
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
TELEGRAM_API_URL = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}'
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

def get_connection():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn

def init_db():
    conn = get_connection()
    c = conn.cursor()
    
    # Таблица программ
    c.execute('''
        CREATE TABLE IF NOT EXISTS programs (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            category VARCHAR(100) NOT NULL,
            description TEXT,
            version VARCHAR(50),
            download_link TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Таблица сообщений
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            email VARCHAR(255),
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            replied BOOLEAN DEFAULT FALSE
        )
    ''')
    
    # Таблица администраторов (простая версия)
    c.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id SERIAL PRIMARY KEY,
            username VARCHAR(100) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL
        )
    ''')
    
    # Добавляем тестового администратора
    try:
        c.execute(
            "INSERT INTO admins (username, password_hash) VALUES (%s, %s)",
            ('admin', 'pbkdf2:sha256:260000$...')  # В реальности хешируйте пароль!
        )
    except psycopg2.IntegrityError:
        pass
    
    conn.commit()
    conn.close()

def send_telegram_message(chat_id, text):
    try:
        url = f'{TELEGRAM_API_URL}/sendMessage'
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML'
        }
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")
        return False

@app.route('/')
def index():
    conn = get_connection()
    c = conn.cursor(cursor_factory=RealDictCursor)
    c.execute("SELECT * FROM programs ORDER BY created_at DESC LIMIT 6")
    programs = c.fetchall()
    conn.close()
    
    return render_template('index.html', programs=programs)

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        message = request.form['message']
        
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "INSERT INTO messages (name, email, message) VALUES (%s, %s, %s)",
            (name, email, message)
        )
        conn.commit()
        conn.close()
        
        # Уведомление в Telegram
        telegram_msg = f"📩 <b>Новое сообщение от {name}</b>\n\n"
        telegram_msg += f"Email: {email or 'Не указан'}\n"
        telegram_msg += f"Сообщение: {message[:200]}..."
        
        threading.Thread(
            target=send_telegram_message,
            args=(TELEGRAM_CHAT_ID, telegram_msg)
        ).start()
        
        return render_template('contact.html', success=True)
    
    return render_template('contact.html', success=False)

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    conn = get_connection()
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM programs")
    program_count = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM messages WHERE replied = FALSE")
    unread_messages = c.fetchone()[0]
    
    c.execute("SELECT * FROM messages ORDER BY created_at DESC LIMIT 10")
    recent_messages = c.fetchall()
    
    conn.close()
    
    return render_template('admin_dashboard.html',
                         program_count=program_count,
                         unread_messages=unread_messages,
                         messages=recent_messages)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    
    if 'message' in data:
        message = data['message']
        chat_id = message['chat']['id']
        text = message.get('text', '').lower()
        
        if text == '/start':
            send_telegram_message(chat_id, 
                "👋 Привет! Я бот для сайта.\n\n"
                "Доступные команды:\n"
                "/programs - Список программ\n"
                "/contact - Связаться с нами")
        
        elif text == '/programs':
            conn = get_connection()
            c = conn.cursor()
            c.execute("SELECT name, category, version FROM programs ORDER BY name")
            programs = c.fetchall()
            conn.close()
            
            response = "📦 <b>Доступные программы:</b>\n\n"
            for program in programs:
                response += f"• {program[0]} v{program[2]} ({program[1]})\n"
            
            send_telegram_message(chat_id, response)
    
    return 'OK'

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
