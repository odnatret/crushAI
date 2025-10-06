import pandas as pd
import requests
from bs4 import BeautifulSoup
import time
import random
from urllib.parse import quote, urljoin
import logging
import re

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class DromParser:
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
        try:
            search_query = f"{brand} {model} {part}".strip()
            encoded_query = search_query.replace(' ', '+')
            
            search_url = f"{self.base_url}/?query={encoded_query}"
            
            logging.info(f"Поиск: {search_query}")
            logging.info(f"URL: {search_url}")
            
            response = self.session.get(search_url, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            price, link = self.find_price_and_link(soup)
            
            if not link:
                link = search_url  # Если ссылку не нашли, используем поисковую ссылку
            
            if price == 0:
                logging.warning(f"Не удалось найти цену для: {search_query}")
            
            return price, link
                
        except requests.RequestException as e:
            logging.error(f"Ошибка запроса для {brand} {model} {part}: {e}")
            return 0, ""
        except Exception as e:
            logging.error(f"Неожиданная ошибка для {brand} {model} {part}: {e}")
            return 0, ""

    def find_price_and_link(self, soup):
        listings = self.find_listings(soup)
        
        if not listings:
            return 0, None
        
        for listing in listings:
            price, link = self.extract_from_listing(listing)
            if price > 0 and link:
                logging.info(f"Найдена цена: {price}, ссылка: {link}")
                return price, link
        
        first_listing = listings[0]
        price, link = self.extract_from_listing(first_listing)
        if link:
            return price, link
        
        return 0, None

    def find_listings(self, soup):
        # Различные селекторы для карточек объявлений
        listing_selectors = [
            'a[data-ftid="bulls-list_bull"]',  # Основной селектор для карточек
            'div[data-ftid="component_bullseye"]',
            '[class*="bull-item"]',
            '[class*="bulla"]',
            '[class*="listing-item"]',
            '.css-1pbv6jv',
            '.css-1ybr0uv',
        ]
        
        for selector in listing_selectors:
            listings = soup.select(selector)
            if listings:
                logging.info(f"Найдено {len(listings)} объявлений с селектором: {selector}")
                return listings
        
        return None

    def extract_from_listing(self, listing):
        try:
            link = self.extract_link(listing)
            
            price = self.extract_price_from_listing(listing)
            
            return price, link
            
        except Exception as e:
            logging.error(f"Ошибка извлечения из listing: {e}")
            return 0, None

    def extract_link(self, element):
        try:
            if element.name == 'a' and element.get('href'):
                href = element['href']
                if href.startswith('/'):
                    return urljoin(self.base_url, href)
                else:
                    return href
            
            link_selectors = [
                'a[href*="/offer/"]',
                'a[href*="/s/"]',
                'a[data-ftid="bull_title"]',
                'a'
            ]
            
            for selector in link_selectors:
                link_element = element.select_one(selector)
                if link_element and link_element.get('href'):
                    href = link_element['href']
                    if href.startswith('/'):
                        return urljoin(self.base_url, href)
                    else:
                        return href
            
            return None
        except Exception as e:
            logging.error(f"Ошибка извлечения ссылки: {e}")
            return None

    def extract_price_from_listing(self, listing):
        try:
            price_selectors = [
                '[data-ftid="bull_price"]',
                '.bull-item__price',
                '.bulla__price',
                '.css-1dv8s3l',
                '.css-1o4spfk',
                '.css-1q8mql1',
                '*[class*="price"]',
                '*[class*="Price"]',
                '.b-price'
            ]
            
            for selector in price_selectors:
                price_element = listing.select_one(selector)
                if price_element:
                    price_text = price_element.get_text(strip=True)
                    cleaned_price = self.clean_price(price_text)
                    if cleaned_price > 0:
                        return cleaned_price
            
            listing_text = listing.get_text()
            price_patterns = [
                r'(\d[\d\s]*)\s*(руб|₽|р\.|рублей)',
                r'цена[:\s]*(\d[\d\s]*)',
                r'стоимость[:\s]*(\d[\d\s]*)'
            ]
            
            for pattern in price_patterns:
                matches = re.findall(pattern, listing_text, re.IGNORECASE)
                if matches:
                    for match in matches:
                        if isinstance(match, tuple):
                            price_text = match[0]
                        else:
                            price_text = match
                        cleaned_price = self.clean_price(price_text)
                        if cleaned_price > 0:
                            return cleaned_price
            
            return 0
            
        except Exception as e:
            logging.error(f"Ошибка извлечения цены: {e}")
            return 0

    def clean_price(self, price_text):
        try:
            digits_only = re.sub(r'[^\d]', '', str(price_text))
            
            if digits_only and len(digits_only) >= 2:
                price_num = int(digits_only)
                if 10 <= price_num <= 10000000:
                    return price_num
            
            return 0
        except:
            return 0

    def process_dataframe(self, df, brand_col='марка', model_col='модель', part_col='деталь'):
        prices = []
        links = []
        
        total_rows = len(df)
        
        for index, row in df.iterrows():
            brand = str(row[brand_col]).strip()
            model = str(row[model_col]).strip()
            part = str(row[part_col]).strip()
            
            if not all([brand, model, part]):
                prices.append(0)
                links.append("")
                continue
            
            logging.info(f"Обработка {index + 1}/{total_rows}: {brand} {model} {part}")
            
            price, link = self.search_part(brand, model, part)
            
            prices.append(price)
            links.append(link if link else "")
            
            delay = random.uniform(2, 4)
            logging.info(f"Задержка {delay:.1f} сек...")
            time.sleep(delay)
        
        df['цена'] = prices
        df['ссылка'] = links
        
        return df

def main():

    parser = DromParser()
    
    try:
        file_path = input("Введите путь к файлу с данными (CSV или Excel): ").strip()
        
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path, encoding='utf-8')
        elif file_path.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file_path)
        else:
            print("Неверный формат файла. Поддерживаются CSV и Excel файлы.")
            return
        
        print("Столбцы в файле:")
        print(df.columns.tolist())
        
        brand_col = input("Введите название столбца с марками: ").strip()
        model_col = input("Введите название столбца с моделями: ").strip()
        part_col = input("Введите название столбца с деталями: ").strip()
        
        missing_cols = []
        for col in [brand_col, model_col, part_col]:
            if col not in df.columns:
                missing_cols.append(col)
        
        if missing_cols:
            print(f"Отсутствуют столбцы: {missing_cols}")
            return
        
        print("\nПервые 3 строки данных:")
        print(df[[brand_col, model_col, part_col]].head(3))
        
        print("\nНачинаем парсинг...")
        result_df = parser.process_dataframe(df, brand_col, model_col, part_col)
        
        output_file = input("Введите имя для выходного файла (без расширения): ").strip()
        result_df.to_csv(f"{output_file}_result.csv", index=False, encoding='utf-8-sig')
        result_df.to_excel(f"{output_file}_result.xlsx", index=False)
        
        print(f"\nРезультаты сохранены в файлы:")
        print(f"- {output_file}_result.csv")
        print(f"- {output_file}_result.xlsx")
        print(f"Обработано {len(result_df)} записей")
        
        found_prices = (result_df['цена'] > 0).sum()
        found_links = result_df['ссылка'].str.contains('drom.ru', na=False).sum()
        print(f"Найдено цен: {found_prices}")
        print(f"Найдено ссылок: {found_links}")
        
        print("\nПримеры результатов:")
        for i, row in result_df.head(3).iterrows():
            print(f"{row[brand_col]} {row[model_col]} {row[part_col]}: {row['цена']} руб.")
            print(f"Ссылка: {row['ссылка']}\n")
        
    except FileNotFoundError:
        print("Файл не найден. Проверьте путь к файлу.")
    except Exception as e:
        print(f"Произошла ошибка: {e}")

if __name__ == "__main__":
    main()
