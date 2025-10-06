import cv2
import numpy as np
import os
from datetime import datetime
from ultralytics import YOLO

def create_output_folders():
    base_dir = "analysis_results"
    folders = {
        'base': base_dir,
        'damages': os.path.join(base_dir, "damages"),
        'parts': os.path.join(base_dir, "parts"),
        'intersections': os.path.join(base_dir, "intersections"),
        'final_result': os.path.join(base_dir, "final_result")
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

def find_damage_parts(damage_boxes, part_boxes, part_labels, iou_threshold=0.1):
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
            'part_name': best_part_label,
            'iou': best_iou,
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

def save_intersection_images(original_image, damage_boxes, part_boxes, part_labels, matches, folders, image_name):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    damage_image = draw_boxes(original_image, damage_boxes, [f"Damage {i}" for i in range(len(damage_boxes))], (0, 0, 255))
    damage_path = os.path.join(folders['damages'], f"{image_name}_damages_{timestamp}.jpg")
    cv2.imwrite(damage_path, damage_image)
    print(f"Сохранено изображение с повреждениями: {damage_path}")
    
    part_image = draw_boxes(original_image, part_boxes, part_labels, (0, 255, 0))
    part_path = os.path.join(folders['parts'], f"{image_name}_parts_{timestamp}.jpg")
    cv2.imwrite(part_path, part_image)
    print(f"Сохранено изображение с частями: {part_path}")
    
    intersection_image = original_image.copy()
    
    for i, part_box in enumerate(part_boxes):
        x1, y1, x2, y2 = map(int, part_box)
        cv2.rectangle(intersection_image, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(intersection_image, part_labels[i], (x1, y1 - 10), 
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    
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
            
            label = f"{match['part_name']} (IoU: {match['iou']:.2f})"
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

damage_model = YOLO("pp2/best.pt")
part_model = YOLO("pp1/best.pt")

def analyze_car_damage(image_path, confidence_threshold=0.5):
    folders = create_output_folders()
    image_name = os.path.splitext(os.path.basename(image_path))[0]
    
    print(f"Анализ изображения: {image_path}")
    print("-" * 50)
    
    image = cv2.imread(image_path)
    if image is None:
        print("Ошибка: не удалось загрузить изображение")
        return
    
    print("Поиск повреждений...")
    damage_results = damage_model(image, conf=confidence_threshold)
    damage_boxes = []
    
    for result in damage_results:
        for box in result.boxes:
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
            damage_boxes.append([x1, y1, x2, y2])
    
    print(f"Найдено повреждений: {len(damage_boxes)}")
    
    print("Определение частей машины...")
    part_results = part_model(image, conf=confidence_threshold)
    part_boxes = []
    part_labels = []
    
    for result in part_results:
        for box in result.boxes:
            x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
            part_boxes.append([x1, y1, x2, y2])
            part_labels.append(part_model.names[int(box.cls[0])])
    
    print(f"Найдено частей машины: {len(part_boxes)}")
    print("Обнаруженные части:", ", ".join(set(part_labels)))
    
    print("\n" + "=" * 50)
    print("РЕЗУЛЬТАТЫ АНАЛИЗА:")
    print("=" * 50)
    
    if len(damage_boxes) == 0:
        print("Повреждений не обнаружено")
        save_intersection_images(image, [], part_boxes, part_labels, [], folders, image_name)
        return []
    
    if len(part_boxes) == 0:
        print("Части машины не обнаружены")
        matches = find_damage_parts(damage_boxes, part_boxes, part_labels)
        save_intersection_images(image, damage_boxes, [], [], matches, folders, image_name)
        return matches
    
    matches = find_damage_parts(damage_boxes, part_boxes, part_labels)
    
    saved_paths = save_intersection_images(image, damage_boxes, part_boxes, part_labels, matches, folders, image_name)
    
    for i, match in enumerate(matches):
        print(f"Повреждение #{i+1}:")
        print(f"  Часть машины: {match['part_name']}")
        print(f"  Уверенность сопоставления: {match['iou']:.2f}")
        if match['part_index'] != -1:
            print(f"  Координаты части: {part_boxes[match['part_index']]}")
        print("-" * 30)

    print("\nСВОДНАЯ СТАТИСТИКА:")
    part_damage_count = {}
    for match in matches:
        part = match['part_name']
        part_damage_count[part] = part_damage_count.get(part, 0) + 1

    for part, count in part_damage_count.items():
        print(f"{part}: {count} повреждений")
    
    print(f"\nСохраненные файлы:")
    for key, path in saved_paths.items():
        print(f"  {key}: {path}")
    
    return matches, saved_paths

if __name__ == "__main__":
    image_path = "car_image.jpg"
    
    if not os.path.exists(image_path):
        print(f"Ошибка: файл {image_path} не найден")
        exit(1)
    
    analyze_car_damage(image_path, confidence_threshold=0.5)
