from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import sqlite3
import requests
import os
import threading
import time
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Замените на случайный ключ

# Конфигурация Telegram бота
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', 'YOUR_BOT_TOKEN')
TELEGRAM_API_URL = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}'
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', 'YOUR_CHAT_ID')

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    # Таблица программ
    c.execute('''CREATE TABLE IF NOT EXISTS programs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  category TEXT NOT NULL,
                  description TEXT,
                  version TEXT,
                  download_link TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # Таблица сообщений от пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT NOT NULL,
                  email TEXT,
                  message TEXT NOT NULL,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  replied BOOLEAN DEFAULT FALSE)''')
    
    # Таблица администраторов
    c.execute('''CREATE TABLE IF NOT EXISTS admins
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  password_hash TEXT NOT NULL)''')
    
    # Добавляем тестового администратора (пароль: admin123)
    try:
        c.execute("INSERT INTO admins (username, password_hash) VALUES (?, ?)",
                 ('admin', 'pbkdf2:sha256:260000$...'))  # В реальности хешируйте пароль!
    except sqlite3.IntegrityError:
        pass
    
    conn.commit()
    conn.close()

# Функция отправки сообщения в Telegram
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

# Маршруты сайта
@app.route('/')
def index():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT * FROM programs ORDER BY created_at DESC LIMIT 6")
    programs = c.fetchall()
    conn.close()
    
    return render_template('index.html', programs=programs)

@app.route('/programs')
def programs():
    category = request.args.get('category', 'all')
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    
    if category == 'all':
        c.execute("SELECT * FROM programs ORDER BY name")
    else:
        c.execute("SELECT * FROM programs WHERE category = ? ORDER BY name", (category,))
    
    programs = c.fetchall()
    conn.close()
    
    return render_template('programs.html', programs=programs, category=category)

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        message = request.form['message']
        
        # Сохраняем в базу
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("INSERT INTO messages (name, email, message) VALUES (?, ?, ?)",
                 (name, email, message))
        conn.commit()
        conn.close()
        
        # Отправляем уведомление в Telegram
        telegram_msg = f"📩 <b>Новое сообщение от {name}</b>\n\n"
        telegram_msg += f"Email: {email}\n"
        telegram_msg += f"Сообщение: {message[:200]}..."
        
        # Запускаем в отдельном потоке, чтобы не блокировать ответ
        threading.Thread(target=send_telegram_message, 
                        args=(TELEGRAM_CHAT_ID, telegram_msg)).start()
        
        return render_template('contact.html', success=True)
    
    return render_template('contact.html', success=False)

# Админ-панель
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        # Простая проверка (в реальном приложении используйте хеширование!)
        if username == 'admin' and password == 'admin123':
            session['admin_logged_in'] = True
            return redirect(url_for('admin_dashboard'))
        
        return render_template('admin_login.html', error=True)
    
    return render_template('admin_login.html', error=False)

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    conn = sqlite3.connect('database.db')
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

@app.route('/admin/programs')
def admin_programs():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("SELECT * FROM programs ORDER BY created_at DESC")
    programs = c.fetchall()
    conn.close()
    
    return render_template('admin_programs.html', programs=programs)

@app.route('/admin/add-program', methods=['GET', 'POST'])
def add_program():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    if request.method == 'POST':
        name = request.form['name']
        category = request.form['category']
        description = request.form['description']
        version = request.form['version']
        download_link = request.form['download_link']
        
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("INSERT INTO programs (name, category, description, version, download_link) VALUES (?, ?, ?, ?, ?)",
                 (name, category, description, version, download_link))
        conn.commit()
        conn.close()
        
        # Уведомление в Telegram о новой программе
        telegram_msg = f"🆕 <b>Добавлена новая программа!</b>\n\n"
        telegram_msg += f"<b>{name}</b> v{version}\n"
        telegram_msg += f"Категория: {category}\n"
        telegram_msg += f"Описание: {description[:100]}...\n\n"
        telegram_msg += f"Скачать: {download_link}"
        
        threading.Thread(target=send_telegram_message, 
                        args=(TELEGRAM_CHAT_ID, telegram_msg)).start()
        
        return redirect(url_for('admin_programs'))
    
    return render_template('add_program.html')

# Webhook для Telegram бота
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    
    if 'message' in data:
        message = data['message']
        chat_id = message['chat']['id']
        text = message.get('text', '').lower()
        
        if text == '/start':
            send_telegram_message(chat_id, 
                "👋 Привет! Я бот для сайта PrankVzlom.\n\n"
                "Доступные команды:\n"
                "/programs - Список программ\n"
                "/contact - Связаться с нами\n"
                "/help - Помощь")
        
        elif text == '/programs':
            conn = sqlite3.connect('database.db')
            c = conn.cursor()
            c.execute("SELECT name, category, version FROM programs ORDER BY name")
            programs = c.fetchall()
            conn.close()
            
            response = "📦 <b>Доступные программы:</b>\n\n"
            for program in programs:
                response += f"• {program[0]} v{program[2]} ({program[1]})\n"
            
            send_telegram_message(chat_id, response)
        
        elif text == '/contact':
            send_telegram_message(chat_id,
                "📞 <b>Свяжитесь с нами:</b>\n\n"
                "Напишите нам на сайте: https://your-site.com/contact\n"
                "Или ответьте на это сообщение, и мы вам ответим!")
    
    return 'OK'

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)