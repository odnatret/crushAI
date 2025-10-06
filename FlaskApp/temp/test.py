import pandas as pd
import requests
from bs4 import BeautifulSoup
import time
import random
from urllib.parse import urljoin
import logging
import re
import os
from threading import Thread
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class AutoDromParser:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        self.base_url = "https://baza.drom.ru"

    def search_part(self, brand, model, part):
        """Поиск цены и ссылки для конкретной детали"""
        try:
            search_query = f"{brand} {model} {part}".strip()
            encoded_query = search_query.replace(' ', '+')
            
            search_url = f"{self.base_url}/?query={encoded_query}"
            
            logging.info(f"🔍 Поиск: {search_query}")
            
            response = self.session.get(search_url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            price, link = self.find_price_and_link(soup)
            
            if not link:
                link = search_url
            
            if price == 0:
                logging.warning(f"❌ Не найдена цена для: {search_query}")
            else:
                logging.info(f"✅ Найдено: {price} руб. для {part}")
            
            return price, link
                
        except Exception as e:
            logging.error(f"❌ Ошибка для {brand} {model} {part}: {e}")
            return 0, ""

    def find_price_and_link(self, soup):
        """Поиск цены и ссылки в HTML"""
        listings = self.find_listings(soup)
        
        if not listings:
            return 0, None
        
        for listing in listings:
            price, link = self.extract_from_listing(listing)
            if price > 0 and link:
                return price, link
        
        first_listing = listings[0]
        price, link = self.extract_from_listing(first_listing)
        return price, link

    def find_listings(self, soup):
        """Поиск списка объявлений"""
        listing_selectors = [
            'a[data-ftid="bulls-list_bull"]',
            'div[data-ftid="component_bullseye"]',
            '[class*="bull-item"]',
            '[class*="bulla"]',
            '[class*="listing-item"]',
        ]
        
        for selector in listing_selectors:
            listings = soup.select(selector)
            if listings:
                return listings
        return None

    def extract_from_listing(self, listing):
        """Извлечение цены и ссылки из объявления"""
        try:
            link = self.extract_link(listing)
            price = self.extract_price_from_listing(listing)
            return price, link
        except Exception as e:
            logging.error(f"Ошибка извлечения: {e}")
            return 0, None

    def extract_link(self, element):
        """Извлечение ссылки"""
        try:
            if element.name == 'a' and element.get('href'):
                href = element['href']
                if href.startswith('/'):
                    return urljoin(self.base_url, href)
                return href
            
            link_selectors = ['a[href*="/offer/"]', 'a[href*="/s/"]', 'a']
            for selector in link_selectors:
                link_element = element.select_one(selector)
                if link_element and link_element.get('href'):
                    href = link_element['href']
                    if href.startswith('/'):
                        return urljoin(self.base_url, href)
                    return href
            return None
        except Exception as e:
            logging.error(f"Ошибка извлечения ссылки: {e}")
            return None

    def extract_price_from_listing(self, listing):
        """Извлечение цены"""
        try:
            price_selectors = [
                '[data-ftid="bull_price"]',
                '.bull-item__price',
                '.bulla__price',
                '*[class*="price"]',
            ]
            
            for selector in price_selectors:
                price_element = listing.select_one(selector)
                if price_element:
                    price_text = price_element.get_text(strip=True)
                    cleaned_price = self.clean_price(price_text)
                    if cleaned_price > 0:
                        return cleaned_price
            
            listing_text = listing.get_text()
            price_patterns = [r'(\d[\d\s]*)\s*(руб|₽|р\.|рублей)']
            
            for pattern in price_patterns:
                matches = re.findall(pattern, listing_text, re.IGNORECASE)
                if matches:
                    for match in matches:
                        price_text = match[0] if isinstance(match, tuple) else match
                        cleaned_price = self.clean_price(price_text)
                        if cleaned_price > 0:
                            return cleaned_price
            
            return 0
        except Exception as e:
            logging.error(f"Ошибка извлечения цены: {e}")
            return 0

    def clean_price(self, price_text):
        """Очистка и преобразование цены"""
        try:
            digits_only = re.sub(r'[^\d]', '', str(price_text))
            if digits_only and len(digits_only) >= 2:
                price_num = int(digits_only)
                if 10 <= price_num <= 10000000:
                    return price_num
            return 0
        except:
            return 0

    def parse_damaged_parts(self, brand, model, damaged_parts):
        """
        Автоматический парсинг для поврежденных деталей
        
        Args:
            brand (str): Марка автомобиля
            model (str): Модель автомобиля  
            damaged_parts (list): Список поврежденных деталей
        
        Returns:
            list: Список словарей с данными о деталях
        """
        results = []
        
        logging.info(f"🚗 Начинаем автоматический парсинг для {brand} {model}")
        logging.info(f"🔧 Поврежденные детали: {damaged_parts}")
        
        for i, part in enumerate(damaged_parts, 1):
            logging.info(f"📦 Парсинг {i}/{len(damaged_parts)}: {part}")
            
            price, link = self.search_part(brand, model, part)
            
            # Автоматическое определение параметров
            area = self.determine_area(part)
            material = self.determine_material(part)
            
            result = {
                'марка': brand,
                'модель': model,
                'деталь': part,
                'площадь_детали': area,
                'материал_детали': material,
                'цена': price,
                'ссылка': link
            }
            
            results.append(result)
            
            # Задержка между запросами
            if i < len(damaged_parts):
                delay = random.uniform(1, 3)
                time.sleep(delay)
        
        logging.info(f"✅ Автопарсинг завершен. Обработано {len(results)} деталей")
        return results

    def determine_area(self, part):
        """Автоматическое определение площади детали"""
        part_lower = part.lower()
        if any(word in part_lower for word in ['бампер', 'дверь', 'капот', 'крышка', 'крыло']):
            return "большая"
        elif any(word in part_lower for word in ['фара', 'зеркало', 'стекло']):
            return "средняя" 
        else:
            return "малая"

    def determine_material(self, part):
        """Автоматическое определение материала"""
        part_lower = part.lower()
        if any(word in part_lower for word in ['стекло', 'фара']):
            return "стекло"
        elif any(word in part_lower for word in ['бампер', 'зеркало', 'пластик']):
            return "пластик"
        else:
            return "металл"

def auto_parse_damages(brand, model, damaged_parts):
    """
    Автоматическая функция для вызова из Flask приложения
    
    Args:
        brand (str): Марка автомобиля
        model (str): Модель автомобиля
        damaged_parts (list): Список поврежденных деталей
    
    Returns:
        pd.DataFrame: DataFrame с результатами парсинга
    """
    parser = AutoDromParser()
    results = parser.parse_damaged_parts(brand, model, damaged_parts)
    return pd.DataFrame(results)

def update_excel_with_parsed_data(parsed_df, excel_file='huh_result.xlsx'):
    """
    Обновляет Excel файл с новыми данными из парсинга
    
    Args:
        parsed_df (pd.DataFrame): DataFrame с результатами парсинга
        excel_file (str): Путь к Excel файлу
    """
    try:
        if os.path.exists(excel_file):
            # Загружаем существующий файл
            existing_df = pd.read_excel(excel_file)
            
            # Обновляем или добавляем данные
            for _, new_row in parsed_df.iterrows():
                mask = (existing_df['марка'] == new_row['марка']) & \
                       (existing_df['модель'] == new_row['модель']) & \
                       (existing_df['деталь'] == new_row['деталь'])
                
                if mask.any():
                    # Обновляем существующую запись
                    idx = mask.idxmax()
                    existing_df.loc[idx, 'цена'] = new_row['цена']
                    existing_df.loc[idx, 'ссылка'] = new_row['ссылка']
                else:
                    # Добавляем новую запись
                    existing_df = pd.concat([existing_df, new_row.to_frame().T], ignore_index=True)
            
            # Сохраняем обновленный файл
            existing_df.to_excel(excel_file, index=False)
            logging.info(f"✅ Excel файл обновлен: {excel_file}")
        else:
            # Создаем новый файл
            parsed_df.to_excel(excel_file, index=False)
            logging.info(f"✅ Создан новый Excel файл: {excel_file}")
            
    except Exception as e:
        logging.error(f"❌ Ошибка обновления Excel: {e}")

def start_auto_parsing(brand, model, damaged_parts, callback=None):
    """
    Запускает автоматический парсинг в отдельном потоке
    
    Args:
        brand (str): Марка автомобиля
        model (str): Модель автомобиля
        damaged_parts (list): Список поврежденных деталей
        callback (function): Функция обратного вызова для уведомления о завершении
    """
    def parsing_thread():
        try:
            # Запускаем парсинг
            parsed_df = auto_parse_damages(brand, model, damaged_parts)
            
            # Обновляем Excel файл
            update_excel_with_parsed_data(parsed_df)
            
            # Вызываем callback если передан
            if callback:
                callback({
                    'success': True,
                    'brand': brand,
                    'model': model,
                    'parsed_parts': len(damaged_parts),
                    'found_prices': (parsed_df['цена'] > 0).sum(),
                    'dataframe': parsed_df
                })
                
        except Exception as e:
            logging.error(f"❌ Ошибка в потоке парсинга: {e}")
            if callback:
                callback({
                    'success': False,
                    'error': str(e)
                })
    
    # Запускаем в отдельном потоке
    thread = Thread(target=parsing_thread)
    thread.daemon = True
    thread.start()
    
    logging.info(f"🚀 Запущен автоматический парсинг для {brand} {model}")
    return thread
