import cv2
import numpy as np
import os
import json
import argparse
from datetime import datetime
from ultralytics import YOLO

def map_yolo_part_to_russian(yolo_part_name):
    """
    Преобразует название детали из YOLO модели в русское название
    """
    PART_MAPPING = {
        'back_bumper': 'Бампер задний',
        'front_bumper': 'Бампер передний',
        'back_door': 'Дверь задняя', 
        'back_left_door': 'Дверь задняя',
        'back_right_door': 'Дверь задняя',
        'front_door': 'Дверь передняя',
        'front_left_door': 'Дверь передняя',
        'front_right_door': 'Дверь передняя',
        'back_glass': 'Стекло заднее',
        'front_glass': 'Стекло лобовое',
        'left_mirror': 'Зеркало левое',
        'right_mirror': 'Зеркало правое',
        'hood': 'Капот',
        'tailgate': 'Крышка багажника',
        'trunk': 'Багажник',
        'back_light': 'Фонарь задний',
        'back_left_light': 'Фонарь задний',
        'back_right_light': 'Фонарь задний',
        'front_light': 'Фара передняя',
        'front_left_light': 'Фара передняя',
        'front_right_light': 'Фара передняя',
        'object': 'Не определено',
        'wheel': 'Колесо'
    }
    
    return PART_MAPPING.get(yolo_part_name, 'Не определено')

def map_damage_to_russian(damage_type):
    """
    Преобразует тип повреждения на русский язык
    """
    DAMAGE_MAPPING = {
        'dent': 'Вмятина',
        'scratch': 'Царапина',
        'crack': 'Трещина',
        'break': 'Разлом',
        'chip': 'Скол',
        'crush': 'Раздавлено',
        'shatter': 'Разбито',
        'bend': 'Погнуто',
        'rip': 'Разрыв',
        'tear': 'Надрыв'
    }
    
    # Если повреждение не найдено в маппинге, возвращаем оригинал
    return DAMAGE_MAPPING.get(damage_type.lower(), damage_type)

def map_severity_to_russian(severity_level):
    """
    Преобразует уровень тяжести на русский язык
    """
    SEVERITY_MAPPING = {
        'light': 'легкий',
        'medium': 'средний',
        'heavy': 'тяжелый',
        'minor': 'незначительный',
        'major': 'серьезный'
    }
    
    return SEVERITY_MAPPING.get(severity_level.lower(), severity_level)

def determine_severity(damage_type, confidence, area_percentage):
    """
    Определяет тяжесть повреждения на основе типа, уверенности и площади
    """
    # Базовые веса для разных типов повреждений
    damage_weights = {
        'scratch': 1.0,
        'dent': 1.5,
        'crack': 2.0,
        'break': 2.5,
        'chip': 1.2
    }
    
    weight = damage_weights.get(damage_type.lower(), 1.0)
    severity_score = confidence * area_percentage * weight
    
    if severity_score > 0.6:
        return 'тяжелый'
    elif severity_score > 0.3:
        return 'средний'
    else:
        return 'легкий'

def get_model_path(model_relative_path):
    """Получает абсолютный путь к модели"""
    # Получаем абсолютный путь к директории скрипта
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Формируем возможные пути к модели
    possible_paths = [
        os.path.join(script_dir, model_relative_path),
        os.path.join(script_dir, "..", model_relative_path),
        os.path.join(os.getcwd(), model_relative_path),
        model_relative_path  # оригинальный путь
    ]
    
    # Ищем существующий путь
    for path in possible_paths:
        if os.path.exists(path):
            print(f"✅ Модель найдена: {path}")
            return path
    
    # Если ни один путь не найден
    print(f"❌ Модель не найдена по путям:")
    for path in possible_paths:
        print(f"   - {path}")
    return None

def create_output_folders():
    base_dir = "analysis_results"
    folders = {
        'base': base_dir,
        'damages': os.path.join(base_dir, "damages"),
        'parts': os.path.join(base_dir, "parts"),
        'intersections': os.path.join(base_dir, "intersections"),
        'final_result': os.path.join(base_dir, "final_result"),
        'json_data': os.path.join(base_dir, "json_data")
    }
    
    for folder in folders.values():
        os.makedirs(folder, exist_ok=True)
    
    return folders

def calculate_iou(box1, box2):
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    
    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    
    iou = intersection / (area1 + area2 - intersection) if (area1 + area2 - intersection) > 0 else 0
    return iou

def find_damage_parts(damage_boxes, damage_labels, part_boxes, part_labels, iou_threshold=0.1):
    results = []
    
    for damage_idx, damage_box in enumerate(damage_boxes):
        best_iou = 0
        best_part_label = "Не определено"
        best_part_idx = -1
        
        for part_idx, part_box in enumerate(part_boxes):
            iou = calculate_iou(damage_box, part_box)
            
            if iou > best_iou and iou > iou_threshold:
                best_iou = iou
                best_part_label = part_labels[part_idx]
                best_part_idx = part_idx
        
        results.append({
            'damage_index': damage_idx,
            'damage_type': damage_labels[damage_idx] if damage_idx < len(damage_labels) else "Неизвестно",
            'part_name': best_part_label,
            'iou': float(best_iou),
            'part_index': best_part_idx
        })
    
    return results

def draw_boxes(image, boxes, labels, color, thickness=2):
    result_image = image.copy()
    for i, box in enumerate(boxes):
        x1, y1, x2, y2 = map(int, box)
        cv2.rectangle(result_image, (x1, y1), (x2, y2), color, thickness)
        
        label = labels[i] if i < len(labels) else f"Obj {i}"
        label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)[0]
        cv2.rectangle(result_image, (x1, y1 - label_size[1] - 10), (x1 + label_size[0], y1), color, -1)
        cv2.putText(result_image, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
    
    return result_image

def save_damage_data_to_json(matches, damage_boxes, damage_labels, part_boxes, part_labels, folders, image_name, image_path, image_dimensions):
    """Сохраняет данные о повреждениях в JSON файл с информацией о типе повреждения и части автомобиля"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_filename = f"{image_name}_damage_analysis_{timestamp}.json"
    json_path = os.path.join(folders['json_data'], json_filename)
    
    # Подготовка данных для JSON
    damage_data = {
        "analysis_info": {
            "timestamp": datetime.now().isoformat(),
            "image_path": image_path,
            "image_name": image_name,
            "image_dimensions": {
                "width": int(image_dimensions[1]),
                "height": int(image_dimensions[0]),
                "channels": int(image_dimensions[2])
            }
        },
        "detected_parts": list(set(part_labels)),
        "detected_damage_types": list(set(damage_labels)),
        "damages": [],
        "summary": {
            "total_damages": len(matches),
            "damages_by_part": {},
            "damages_by_type": {}
        }
    }
    
    # Добавляем информацию о каждом повреждении
    for match in matches:
        damage_idx = match['damage_index']
        damage_box = damage_boxes[damage_idx]
        
        damage_info = {
            "damage_id": damage_idx + 1,
            "damage_type": match['damage_type'],
            "car_part": match['part_name'],
            "matching_confidence": match['iou'],
            "bounding_box": {
                "x1": float(damage_box[0]),
                "y1": float(damage_box[1]),
                "x2": float(damage_box[2]),
                "y2": float(damage_box[3]),
                "width": float(damage_box[2] - damage_box[0]),
                "height": float(damage_box[3] - damage_box[1])
            }
        }
        
        # Если найдена соответствующая часть, добавляем её координаты
        if match['part_index'] != -1:
            part_box = part_boxes[match['part_index']]
            damage_info["part_bounding_box"] = {
                "x1": float(part_box[0]),
                "y1": float(part_box[1]),
                "x2": float(part_box[2]),
                "y2": float(part_box[3])
            }
        
        damage_data["damages"].append(damage_info)
        
        # Обновляем сводную статистику по частям
        part_name = match['part_name']
        damage_data["summary"]["damages_by_part"][part_name] = damage_data["summary"]["damages_by_part"].get(part_name, 0) + 1
        
        # Обновляем сводную статистику по типам повреждений
        damage_type = match['damage_type']
        damage_data["summary"]["damages_by_type"][damage_type] = damage_data["summary"]["damages_by_type"].get(damage_type, 0) + 1
    
    # Сохраняем в JSON файл
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(damage_data, f, ensure_ascii=False, indent=2)
    
    print(f"Сохранены данные о повреждениях в JSON: {json_path}")
    return json_path

def save_intersection_images(original_image, damage_boxes, damage_labels, part_boxes, part_labels, matches, folders, image_name):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    damage_image = draw_boxes(original_image, damage_boxes, damage_labels, (0, 0, 255))
    damage_path = os.path.join(folders['damages'], f"{image_name}_damages_{timestamp}.jpg")
    cv2.imwrite(damage_path, damage_image)
    print(f"Сохранено изображение с повреждениями: {damage_path}")
    
    part_image = draw_boxes(original_image, part_boxes, part_labels, (0, 255, 0))
    part_path = os.path.join(folders['parts'], f"{image_name}_parts_{timestamp}.jpg")
    cv2.imwrite(part_path, part_image)
    print(f"Сохранено изображение с частями: {part_path}")
    
    intersection_image = original_image.copy()
    
    # Рисуем части автомобиля
    for i, part_box in enumerate(part_boxes):
        x1, y1, x2, y2 = map(int, part_box)
        cv2.rectangle(intersection_image, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(intersection_image, part_labels[i], (x1, y1 - 10), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    
    # Рисуем повреждения и связи с частями
    for match in matches:
        damage_idx = match['damage_index']
        part_idx = match['part_index']
        
        if part_idx != -1:
            damage_box = damage_boxes[damage_idx]
            part_box = part_boxes[part_idx]
            
            damage_center = (int((damage_box[0] + damage_box[2]) / 2), int((damage_box[1] + damage_box[3]) / 2))
            part_center = (int((part_box[0] + part_box[2]) / 2), int((part_box[1] + part_box[3]) / 2))
            
            cv2.line(intersection_image, damage_center, part_center, (255, 0, 255), 2)
            
            x1, y1, x2, y2 = map(int, damage_box)
            cv2.rectangle(intersection_image, (x1, y1), (x2, y2), (0, 0, 255), 3)
            
            # Используем русские labels
            label = f"{match['damage_type']} на {match['part_name']} (IoU: {match['iou']:.2f})"
            cv2.putText(intersection_image, label, (x1, y1 - 15), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        else:
            # Если часть не найдена, просто рисуем повреждение
            damage_box = damage_boxes[damage_idx]
            x1, y1, x2, y2 = map(int, damage_box)
            cv2.rectangle(intersection_image, (x1, y1), (x2, y2), (0, 0, 255), 3)
            label = f"{match['damage_type']} (Неизвестная часть)"
            cv2.putText(intersection_image, label, (x1, y1 - 15), 
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
    
    intersection_path = os.path.join(folders['intersections'], f"{image_name}_intersections_{timestamp}.jpg")
    cv2.imwrite(intersection_path, intersection_image)
    print(f"Сохранено изображение с пересечениями: {intersection_path}")
    
    final_image = intersection_image.copy()
    final_path = os.path.join(folders['final_result'], f"{image_name}_final_{timestamp}.jpg")
    cv2.imwrite(final_path, final_image)
    print(f"Сохранено финальное изображение: {final_path}")
    
    return {
        'damage_path': damage_path,
        'part_path': part_path,
        'intersection_path': intersection_path,
        'final_path': final_path
    }

def analyze_car_damage(image_path, confidence_threshold=0.5):
    # Получаем пути к моделям
    damage_model_path = get_model_path("pp2/best.pt")
    part_model_path = get_model_path("pp1/best.pt")
    
    if not damage_model_path or not part_model_path:
        print("❌ Не удалось найти модели. Проверьте пути к файлам моделей.")
        return None, None
    
    # Загружаем модели
    print("🔧 Загружаем модель повреждений...")
    damage_model = YOLO(damage_model_path)
    print("🔧 Загружаем модель частей автомобиля...")
    part_model = YOLO(part_model_path)
    print("✅ Модели загружены успешно")
    
    folders = create_output_folders()
    image_name = os.path.splitext(os.path.basename(image_path))[0]
    
    print(f"Анализ изображения: {image_path}")
    print("-" * 50)
    
    image = cv2.imread(image_path)
    if image is None:
        print("Ошибка: не удалось загрузить изображение")
        return None, None
    
    image_dimensions = image.shape  # (height, width, channels)
    
    print("Поиск повреждений...")
    damage_results = damage_model(image, conf=confidence_threshold)
    damage_boxes = []
    damage_labels = []
    
    for result in damage_results:
        for box in result.boxes:
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
            damage_boxes.append([x1, y1, x2, y2])
            original_damage_label = damage_model.names[int(box.cls[0])]
            # Преобразуем на русский
            russian_damage_label = map_damage_to_russian(original_damage_label)
            damage_labels.append(russian_damage_label)
    
    print(f"Найдено повреждений: {len(damage_boxes)}")
    print("Типы повреждений:", ", ".join(set(damage_labels)))
    
    print("Определение частей машины...")
    part_results = part_model(image, conf=confidence_threshold)
    part_boxes = []
    part_labels = []
    
    for result in part_results:
        for box in result.boxes:
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
            part_boxes.append([x1, y1, x2, y2])
            original_part_label = part_model.names[int(box.cls[0])]
            # Преобразуем на русский
            russian_part_label = map_yolo_part_to_russian(original_part_label)
            part_labels.append(russian_part_label)
    
    print(f"Найдено частей машины: {len(part_boxes)}")
    print("Обнаруженные части:", ", ".join(set(part_labels)))
    
    print("\n" + "=" * 50)
    print("РЕЗУЛЬТАТЫ АНАЛИЗА:")
    print("=" * 50)
    
    if len(damage_boxes) == 0:
        print("Повреждений не обнаружено")
        saved_paths = save_intersection_images(image, [], [], part_boxes, part_labels, [], folders, image_name)
        # Сохраняем JSON даже если повреждений нет
        json_path = save_damage_data_to_json([], [], [], part_boxes, part_labels, folders, image_name, image_path, image_dimensions)
        saved_paths['json_path'] = json_path
        return [], saved_paths
    
    if len(part_boxes) == 0:
        print("Части машины не обнаружены")
        matches = find_damage_parts(damage_boxes, damage_labels, part_boxes, part_labels)
        saved_paths = save_intersection_images(image, damage_boxes, damage_labels, [], [], matches, folders, image_name)
        json_path = save_damage_data_to_json(matches, damage_boxes, damage_labels, part_boxes, part_labels, folders, image_name, image_path, image_dimensions)
        saved_paths['json_path'] = json_path
        return matches, saved_paths
    
    matches = find_damage_parts(damage_boxes, damage_labels, part_boxes, part_labels)
    
    saved_paths = save_intersection_images(image, damage_boxes, damage_labels, part_boxes, part_labels, matches, folders, image_name)
    
    # Сохраняем данные в JSON
    json_path = save_damage_data_to_json(matches, damage_boxes, damage_labels, part_boxes, part_labels, folders, image_name, image_path, image_dimensions)
    saved_paths['json_path'] = json_path
    
    for i, match in enumerate(matches):
        print(f"Повреждение #{i+1}:")
        print(f"  Тип повреждения: {match['damage_type']}")
        print(f"  Часть машины: {match['part_name']}")
        print(f"  Уверенность сопоставления: {match['iou']:.2f}")
        if match['part_index'] != -1:
            print(f"  Координаты части: {part_boxes[match['part_index']]}")
        print("-" * 30)

    print("\nСВОДНАЯ СТАТИСТИКА:")
    part_damage_count = {}
    damage_type_count = {}
    for match in matches:
        part = match['part_name']
        damage_type = match['damage_type']
        part_damage_count[part] = part_damage_count.get(part, 0) + 1
        damage_type_count[damage_type] = damage_type_count.get(damage_type, 0) + 1

    print("По частям автомобиля:")
    for part, count in part_damage_count.items():
        print(f"  {part}: {count} повреждений")
    
    print("По типам повреждений:")
    for damage_type, count in damage_type_count.items():
        print(f"  {damage_type}: {count} случаев")
    
    print(f"\nСохраненные файлы:")
    for key, path in saved_paths.items():
        print(f"  {key}: {path}")
    
    return matches, saved_paths

def main():
    parser = argparse.ArgumentParser(description='Анализ повреждений автомобиля')
    parser.add_argument('--image', required=True, help='Путь к изображению')
    parser.add_argument('--brand', required=True, help='Марка автомобиля')
    parser.add_argument('--model', required=True, help='Модель автомобиля')
    parser.add_argument('--output', required=True, help='Путь для сохранения результатов JSON')
    parser.add_argument('--confidence', type=float, default=0.5, help='Порог уверенности для детекции')
    
    args = parser.parse_args()
    
    print("🚗 Запуск анализа повреждений автомобиля")
    print(f"📁 Изображение: {args.image}")
    print(f"🚙 Марка: {args.brand}")
    print(f"🚗 Модель: {args.model}")
    print(f"🎯 Уверенность: {args.confidence}")
    print("-" * 50)
    
    # Проверяем существование изображения
    if not os.path.exists(args.image):
        print(f"❌ Файл изображения не найден: {args.image}")
        # Сохраняем ошибку в выходной файл
        error_result = {
            "error": f"Файл изображения не найден: {args.image}",
            "damages": []
        }
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(error_result, f, ensure_ascii=False, indent=2)
        return
    
    # Запускаем анализ
    matches, saved_paths = analyze_car_damage(args.image, args.confidence)
    
    # Формируем результат для веб-интерфейса на русском языке
    if matches is not None:
        result_data = {
            "damages": [
                {
                    "part": match['part_name'],  # Уже на русском
                    "severity": determine_severity(match['damage_type'], match['iou'], 0.1),  # Автоматическое определение тяжести
                    "confidence": match['iou'],
                    "location": f"Область {match['damage_index'] + 1}",
                    "type": match['damage_type']  # Уже на русском
                }
                for match in matches
            ],
            "analysis_info": {
                "total_damages": len(matches),
                "image_path": args.image,
                "brand": args.brand,
                "model": args.model,
                "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        }
    else:
        result_data = {
            "error": "Не удалось выполнить анализ повреждений",
            "damages": []
        }
    
    # Сохраняем результат в указанный файл
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ Результаты сохранены в: {args.output}")

if __name__ == "__main__":
    main()
