from flask import Flask, request, jsonify
import pandas as pd
import random
import os
import base64
import json
import subprocess
import tempfile
import time
from threading import Thread
from io import BytesIO
from PIL import Image
import math

app = Flask(__name__)

# Создаем папку для загруженных фото если её нет
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Путь к стороннему скрипту анализа повреждений
DAMAGE_ANALYSIS_SCRIPT = 'cvmain/test.py'

# Глобальная переменная для отслеживания статуса парсинга
PARSING_STATUS = {
    'in_progress': False,
    'last_completed': None,
    'current_task': None
}

# Глобальная переменная для данных Excel
CAR_PRICES_DF = None

# Базовые ставки за ремонт вмятин (руб/см²)
BASE_DENT_REPAIR_RATES = {
    'сталь': {
        'легкий': 150,    # руб/см² за легкие вмятины
        'средний': 250,   # руб/см² за средние вмятины  
        'тяжелый': 400    # руб/см² за тяжелые вмятины
    },
    'алюминий': {
        'легкий': 200,    # +33% к стали
        'средний': 350,   # +40% к стали
        'тяжелый': 550    # +37% к стали
    },
    'магниевый сплав': {
        'легкий': 300,    # +100% к стали
        'средний': 500,   # +100% к стали
        'тяжелый': 800    # +100% к стали (чаще требуется замена)
    },
    'композит': {
        'легкий': 400,    # сложный материал
        'средний': 700,   # требует спецоборудования
        'тяжелый': 1200   # обычно только замена
    }
}

# Коэффициенты стоимости ремонта в зависимости от типа повреждения
REPAIR_COST_MULTIPLIERS = {
    'вмятина': {
        'легкий': 0.3,   # Небольшая вмятина - легкий ремонт
        'средний': 0.5,  # Средняя вмятина 
        'тяжелый': 0.8   # Сильная вмятина, почти не ремонтируется
    },
    'царапина': {
        'легкий': 0.2,   # Поверхностная царапина
        'средний': 0.4,  # Глубокая царапина
        'тяжелый': 0.7   # Очень глубокая царапина до металла
    },
    'разрыв': {
        'легкий': 0.6,
        'средний': 0.9,
        'тяжелый': 1.2   # Разрыв обычно требует замены
    }
}

# Множители сложности для разных материалов
MATERIAL_COMPLEXITY_MULTIPLIERS = {
    'сталь': 1.0,
    'алюминий': 1.4,      # +40% к стоимости
    'магниевый сплав': 2.0, # +100% к стоимости
    'композит': 2.5,      # +150% к стоимости
    'пластик': 0.8        # -20% к стоимости (легче ремонтировать)
}

# Минимальные и максимальные площади повреждений (см²)
MIN_DAMAGE_AREA = 10  # минимальная площадь повреждения
MAX_DAMAGE_AREA = 500 # максимальная площадь повреждения

def load_repair_prices_from_excel(file_path='huh_result.xlsx'):
    """
    Загружает цены на ремонт из Excel файла
    Ожидаемая структура файла:
    - Колонки: 'марка', 'модель', 'деталь', 'площадь детали', 'материал детали', 'цена', 'ссылка'
    """
    global CAR_PRICES_DF
    try:
        if not os.path.exists(file_path):
            print(f"❌ Файл {file_path} не найден")
            CAR_PRICES_DF = None
            return None
        
        df = pd.read_excel(file_path)
        print(f"✅ Файл загружен, колонки: {list(df.columns)}")
        
        # Проверяем наличие необходимых колонок
        required_columns = ['марка', 'модель', 'деталь', 'площадь детали', 'материал детали', 'цена']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            print(f"❌ Отсутствуют колонки: {missing_columns}")
            CAR_PRICES_DF = None
            raise ValueError(f"Отсутствуют колонки: {missing_columns}")
        
        # Преобразуем все данные в строки чтобы избежать проблем с сортировкой
        df['марка'] = df['марка'].astype(str).str.strip()
        df['модель'] = df['модель'].astype(str).str.strip()
        df['деталь'] = df['деталь'].astype(str).str.strip()
        df['площадь детали'] = df['площадь детали'].astype(str).str.strip()
        df['материал детали'] = df['материал детали'].astype(str).str.strip()
        
        # Обрабатываем ссылку если она есть
        if 'ссылка' in df.columns:
            df['ссылка'] = df['ссылка'].astype(str).str.strip()
            # Заменяем NaN и 'nan' на пустые строки
            df['ссылка'] = df['ссылка'].replace(['nan', 'None', 'NaN'], '')
        else:
            df['ссылка'] = ''
        
        # Убедимся что цена - число
        df['цена'] = pd.to_numeric(df['цена'], errors='coerce').fillna(0).astype(int)
        
        CAR_PRICES_DF = df
        print(f"✅ Успешно загружено {len(df)} записей из {file_path}")
        print(f"📊 Пример данных:")
        print(df.head(3))
        return df
    
    except Exception as e:
        print(f"❌ Ошибка загрузки Excel файла: {e}")
        CAR_PRICES_DF = None
        return None

# Загружаем данные при старте сервера
load_repair_prices_from_excel()

def get_unique_brands():
    """Получает уникальные марки автомобилей"""
    global CAR_PRICES_DF
    if CAR_PRICES_DF is None:
        return []
    try:
        brands = CAR_PRICES_DF['марка'].unique().tolist()
        print(f"🔧 Найдены марки: {brands}")
        return sorted(brands)
    except Exception as e:
        print(f"❌ Ошибка получения марок: {e}")
        return []

def get_models_by_brand(brand):
    """Получает модели по марке"""
    global CAR_PRICES_DF
    if CAR_PRICES_DF is None:
        return []
    try:
        models = CAR_PRICES_DF[CAR_PRICES_DF['марка'] == brand]['модель'].unique().tolist()
        print(f"🔧 Для марки '{brand}' найдены модели: {models}")
        return sorted(models)
    except Exception as e:
        print(f"❌ Ошибка при получении моделей для марки {brand}: {e}")
        return []

def get_all_parts_for_model(brand, model):
    """
    Получает все уникальные детали для конкретной марки и модели из базы данных
    """
    global CAR_PRICES_DF
    try:
        if CAR_PRICES_DF is None:
            return []
        
        parts = CAR_PRICES_DF[
            (CAR_PRICES_DF['марка'] == brand) & 
            (CAR_PRICES_DF['модель'] == model)
        ]['деталь'].unique().tolist()
        
        print(f"🔧 Для {brand} {model} найдено {len(parts)} уникальных деталей")
        return parts
        
    except Exception as e:
        print(f"❌ Ошибка получения деталей для модели: {e}")
        return []

def find_car_parts(brand, model):
    """
    Ищет детали для конкретной марки и модели в таблице
    """
    global CAR_PRICES_DF
    try:
        if CAR_PRICES_DF is None:
            return pd.DataFrame()
            
        # Фильтруем детали для указанной марки и модели
        matching_parts = CAR_PRICES_DF[
            (CAR_PRICES_DF['марка'] == brand) & 
            (CAR_PRICES_DF['модель'] == model)
        ]
        
        print(f"🔧 Для {brand} {model} найдено {len(matching_parts)} деталей")
        return matching_parts
    
    except Exception as e:
        print(f"❌ Ошибка поиска деталей: {e}")
        return pd.DataFrame()

def analyze_damage_with_ai(photo_path, brand, model):
    """
    Вызывает сторонний скрипт для анализа повреждений на фото
    Возвращает данные с типами повреждений (вмятина/царапина/разрыв) и размерами
    """
    try:
        if not os.path.exists(DAMAGE_ANALYSIS_SCRIPT):
            print(f"❌ Скрипт анализа повреждений не найден: {DAMAGE_ANALYSIS_SCRIPT}")
            # Возвращаем тестовые данные для демонстрации
            return {
                'damages': [
                    {
                        'part': 'капот',
                        'damage_type': 'вмятина',
                        'severity': 'средний',
                        'confidence': 0.85,
                        'location': 'центр',
                        'area_cm2': 45,  # площадь повреждения в см²
                        'depth': 'средняя'  # глубина повреждения
                    },
                    {
                        'part': 'дверь передняя левая',
                        'damage_type': 'царапина',
                        'severity': 'легкий',
                        'confidence': 0.92,
                        'location': 'низ',
                        'area_cm2': 15,  # площадь повреждения в см²
                        'depth': 'поверхностная'
                    },
                    {
                        'part': 'бампер передний',
                        'damage_type': 'вмятина',
                        'severity': 'тяжелый',
                        'confidence': 0.78,
                        'location': 'правый угол',
                        'area_cm2': 120,  # площадь повреждения в см²
                        'depth': 'глубокая'
                    }
                ]
            }
        
        print(f"🔍 Запускаем анализ повреждений для {brand} {model}")
        
        temp_dir = tempfile.gettempdir()
        output_file = os.path.join(temp_dir, f"damage_analysis_{random.randint(1000, 9999)}.json")
        
        # Запускаем сторонний скрипт
        result = subprocess.run([
            'python', DAMAGE_ANALYSIS_SCRIPT,
            '--image', photo_path,
            '--brand', brand,
            '--model', model,
            '--output', output_file
        ], capture_output=True, text=True, timeout=120)
        
        if result.returncode == 0:
            print("✅ Анализ повреждений завершен успешно")
            
            # Читаем результат из JSON файла
            if os.path.exists(output_file):
                with open(output_file, 'r', encoding='utf-8') as f:
                    analysis_result = json.load(f)
                print(f"📊 Результат анализа: {analysis_result}")
                
                # Удаляем временный файл
                os.remove(output_file)
                return analysis_result
            else:
                print("❌ Файл с результатами анализа не создан")
                return None
        else:
            print(f"❌ Ошибка при анализе повреждений: {result.stderr}")
            return None
            
    except subprocess.TimeoutExpired:
        print("❌ Таймаут при анализе повреждений")
        return None
    except Exception as e:
        print(f"❌ Ошибка при вызове скрипта анализа: {e}")
        return None

def calculate_dent_repair_cost(damage_area, material, severity, damage_type):
    """
    Рассчитывает стоимость ремонта вмятины на основе площади, материала и сложности
    """
    try:
        # Нормализуем материал
        material_lower = material.lower()
        
        # Определяем базовый материал для расчета
        if 'алюмин' in material_lower:
            base_material = 'алюминий'
        elif 'магн' in material_lower or 'сплав' in material_lower:
            base_material = 'магниевый сплав'
        elif 'композит' in material_lower or 'карбон' in material_lower:
            base_material = 'композит'
        elif 'пластик' in material_lower or 'полимер' in material_lower:
            base_material = 'пластик'
        else:
            base_material = 'сталь'  # по умолчанию
        
        # Для пластика используем специальную логику
        if base_material == 'пластик':
            if damage_type == 'вмятина':
                # Для пластиковых вмятин - нагрев и выправление
                base_rate = 100  # руб/см²
                if severity == 'тяжелый':
                    base_rate = 200  # сложные случаи
            else:
                base_rate = 150  # для царапин на пластике
        else:
            # Для металлов используем базовые ставки
            base_rate = BASE_DENT_REPAIR_RATES[base_material][severity]
        
        # Применяем множитель сложности материала
        material_multiplier = MATERIAL_COMPLEXITY_MULTIPLIERS.get(base_material, 1.0)
        
        # Рассчитываем базовую стоимость
        base_cost = damage_area * base_rate * material_multiplier
        
        # Корректируем в зависимости от типа повреждения
        damage_multiplier = REPAIR_COST_MULTIPLIERS.get(damage_type, {}).get(severity, 1.0)
        
        final_cost = base_cost * damage_multiplier
        
        # Округляем до сотен
        final_cost = math.ceil(final_cost / 100) * 100
        
        return int(final_cost), base_material
        
    except Exception as e:
        print(f"❌ Ошибка расчета стоимости ремонта: {e}")
        return 0, 'сталь'

def calculate_repair_cost(damage_analysis, brand, model):
    """
    Рассчитывает стоимость ремонта и замены на основе анализа повреждений
    """
    global CAR_PRICES_DF
    try:
        if not damage_analysis or 'damages' not in damage_analysis:
            return []
        
        car_parts = find_car_parts(brand, model)
        if car_parts.empty:
            return []
        
        damages_with_costs = []
        
        for damage in damage_analysis['damages']:
            damaged_part = damage.get('part', '')
            damage_type = damage.get('damage_type', 'вмятина')
            severity = damage.get('severity', 'средний')
            damage_area = damage.get('area_cm2', random.randint(10,100))  # площадь повреждения в см²
            
            # Ограничиваем площадь повреждения разумными пределами
            damage_area = max(MIN_DAMAGE_AREA, min(damage_area, MAX_DAMAGE_AREA))
            
            # Ищем деталь в таблице
            part_data = car_parts[car_parts['деталь'] == damaged_part]
            
            if not part_data.empty:
                replacement_cost = int(part_data.iloc[0]['цена'])  # Стоимость полной замены
                part_material = str(part_data.iloc[0]['материал детали'])
                part_area = str(part_data.iloc[0]['площадь детали'])
                
                # Рассчитываем стоимость ремонта на основе материала и площади повреждения
                repair_cost, detected_material = calculate_dent_repair_cost(
                    damage_area, part_material, severity, damage_type
                )
                
                # Для тяжелых повреждений на сложных материалах ремонт может быть нецелесообразен
                if (severity == 'тяжелый' and 
                    detected_material in ['магниевый сплав', 'композит']):
                    repair_cost = min(repair_cost, replacement_cost)
                
                # Получаем ссылку если она есть
                link = part_data.iloc[0].get('ссылка', '')
                if pd.isna(link) or link in ['', 'nan', 'None']:
                    link = ''
                
                # Определяем рекомендацию
                if repair_cost < replacement_cost * 0.7:  # если ремонт дешевле замены на 30%
                    recommendation = "ремонт"
                    savings = replacement_cost - repair_cost
                else:
                    recommendation = "замена"
                    savings = 0
                
                damages_with_costs.append({
                    "part": damaged_part,
                    "area": part_area,
                    "material": part_material,
                    "detected_material": detected_material,  # определенный материал для расчета
                    "damage_type": damage_type,
                    "severity": severity,
                    "confidence": float(damage.get('confidence', 0)),
                    "location": damage.get('location', ''),
                    "damage_area_cm2": damage_area,  # площадь повреждения
                    "damage_depth": damage.get('depth', 'не определена'),
                    "repair_cost": repair_cost,
                    "replacement_cost": replacement_cost,
                    "recommendation": recommendation,
                    "savings": savings,
                    "link": link
                })
        
        return damages_with_costs
        
    except Exception as e:
        print(f"❌ Ошибка расчета стоимости: {e}")
        return []

def save_uploaded_photo(photo_data):
    """Сохраняет загруженное фото и возвращает путь к файлу"""
    try:
        if not photo_data:
            return None
            
        # Убираем префикс data:image если есть
        if ',' in photo_data:
            photo_data = photo_data.split(',')[1]
        
        # Декодируем base64
        image_data = base64.b64decode(photo_data)
        
        # Создаем имя файла
        filename = f"car_photo_{random.randint(1000, 9999)}.jpg"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        
        # Сохраняем изображение
        with open(filepath, 'wb') as f:
            f.write(image_data)
        
        print(f"✅ Фото сохранено: {filepath}")
        return filepath
        
    except Exception as e:
        print(f"❌ Ошибка сохранения фото: {e}")
        return None

# ========== ФУНКЦИИ ПАРСИНГА ==========

def parsing_complete_callback(result):
    """
    Callback функция, вызываемая при завершении парсинга
    """
    global CAR_PRICES_DF
    try:
        if result['success']:
            print(f"✅ Автопарсинг завершен для {result['brand']} {result['model']}")
            print(f"📊 Обработано деталей: {result['parsed_parts']}")
            print(f"💰 Найдено цен: {result['found_prices']}")
            
            # Перезагружаем данные из Excel
            CAR_PRICES_DF = load_repair_prices_from_excel()
            print("🔄 Данные Excel перезагружены с актуальными ценами")
        else:
            print(f"❌ Ошибка автопарсинга: {result['error']}")
            
    except Exception as e:
        print(f"❌ Ошибка в callback парсинга: {e}")

def start_auto_parsing(brand, model, damaged_parts):
    """
    Запускает автоматический парсинг в отдельном потоке
    """
    def parsing_thread():
        global PARSING_STATUS
        try:
            PARSING_STATUS['in_progress'] = True
            PARSING_STATUS['current_task'] = f"{brand} {model}"
            
            # Импортируем здесь чтобы избежать циклических импортов
            from parser import auto_parse_damages, update_excel_with_parsed_data
            
            # Запускаем парсинг
            parsed_df = auto_parse_damages(brand, model, damaged_parts)
            
            # Обновляем Excel файл
            update_excel_with_parsed_data(parsed_df)
            
            # Преобразуем pandas типы в стандартные Python типы для JSON
            found_prices = int((parsed_df['цена'] > 0).sum())  # Преобразуем в int
            
            # Обновляем статус
            PARSING_STATUS['in_progress'] = False
            PARSING_STATUS['last_completed'] = {
                'brand': brand,
                'model': model,
                'timestamp': time.time(),
                'parsed_parts': len(damaged_parts),
                'found_prices': found_prices
            }
            PARSING_STATUS['current_task'] = None
            
            # Вызываем callback
            parsing_complete_callback({
                'success': True,
                'brand': brand,
                'model': model,
                'parsed_parts': len(damaged_parts),
                'found_prices': found_prices,
                'dataframe': parsed_df
            })
                
        except Exception as e:
            PARSING_STATUS['in_progress'] = False
            PARSING_STATUS['current_task'] = None
            print(f"❌ Ошибка в потоке парсинга: {e}")
            parsing_complete_callback({
                'success': False,
                'error': str(e)
            })
    
    # Запускаем в отдельном потоке
    thread = Thread(target=parsing_thread)
    thread.daemon = True
    thread.start()
    
    print(f"🚀 Запущен автоматический парсинг для {brand} {model}")
    return thread

def wait_for_parsing_completion(timeout=300):
    """
    Ожидает завершения парсинга с таймаутом
    """
    start_time = time.time()
    while PARSING_STATUS['in_progress']:
        if time.time() - start_time > timeout:
            print("❌ Таймаут ожидания парсинга")
            return False
        time.sleep(2)
        print("⏳ Ожидаем завершения парсинга...")
    return True

# ========== МАРШРУТЫ FLASK ==========

@app.route('/')
def index():
    return '''
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Оценка стоимости ремонта автомобиля</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                max-width: 1000px;
                margin: 50px auto;
                padding: 20px;
                background-color: #f5f5f5;
            }
            .container {
                background: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            .form-group {
                margin-bottom: 20px;
                position: relative;
            }
            label {
                display: block;
                margin-bottom: 8px;
                font-weight: bold;
                color: #333;
            }
            input, select {
                width: 100%;
                padding: 12px;
                border: 2px solid #ddd;
                border-radius: 6px;
                font-size: 16px;
                transition: border-color 0.3s;
                box-sizing: border-box;
            }
            input:focus, select:focus {
                outline: none;
                border-color: #007bff;
            }
            button {
                background-color: #007bff;
                color: white;
                padding: 15px 30px;
                border: none;
                border-radius: 6px;
                cursor: pointer;
                font-size: 16px;
                width: 100%;
                transition: background-color 0.3s;
            }
            button:hover {
                background-color: #0056b3;
            }
            button:disabled {
                background-color: #6c757d;
                cursor: not-allowed;
            }
            .result {
                margin-top: 25px;
                padding: 20px;
                border-radius: 6px;
                display: none;
            }
            .success {
                background-color: #d4edda;
                border: 1px solid #c3e6cb;
                color: #155724;
            }
            .error {
                background-color: #f8d7da;
                border: 1px solid #f5c6cb;
                color: #721c24;
            }
            .loading {
                display: none;
                text-align: center;
                margin: 20px 0;
                padding: 15px;
            }
            .damage-item {
                background: #f8f9fa;
                margin: 20px 0;
                padding: 25px;
                border-radius: 10px;
                border-left: 4px solid #007bff;
            }
            .cost-comparison {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
                margin: 20px 0;
                padding: 20px;
                background: white;
                border-radius: 10px;
                border: 2px solid #e9ecef;
            }
            .repair-cost {
                text-align: center;
                padding: 20px;
                background: #e8f5e8;
                border-radius: 8px;
                border: 2px solid #28a745;
            }
            .replacement-cost {
                text-align: center;
                padding: 20px;
                background: #fff3cd;
                border-radius: 8px;
                border: 2px solid #ffc107;
            }
            .cost-value {
                font-size: 1.6em;
                font-weight: bold;
                margin: 15px 0;
            }
            .repair-value {
                color: #28a745;
            }
            .replacement-value {
                color: #856404;
            }
            .recommendation {
                text-align: center;
                padding: 15px;
                margin: 15px 0;
                border-radius: 8px;
                font-weight: bold;
                font-size: 1.1em;
            }
            .recommend-repair {
                background: #d4edda;
                color: #155724;
                border: 2px solid #c3e6cb;
            }
            .recommend-replacement {
                background: #f8d7da;
                color: #721c24;
                border: 2px solid #f5c6cb;
            }
            .total-cost {
                font-size: 1.6em;
                font-weight: bold;
                color: #28a745;
                text-align: center;
                margin-top: 30px;
                padding: 25px;
                background: #e8f5e8;
                border-radius: 10px;
                border: 3px solid #28a745;
            }
            .part-details {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 15px;
                margin-top: 15px;
                font-size: 0.95em;
            }
            .detail-item {
                color: #666;
                padding: 8px 0;
                border-bottom: 1px solid #eee;
            }
            .damage-details {
                background: #e7f3ff;
                padding: 15px;
                border-radius: 8px;
                margin: 15px 0;
            }
            .damage-type-badge {
                display: inline-block;
                padding: 6px 15px;
                border-radius: 20px;
                font-size: 0.9em;
                font-weight: bold;
                margin-left: 10px;
            }
            .dent-badge {
                background: #007bff;
                color: white;
            }
            .scratch-badge {
                background: #28a745;
                color: white;
            }
            .break-badge {
                background: #dc3545;
                color: white;
            }
            .material-badge {
                display: inline-block;
                padding: 4px 12px;
                border-radius: 15px;
                font-size: 0.8em;
                font-weight: bold;
                margin-left: 8px;
            }
            .steel-badge {
                background: #6c757d;
                color: white;
            }
            .aluminum-badge {
                background: #17a2b8;
                color: white;
            }
            .magnesium-badge {
                background: #e83e8c;
                color: white;
            }
            .composite-badge {
                background: #6f42c1;
                color: white;
            }
            .plastic-badge {
                background: #fd7e14;
                color: white;
            }
            .autocomplete-list {
                position: absolute;
                border: 1px solid #d4d4d4;
                border-bottom: none;
                border-top: none;
                z-index: 99;
                top: 100%;
                left: 0;
                right: 0;
                background: white;
                max-height: 200px;
                overflow-y: auto;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                display: none;
            }
            .autocomplete-item {
                padding: 10px;
                cursor: pointer;
                border-bottom: 1px solid #d4d4d4;
                background: white;
            }
            .autocomplete-item:hover {
                background-color: #e9e9e9;
            }
            .autocomplete-active {
                background-color: #007bff !important;
                color: white;
            }
            .debug-info {
                margin-top: 10px;
                padding: 10px;
                background: #f8f9fa;
                border-radius: 5px;
                font-size: 12px;
                color: #666;
            }
            .photo-upload {
                border: 2px dashed #ddd;
                border-radius: 6px;
                padding: 20px;
                text-align: center;
                cursor: pointer;
                transition: border-color 0.3s;
                margin-bottom: 15px;
            }
            .photo-upload:hover {
                border-color: #007bff;
            }
            .photo-upload.dragover {
                border-color: #007bff;
                background-color: #f0f8ff;
            }
            .photo-preview {
                max-width: 100%;
                max-height: 200px;
                margin-top: 10px;
                display: none;
                border-radius: 4px;
            }
            .remove-photo {
                background-color: #dc3545;
                color: white;
                border: none;
                padding: 5px 10px;
                border-radius: 4px;
                cursor: pointer;
                margin-top: 5px;
            }
            .remove-photo:hover {
                background-color: #c82333;
            }
            .upload-icon {
                font-size: 48px;
                color: #6c757d;
                margin-bottom: 10px;
            }
            .ai-analysis-badge {
                background: #17a2b8;
                color: white;
                padding: 4px 12px;
                border-radius: 12px;
                font-size: 0.9em;
                margin-left: 10px;
            }
            .part-link {
                display: inline-block;
                background: #007bff;
                color: white;
                padding: 8px 16px;
                border-radius: 6px;
                text-decoration: none;
                font-size: 0.95em;
                margin-top: 10px;
                transition: background-color 0.3s;
            }
            .part-link:hover {
                background: #0056b3;
            }
            .no-link {
                color: #6c757d;
                font-style: italic;
                font-size: 0.9em;
            }
            .parsing-status {
                background: #e7f3ff;
                padding: 12px;
                border-radius: 5px;
                margin: 15px 0;
                border-left: 4px solid #007bff;
            }
            .parsing-message {
                color: #0066cc;
                font-weight: bold;
                margin: 0;
            }
            .step-indicator {
                display: flex;
                justify-content: space-between;
                margin: 20px 0;
                position: relative;
            }
            .step {
                flex: 1;
                text-align: center;
                padding: 10px;
                background: #f8f9fa;
                border-radius: 5px;
                margin: 0 5px;
                font-weight: bold;
            }
            .step.active {
                background: #007bff;
                color: white;
            }
            .step.completed {
                background: #28a745;
                color: white;
            }
            .damage-area-info {
                background: #fff3cd;
                padding: 10px;
                border-radius: 5px;
                margin: 10px 0;
                font-size: 0.9em;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1 style="text-align: center; color: #333; margin-bottom: 30px;">
                🚗 AI Оценка стоимости ремонта автомобиля
            </h1>
            
            <div class="step-indicator">
                <div class="step" id="step1">1. Обновление данных</div>
                <div class="step" id="step2">2. Анализ фото</div>
                <div class="step" id="step3">3. Результат</div>
            </div>
            
            <div class="parsing-status" id="parsingStatus">
                <p class="parsing-message" id="parsingMessage">
                    🔄 Обновляем цены для этой модели...
                </p>
            </div>
            
            <form id="carForm">
                <div class="form-group">
                    <label for="brand">Марка автомобиля:</label>
                    <input type="text" id="brand" name="brand" required 
                           placeholder="Начните вводить марку..." autocomplete="off">
                    <div id="brandAutocomplete" class="autocomplete-list"></div>
                </div>
                
                <div class="form-group">
                    <label for="model">Модель автомобиля:</label>
                    <input type="text" id="model" name="model" required 
                           placeholder="Сначала выберите марку..." autocomplete="off" disabled>
                    <div id="modelAutocomplete" class="autocomplete-list"></div>
                </div>
                
                <div class="form-group">
                    <label for="photo">Загрузить фото повреждений <span style="color: #dc3545;">*</span>:</label>
                    <div class="photo-upload" id="photoUpload">
                        <div class="upload-icon">📷</div>
                        <div>Нажмите для выбора файла или перетащите фото сюда</div>
                        <div style="font-size: 12px; color: #666; margin-top: 5px;">
                            Поддерживаемые форматы: JPG, PNG, GIF (макс. 5MB)
                        </div>
                        <input type="file" id="photoInput" accept="image/*" style="display: none;">
                        <img id="photoPreview" class="photo-preview" alt="Предпросмотр фото">
                    </div>
                    <div style="font-size: 12px; color: #dc3545; margin-top: 5px;">
                        * Фото обязательно для AI анализа повреждений
                    </div>
                    <button type="button" id="removePhoto" class="remove-photo" style="display: none;">Удалить фото</button>
                </div>
                
                <button type="submit" id="submitBtn">🔍 Проанализировать повреждения и оценить стоимость</button>
            </form>
            
            <div class="debug-info" id="debugInfo">
                Статус: <span id="status">Загрузка...</span>
            </div>
            
            <div class="loading" id="loading">
                <p id="loadingMessage">🤖 AI анализирует повреждения на фото...</p>
                <p><small>Это может занять несколько секунд</small></p>
            </div>
            
            <div class="result" id="result"></div>
        </div>

        <script>
            let allBrands = [];
            let brandModels = {};
            let currentPhoto = null;

            // Загружаем список марок при загрузке страницы
            document.addEventListener('DOMContentLoaded', function() {
                console.log('Загружаем список марок...');
                fetch('/get-brands')
                    .then(response => response.json())
                    .then(data => {
                        console.log('Получены данные марок:', data);
                        if (data.success) {
                            allBrands = data.brands;
                            document.getElementById('status').textContent = `Загружено ${allBrands.length} марок`;
                            console.log('Марки загружены:', allBrands);
                        } else {
                            document.getElementById('status').textContent = 'Ошибка загрузки марок: ' + data.error;
                            console.error('Ошибка загрузки марок:', data.error);
                        }
                    })
                    .catch(error => {
                        document.getElementById('status').textContent = 'Ошибка сети при загрузке марок';
                        console.error('Ошибка сети:', error);
                    });

                // Запускаем проверку статуса парсинга
                setInterval(checkParsingStatus, 2000);
            });

            // Функция для проверки статуса парсинга
            function checkParsingStatus() {
                fetch('/parsing-status')
                    .then(response => response.json())
                    .then(data => {
                        const statusDiv = document.getElementById('parsingStatus');
                        if (data.in_progress) {
                            statusDiv.style.display = 'block';
                            document.getElementById('parsingMessage').textContent = 
                                `🔄 Обновляем цены для ${data.current_task}...`;
                        } else {
                            statusDiv.style.display = 'none';
                            if (data.last_completed) {
                                console.log(`✅ Парсинг завершен для ${data.last_completed.brand} ${data.last_completed.model}`);
                            }
                        }
                    })
                    .catch(error => {
                        console.error('Ошибка проверки статуса парсинга:', error);
                    });
            }

            // Обновление индикатора шагов
            function updateStepIndicator(step, status) {
                const stepElement = document.getElementById(`step${step}`);
                stepElement.className = 'step';
                if (status === 'active') {
                    stepElement.classList.add('active');
                } else if (status === 'completed') {
                    stepElement.classList.add('completed');
                }
            }

            // Обработка загрузки фото
            const photoUpload = document.getElementById('photoUpload');
            const photoInput = document.getElementById('photoInput');
            const photoPreview = document.getElementById('photoPreview');
            const removePhotoBtn = document.getElementById('removePhoto');

            // Клик по области загрузки
            photoUpload.addEventListener('click', function() {
                photoInput.click();
            });

            // Выбор файла
            photoInput.addEventListener('change', function(e) {
                const file = e.target.files[0];
                if (file) {
                    handlePhotoUpload(file);
                }
            });

            // Drag and drop
            photoUpload.addEventListener('dragover', function(e) {
                e.preventDefault();
                photoUpload.classList.add('dragover');
            });

            photoUpload.addEventListener('dragleave', function() {
                photoUpload.classList.remove('dragover');
            });

            photoUpload.addEventListener('drop', function(e) {
                e.preventDefault();
                photoUpload.classList.remove('dragover');
                const file = e.dataTransfer.files[0];
                if (file && file.type.startsWith('image/')) {
                    handlePhotoUpload(file);
                }
            });

            // Удаление фото
            removePhotoBtn.addEventListener('click', function() {
                currentPhoto = null;
                photoInput.value = '';
                photoPreview.style.display = 'none';
                removePhotoBtn.style.display = 'none';
                photoUpload.innerHTML = `
                    <div class="upload-icon">📷</div>
                    <div>Нажмите для выбора файла или перетащите фото сюда</div>
                    <div style="font-size: 12px; color: #666; margin-top: 5px;">
                        Поддерживаемые форматы: JPG, PNG, GIF (макс. 5MB)
                    </div>
                `;
            });

            function handlePhotoUpload(file) {
                // Проверка размера файла (5MB)
                if (file.size > 5 * 1024 * 1024) {
                    alert('Файл слишком большой. Максимальный размер: 5MB');
                    return;
                }

                const reader = new FileReader();
                reader.onload = function(e) {
                    currentPhoto = e.target.result;
                    photoPreview.src = currentPhoto;
                    photoPreview.style.display = 'block';
                    removePhotoBtn.style.display = 'block';
                    
                    // Обновляем текст области загрузки
                    photoUpload.innerHTML = `
                        <div>Фото загружено: ${file.name}</div>
                        <div style="font-size: 12px; color: #666; margin-top: 5px;">
                            Размер: ${(file.size / 1024 / 1024).toFixed(2)} MB
                        </div>
                    `;
                    photoUpload.appendChild(photoPreview);
                };
                reader.readAsDataURL(file);
            }

            // Автодополнение для марки
            document.getElementById('brand').addEventListener('input', function(e) {
                const input = e.target.value;
                const autocomplete = document.getElementById('brandAutocomplete');
                
                if (input.length === 0) {
                    autocomplete.style.display = 'none';
                    document.getElementById('model').disabled = true;
                    document.getElementById('model').value = '';
                    document.getElementById('model').placeholder = 'Сначала выберите марку...';
                    document.getElementById('modelAutocomplete').style.display = 'none';
                    return;
                }

                // Фильтруем марки по введенному тексту
                const filteredBrands = allBrands.filter(brand => 
                    brand.toLowerCase().includes(input.toLowerCase())
                );

                if (filteredBrands.length === 0) {
                    autocomplete.style.display = 'none';
                    return;
                }

                // Показываем подсказки
                autocomplete.innerHTML = '';
                filteredBrands.forEach(brand => {
                    const item = document.createElement('div');
                    item.className = 'autocomplete-item';
                    item.textContent = brand;
                    item.addEventListener('click', function() {
                        document.getElementById('brand').value = brand;
                        autocomplete.style.display = 'none';
                        // Загружаем модели для выбранной марки
                        loadModelsForBrand(brand);
                        document.getElementById('model').disabled = false;
                        document.getElementById('model').placeholder = 'Начните вводить модель...';
                        document.getElementById('model').focus();
                    });
                    autocomplete.appendChild(item);
                });
                autocomplete.style.display = 'block';
            });

            // Автодополнение для модели
            document.getElementById('model').addEventListener('input', function(e) {
                const input = e.target.value;
                const brand = document.getElementById('brand').value;
                const autocomplete = document.getElementById('modelAutocomplete');
                
                if (input.length === 0 || !brand) {
                    autocomplete.style.display = 'none';
                    return;
                }

                const models = brandModels[brand] || [];
                const filteredModels = models.filter(model => 
                    model.toLowerCase().includes(input.toLowerCase())
                );

                if (filteredModels.length === 0) {
                    autocomplete.style.display = 'none';
                    return;
                }

                // Показываем подсказки
                autocomplete.innerHTML = '';
                filteredModels.forEach(model => {
                    const item = document.createElement('div');
                    item.className = 'autocomplete-item';
                    item.textContent = model;
                    item.addEventListener('click', function() {
                        document.getElementById('model').value = model;
                        autocomplete.style.display = 'none';
                    });
                    autocomplete.appendChild(item);
                });
                autocomplete.style.display = 'block';
            });

            // Загрузка моделей для выбранной марки
            function loadModelsForBrand(brand) {
                document.getElementById('status').textContent = `Загрузка моделей для ${brand}...`;
                
                fetch('/get-models?brand=' + encodeURIComponent(brand))
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            brandModels[brand] = data.models;
                            document.getElementById('status').textContent = `Загружено ${data.models.length} моделей для ${brand}`;
                        } else {
                            document.getElementById('status').textContent = 'Ошибка загрузки моделей: ' + data.error;
                            brandModels[brand] = [];
                        }
                    })
                    .catch(error => {
                        document.getElementById('status').textContent = 'Ошибка сети при загрузке моделей';
                        brandModels[brand] = [];
                    });
            }

            // Закрытие автодополнения при клике вне поля
            document.addEventListener('click', function(e) {
                if (!e.target.matches('#brand') && !e.target.matches('#model')) {
                    document.getElementById('brandAutocomplete').style.display = 'none';
                    document.getElementById('modelAutocomplete').style.display = 'none';
                }
            });

            // Отправка формы
            document.getElementById('carForm').addEventListener('submit', function(e) {
                e.preventDefault();
                
                const brand = document.getElementById('brand').value;
                const model = document.getElementById('model').value;
                const submitBtn = document.getElementById('submitBtn');
                
                // Проверяем что фото загружено
                if (!currentPhoto) {
                    alert('Пожалуйста, загрузите фото повреждений для анализа');
                    return;
                }
                
                console.log('Отправка формы:', { brand, model, hasPhoto: !!currentPhoto });
                
                // Блокируем кнопку и показываем загрузку
                submitBtn.disabled = true;
                submitBtn.textContent = '🔄 Обновляем данные...';
                document.getElementById('loading').style.display = 'block';
                document.getElementById('loadingMessage').textContent = '🔄 Обновляем данные о ценах...';
                document.getElementById('result').style.display = 'none';
                document.getElementById('status').textContent = 'Обновление данных...';
                
                // Обновляем индикатор шагов
                updateStepIndicator(1, 'active');
                updateStepIndicator(2, '');
                updateStepIndicator(3, '');
                
                // Скрываем автодополнение
                document.getElementById('brandAutocomplete').style.display = 'none';
                document.getElementById('modelAutocomplete').style.display = 'none';
                
                // Подготавливаем данные для отправки
                const formData = {
                    brand: brand,
                    model: model,
                    photo: currentPhoto
                };
                
                // Отправляем данные на сервер
                fetch('/analyze-damage', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify(formData)
                })
                .then(response => response.json())
                .then(data => {
                    console.log('Получен ответ:', data);
                    
                    // Восстанавливаем кнопку
                    submitBtn.disabled = false;
                    submitBtn.textContent = '🔍 Проанализировать повреждения и оценить стоимость';
                    document.getElementById('loading').style.display = 'none';
                    
                    const resultDiv = document.getElementById('result');
                    
                    if (data.success) {
                        resultDiv.className = 'result success';
                        let html = `<h3>📊 Результаты AI оценки для ${data.brand} ${data.model}</h3>`;
                        
                        // Показываем превью фото
                        if (data.photo_preview) {
                            html += `<div style="text-align: center; margin: 15px 0;">
                                        <img src="${data.photo_preview}" style="max-width: 300px; max-height: 200px; border-radius: 8px; border: 2px solid #ddd;">
                                        <div style="font-size: 12px; color: #666; margin-top: 5px;">Анализируемое фото</div>
                                    </div>`;
                        }
                        
                        html += `<h4>🔧 Обнаруженные повреждения: <span class="ai-analysis-badge">AI анализ</span></h4>`;
                        
                        if (data.damages && data.damages.length > 0) {
                            let totalRepairCost = 0;
                            let totalReplacementCost = 0;
                            
                            data.damages.forEach(damage => {
                                totalRepairCost += damage.repair_cost;
                                totalReplacementCost += damage.replacement_cost;
                                
                                // Определяем бейдж для типа повреждения
                                let damageTypeBadge = '';
                                let damageBadgeClass = '';
                                switch(damage.damage_type.toLowerCase()) {
                                    case 'вмятина':
                                        damageBadgeClass = 'dent-badge';
                                        break;
                                    case 'царапина':
                                        damageBadgeClass = 'scratch-badge';
                                        break;
                                    case 'разрыв':
                                        damageBadgeClass = 'break-badge';
                                        break;
                                    default:
                                        damageBadgeClass = 'dent-badge';
                                }
                                damageTypeBadge = `<span class="damage-type-badge ${damageBadgeClass}">${damage.damage_type}</span>`;
                                
                                // Определяем бейдж для материала
                                let materialBadge = '';
                                let materialBadgeClass = '';
                                switch(damage.detected_material.toLowerCase()) {
                                    case 'сталь':
                                        materialBadgeClass = 'steel-badge';
                                        break;
                                    case 'алюминий':
                                        materialBadgeClass = 'aluminum-badge';
                                        break;
                                    case 'магниевый сплав':
                                        materialBadgeClass = 'magnesium-badge';
                                        break;
                                    case 'композит':
                                        materialBadgeClass = 'composite-badge';
                                        break;
                                    case 'пластик':
                                        materialBadgeClass = 'plastic-badge';
                                        break;
                                    default:
                                        materialBadgeClass = 'steel-badge';
                                }
                                materialBadge = `<span class="material-badge ${materialBadgeClass}">${damage.detected_material}</span>`;
                                
                                let linkHtml = '';
                                if (damage.link && damage.link !== '') {
                                    linkHtml = `<a href="${damage.link}" target="_blank" class="part-link">🔗 Ссылка на деталь</a>`;
                                } else {
                                    linkHtml = `<span class="no-link">🔗 Ссылка не указана</span>`;
                                }
                                
                                // Определяем рекомендацию
                                const recommendationClass = damage.recommendation === 'ремонт' ? 
                                    'recommend-repair' : 'recommend-replacement';
                                const recommendationIcon = damage.recommendation === 'ремонт' ? '🔧' : '🔄';
                                
                                html += `
                                    <div class="damage-item">
                                        <div style="display: flex; justify-content: space-between; align-items: center;">
                                            <strong style="font-size: 1.2em;">${damage.part}</strong>
                                            <div>
                                                ${damageTypeBadge}
                                                ${materialBadge}
                                            </div>
                                        </div>
                                        
                                        <div class="damage-details">
                                            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                                                <div><strong>📏 Площадь повреждения:</strong> ${damage.damage_area_cm2} см²</div>
                                                <div><strong>📐 Площадь детали:</strong> ${damage.area}</div>
                                                <div><strong>⚡ Сложность ремонта:</strong> ${damage.severity}</div>
                                            </div>
                                            <div style="margin-top: 10px;">
                                                <strong>📍 Расположение:</strong> ${damage.location}
                                                <span style="margin-left: 20px;"><strong>🎯 Точность:</strong> ${Math.round(damage.confidence * 100)}%</span>
                                            </div>
                                        </div>
                                        
                                        <div class="cost-comparison">
                                            <div class="repair-cost">
                                                <div>🔧 Ремонт</div>
                                                <div class="cost-value repair-value">${damage.repair_cost.toLocaleString('ru-RU')} руб.</div>
                                                <small>Восстановление детали (${damage.damage_area_cm2} см² × материал)</small>
                                            </div>
                                            <div class="replacement-cost">
                                                <div>🔄 Полная замена</div>
                                                <div class="cost-value replacement-value">${damage.replacement_cost.toLocaleString('ru-RU')} руб.</div>
                                                <small>Новая деталь</small>
                                            </div>
                                        </div>
                                        
                                        <div class="recommendation ${recommendationClass}">
                                            ${recommendationIcon} Рекомендация: <strong>${damage.recommendation.toUpperCase()}</strong>
                                            ${damage.recommendation === 'ремонт' ? 
                                                `(экономия ${damage.savings.toLocaleString('ru-RU')} руб.)` : 
                                                '(ремонт нецелесообразен)'}
                                        </div>
                                        
                                        <div style="margin-top: 15px;">
                                            ${linkHtml}
                                        </div>
                                    </div>
                                `;
                            });
                            
                            // Общая стоимость
                            const totalSavings = totalReplacementCost - totalRepairCost;
                            const finalRecommendation = totalRepairCost < totalReplacementCost ? 'ремонт' : 'замена';
                            
                            html += `
                                <div class="total-cost">
                                    <div>💵 Общая стоимость ремонта: ${totalRepairCost.toLocaleString('ru-RU')} руб.</div>
                                    <div>💰 Общая стоимость замены: ${totalReplacementCost.toLocaleString('ru-RU')} руб.</div>
                                    <div style="margin-top: 15px; font-size: 1.3em; padding: 15px; background: white; border-radius: 8px;">
                                        🎯 Итоговая рекомендация: <strong>${finalRecommendation.toUpperCase()}</strong>
                                        ${finalRecommendation === 'ремонт' ? 
                                            `(экономия ${totalSavings.toLocaleString('ru-RU')} руб.)` : 
                                            ''}
                                    </div>
                                </div>
                            `;
                            
                            // Показываем информацию о фоновом парсинге
                            if (data.background_parsing > 0) {
                                html += `<div style="margin-top: 15px; padding: 10px; background: #e7f3ff; border-radius: 5px;">
                                            <small>🔄 Запущено фоновое обновление цен для ${data.background_parsing} деталей</small>
                                        </div>`;
                            }
                        } else {
                            html += `<p>❌ AI не обнаружил повреждений на фото</p>`;
                        }
                        
                        resultDiv.innerHTML = html;
                        
                        // Обновляем индикатор шагов
                        updateStepIndicator(1, 'completed');
                        updateStepIndicator(2, 'completed');
                        updateStepIndicator(3, 'completed');
                    } else {
                        resultDiv.className = 'result error';
                        resultDiv.innerHTML = `<p>❌ Ошибка: ${data.error}</p>`;
                        
                        // Сбрасываем индикатор шагов при ошибке
                        updateStepIndicator(1, '');
                        updateStepIndicator(2, '');
                        updateStepIndicator(3, '');
                    }
                    
                    resultDiv.style.display = 'block';
                })
                .catch(error => {
                    // Восстанавливаем кнопку при ошибке
                    submitBtn.disabled = false;
                    submitBtn.textContent = '🔍 Проанализировать повреждения и оценить стоимость';
                    document.getElementById('loading').style.display = 'none';
                    
                    const resultDiv = document.getElementById('result');
                    resultDiv.className = 'result error';
                    resultDiv.innerHTML = '<p>❌ Произошла ошибка при отправке запроса</p>';
                    resultDiv.style.display = 'block';
                    
                    // Сбрасываем индикатор шагов при ошибке
                    updateStepIndicator(1, '');
                    updateStepIndicator(2, '');
                    updateStepIndicator(3, '');
                    
                    console.error('Error:', error);
                });
            });
        </script>
    </body>
    </html>
    '''

@app.route('/get-brands')
def get_brands():
    """Возвращает список уникальных марок"""
    try:
        brands = get_unique_brands()
        print(f"📡 GET /get-brands -> {len(brands)} марок")
        return jsonify({
            "success": True,
            "brands": brands
        })
    except Exception as e:
        print(f"❌ Ошибка в get_brands: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        })

@app.route('/get-models')
def get_models():
    """Возвращает список моделей для указанной марки"""
    try:
        brand = request.args.get('brand', '')
        print(f"📡 GET /get-models?brand={brand}")
        
        if not brand:
            return jsonify({
                "success": False,
                "error": "Не указана марка"
            })
        
        models = get_models_by_brand(brand)
        return jsonify({
            "success": True,
            "models": models
        })
    except Exception as e:
        print(f"❌ Ошибка в get_models для марки '{brand}': {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        })

@app.route('/parsing-status')
def parsing_status():
    """Возвращает статус фонового парсинга"""
    # Преобразуем все данные в JSON-сериализуемые типы
    status_data = {
        "in_progress": PARSING_STATUS['in_progress'],
        "current_task": PARSING_STATUS['current_task']
    }
    
    # Обрабатываем last_completed отдельно, преобразуя все числовые типы
    if PARSING_STATUS['last_completed']:
        last_completed = PARSING_STATUS['last_completed'].copy()
        # Преобразуем все числовые значения в стандартные Python типы
        if 'timestamp' in last_completed:
            last_completed['timestamp'] = float(last_completed['timestamp'])
        if 'parsed_parts' in last_completed:
            last_completed['parsed_parts'] = int(last_completed['parsed_parts'])
        if 'found_prices' in last_completed:
            last_completed['found_prices'] = int(last_completed['found_prices'])
        status_data['last_completed'] = last_completed
    else:
        status_data['last_completed'] = None
    
    return jsonify(status_data)

@app.route('/analyze-damage', methods=['POST'])
def analyze_damage_endpoint():
    global CAR_PRICES_DF
    try:
        data = request.get_json()
        
        brand = data.get('brand', '').strip()
        model = data.get('model', '').strip()
        photo_data = data.get('photo', '')
        
        print(f"📡 POST /analyze-damage -> {brand} {model}, фото: {'есть' if photo_data else 'нет'}")
        
        # Валидация данных
        if not brand or not model:
            return jsonify({
                "success": False,
                "error": "Все поля обязательны для заполнения"
            })
        
        if not photo_data:
            return jsonify({
                "success": False,
                "error": "Фото обязательно для AI анализа повреждений"
            })
        
        # Проверяем, загружены ли данные из Excel
        if CAR_PRICES_DF is None:
            return jsonify({
                "success": False,
                "error": "База данных не загружена. Убедитесь, что файл huh_result.xlsx существует и имеет правильную структуру."
            })
        
        # 🔄 ПЕРВЫЙ ЭТАП: ЗАПУСКАЕМ АВТОМАТИЧЕСКИЙ ПАРСИНГ И ЖДЕМ ЕГО ЗАВЕРШЕНИЯ
        print(f"🚀 Запускаем автоматический парсинг для {brand} {model}")
        all_parts = get_all_parts_for_model(brand, model)
        
        if all_parts:
            # Запускаем парсинг и ждем его завершения
            start_auto_parsing(
                brand=brand,
                model=model,
                damaged_parts=all_parts
            )
            print(f"⏳ Ожидаем завершения парсинга для {len(all_parts)} деталей...")
            
            # Ждем завершения парсинга
            if not wait_for_parsing_completion():
                return jsonify({
                    "success": False,
                    "error": "Таймаут ожидания обновления данных. Попробуйте позже."
                })
            
            print("✅ Парсинг завершен, продолжаем анализ...")
        else:
            print(f"⚠️ Для {brand} {model} не найдено деталей для парсинга")
        
        # 🔄 ВТОРОЙ ЭТАП: АНАЛИЗ ФОТО С ОБНОВЛЕННЫМИ ДАННЫМИ
        # Сохраняем фото
        photo_path = save_uploaded_photo(photo_data)
        if not photo_path:
            return jsonify({
                "success": False,
                "error": "Не удалось сохранить фото"
            })
        
        # Запускаем AI анализ повреждений
        damage_analysis = analyze_damage_with_ai(photo_path, brand, model)
        
        if not damage_analysis:
            return jsonify({
                "success": False,
                "error": "Не удалось проанализировать повреждения на фото. Проверьте скрипт анализа."
            })
        
        # 🔄 ПЕРЕЗАГРУЖАЕМ ДАННЫЕ ИЗ EXCEL (чтобы получить актуальные цены)
        CAR_PRICES_DF = load_repair_prices_from_excel()
        
        # Рассчитываем стоимость ремонта и замены на основе анализа
        damages_with_costs = calculate_repair_cost(damage_analysis, brand, model)
        
        if not damages_with_costs:
            return jsonify({
                "success": False,
                "error": "Не удалось найти детали для анализа повреждений в таблице"
            })
        
        total_repair_cost = sum(damage["repair_cost"] for damage in damages_with_costs)
        total_replacement_cost = sum(damage["replacement_cost"] for damage in damages_with_costs)
        
        response_data = {
            "success": True,
            "brand": brand,
            "model": model,
            "damages": damages_with_costs,
            "total_repair_cost": int(total_repair_cost),
            "total_replacement_cost": int(total_replacement_cost),
            "photo_preview": photo_data,
            "analysis_method": "AI",
            "background_parsing": len(all_parts) if all_parts else 0
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"❌ Ошибка в analyze_damage: {e}")
        return jsonify({
            "success": False,
            "error": f"Внутренняя ошибка сервера: {str(e)}"
        })

if __name__ == '__main__':
    print("🚀 Запуск системы AI оценки повреждений автомобиля")
    print(f"🔧 Скрипт анализа: {DAMAGE_ANALYSIS_SCRIPT}")
    
    if CAR_PRICES_DF is not None:
        print(f"✅ Успешно загружено {len(CAR_PRICES_DF)} записей из huh_result.xlsx")
        print("🚗 Доступные марки:", get_unique_brands())
    else:
        print("❌ Не удалось загрузить данные из Excel файла")
        print("📋 Убедитесь, что файл huh_result.xlsx существует со следующими колонками:")
        print("   - марка, модель, деталь, площадь детали, материал детали, цена, ссылка")
    
    print("🌐 Сервер запущен: http://localhost:5000")
    app.run(debug=True, port=5000)
